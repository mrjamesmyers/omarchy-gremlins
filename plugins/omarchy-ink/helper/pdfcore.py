#!/usr/bin/env python3
"""
A small PDF reader and incremental-update writer, standard library only.

Omarchy plugins are cloned, not installed, so pypdf is not available and asking
somebody to run pip before they can sign a form is the same as not shipping the
feature. This implements the subset needed to annotate a document:

  read   the trailer, both classic cross-reference tables and the cross-reference
         streams that every PDF since 1.5 uses, object streams, and enough of the
         page tree to enumerate pages with their boxes
  write  an incremental update - the original file is copied byte for byte and
         new objects are appended after it, so the document you started with is
         still in there untouched and a bad annotation cannot corrupt it

What it deliberately does not do: encryption, font embedding, image XObjects.
Annotations are vector ink and text in the standard fonts, which is what
signing and filling actually need.
"""

import re
import zlib

WHITESPACE = b"\x00\t\n\x0c\r "
DELIMITERS = b"()<>[]{}/%"


class PdfError(Exception):
    pass


class Name(str):
    """A PDF name. A distinct type so /Foo never collides with the string 'Foo'."""
    __slots__ = ()


class Ref:
    __slots__ = ("num", "gen")

    def __init__(self, num, gen=0):
        self.num, self.gen = num, gen

    def __repr__(self):
        return "Ref(%d,%d)" % (self.num, self.gen)

    def __eq__(self, other):
        return isinstance(other, Ref) and (self.num, self.gen) == (other.num, other.gen)

    def __hash__(self):
        return hash((self.num, self.gen))


class Stream:
    __slots__ = ("dict", "raw")

    def __init__(self, dictionary, raw):
        self.dict, self.raw = dictionary, raw

    def data(self):
        """Decoded bytes. Only the filters that actually appear in the wild."""
        filters = self.dict.get("Filter")
        if filters is None:
            return self.raw
        if isinstance(filters, (Name, str)):
            filters = [filters]
        out = self.raw
        params = self.dict.get("DecodeParms") or self.dict.get("DP")
        if isinstance(params, dict) or params is None:
            params = [params] * len(filters)
        for f, parm in zip(filters, params):
            if f in ("FlateDecode", "Fl"):
                out = zlib.decompress(out)
                out = apply_predictor(out, parm)
            elif f in ("ASCIIHexDecode", "AHx"):
                hexed = re.sub(rb"[^0-9A-Fa-f>]", b"", out).split(b">")[0]
                if len(hexed) % 2:
                    hexed += b"0"
                out = bytes.fromhex(hexed.decode("ascii"))
            else:
                raise PdfError("unsupported stream filter: %s" % f)
        return out


def apply_predictor(data, parm):
    """Undo the PNG predictors that cross-reference streams almost always use."""
    if not isinstance(parm, dict):
        return data
    predictor = int(parm.get("Predictor", 1) or 1)
    if predictor < 2:
        return data
    colors = int(parm.get("Colors", 1) or 1)
    bpc = int(parm.get("BitsPerComponent", 8) or 8)
    columns = int(parm.get("Columns", 1) or 1)
    sample = max(1, (colors * bpc + 7) // 8)
    row_len = (columns * colors * bpc + 7) // 8

    if predictor == 2:                      # TIFF predictor
        if bpc != 8:
            raise PdfError("TIFF predictor with bpc %d is not supported" % bpc)
        out = bytearray(data)
        for r in range(0, len(out), row_len):
            for i in range(sample, row_len):
                if r + i < len(out):
                    out[r + i] = (out[r + i] + out[r + i - sample]) & 0xFF
        return bytes(out)

    # PNG predictors: each row is prefixed with a filter-type byte.
    out = bytearray()
    previous = bytearray(row_len)
    pos = 0
    while pos + 1 <= len(data) - 1:
        ftype = data[pos]
        pos += 1
        row = bytearray(data[pos:pos + row_len])
        if not row:
            break
        pos += row_len
        if ftype == 0:
            pass
        elif ftype == 1:
            for i in range(sample, len(row)):
                row[i] = (row[i] + row[i - sample]) & 0xFF
        elif ftype == 2:
            for i in range(len(row)):
                row[i] = (row[i] + previous[i]) & 0xFF
        elif ftype == 3:
            for i in range(len(row)):
                left = row[i - sample] if i >= sample else 0
                row[i] = (row[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(len(row)):
                a = row[i - sample] if i >= sample else 0
                b = previous[i]
                c = previous[i - sample] if i >= sample else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                row[i] = (row[i] + pred) & 0xFF
        else:
            raise PdfError("unknown PNG predictor row type %d" % ftype)
        out += row
        previous = row
    return bytes(out)


# --------------------------------------------------------------------------
# tokenising and parsing
# --------------------------------------------------------------------------

class Parser:
    def __init__(self, data, pos=0):
        self.data, self.pos = data, pos

    def skip_space(self):
        d, n = self.data, len(self.data)
        while self.pos < n:
            c = d[self.pos]
            if c in WHITESPACE:
                self.pos += 1
            elif c == 0x25:                 # '%' comment to end of line
                while self.pos < n and d[self.pos] not in b"\r\n":
                    self.pos += 1
            else:
                return

    def parse(self):
        self.skip_space()
        if self.pos >= len(self.data):
            raise PdfError("unexpected end of data")
        c = self.data[self.pos]

        if c == 0x2F:                       # /Name
            return self.parse_name()
        if c == 0x28:                       # (string)
            return self.parse_literal_string()
        if c == 0x3C:                       # << dict >> or <hex>
            if self.data[self.pos:self.pos + 2] == b"<<":
                return self.parse_dict()
            return self.parse_hex_string()
        if c == 0x5B:                       # [array]
            return self.parse_array()
        if c == 0x5D or c == 0x3E:
            raise PdfError("unbalanced delimiter at %d" % self.pos)
        return self.parse_keyword_or_number()

    def parse_name(self):
        self.pos += 1
        start = self.pos
        d, n = self.data, len(self.data)
        while self.pos < n and d[self.pos] not in WHITESPACE and d[self.pos] not in DELIMITERS:
            self.pos += 1
        raw = d[start:self.pos]
        # #xx escapes are legal inside names and appear in real files.
        if b"#" in raw:
            out = bytearray()
            i = 0
            while i < len(raw):
                if raw[i] == 0x23 and i + 2 < len(raw):
                    try:
                        out.append(int(raw[i + 1:i + 3], 16))
                        i += 3
                        continue
                    except ValueError:
                        pass
                out.append(raw[i])
                i += 1
            raw = bytes(out)
        return Name(raw.decode("latin-1"))

    def parse_literal_string(self):
        self.pos += 1
        out = bytearray()
        depth = 1
        d, n = self.data, len(self.data)
        while self.pos < n:
            c = d[self.pos]
            if c == 0x5C:                   # backslash escape
                self.pos += 1
                if self.pos >= n:
                    break
                e = d[self.pos]
                mapping = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}
                if e in mapping:
                    out.append(mapping[e])
                    self.pos += 1
                elif 0x30 <= e <= 0x37:     # octal
                    digits = bytearray()
                    while len(digits) < 3 and self.pos < n and 0x30 <= d[self.pos] <= 0x37:
                        digits.append(d[self.pos])
                        self.pos += 1
                    out.append(int(digits, 8) & 0xFF)
                elif e in b"\r\n":          # line continuation
                    self.pos += 1
                    if self.pos < n and d[self.pos] in b"\n" and e == 0x0D:
                        self.pos += 1
                else:
                    out.append(e)
                    self.pos += 1
                continue
            if c == 0x28:
                depth += 1
            elif c == 0x29:
                depth -= 1
                if depth == 0:
                    self.pos += 1
                    return bytes(out)
            out.append(c)
            self.pos += 1
        raise PdfError("unterminated string")

    def parse_hex_string(self):
        self.pos += 1
        end = self.data.find(b">", self.pos)
        if end < 0:
            raise PdfError("unterminated hex string")
        hexed = re.sub(rb"[^0-9A-Fa-f]", b"", self.data[self.pos:end])
        self.pos = end + 1
        if len(hexed) % 2:
            hexed += b"0"
        return bytes.fromhex(hexed.decode("ascii"))

    def parse_array(self):
        self.pos += 1
        out = []
        while True:
            self.skip_space()
            if self.pos >= len(self.data):
                raise PdfError("unterminated array")
            if self.data[self.pos] == 0x5D:
                self.pos += 1
                return out
            out.append(self.parse())

    def parse_dict(self):
        self.pos += 2
        out = {}
        while True:
            self.skip_space()
            if self.data[self.pos:self.pos + 2] == b">>":
                self.pos += 2
                break
            key = self.parse()
            if not isinstance(key, Name):
                raise PdfError("dictionary key is not a name at %d" % self.pos)
            out[str(key)] = self.parse()

        # A dictionary followed by `stream` owns the bytes that come after it.
        save = self.pos
        self.skip_space()
        if self.data[self.pos:self.pos + 6] == b"stream":
            self.pos += 6
            if self.data[self.pos:self.pos + 2] == b"\r\n":
                self.pos += 2
            elif self.pos < len(self.data) and self.data[self.pos] in b"\n\r":
                self.pos += 1
            length = out.get("Length")
            start = self.pos
            if isinstance(length, int) and length >= 0 and start + length <= len(self.data):
                raw = self.data[start:start + length]
                after = self.data.find(b"endstream", start + length)
                self.pos = (after + 9) if after >= 0 else start + length
                # A wrong /Length is common enough that it is worth checking.
                if after < 0 or after - (start + length) > 4:
                    raw, self.pos = self._scan_stream(start)
            else:
                raw, self.pos = self._scan_stream(start)
            return Stream(out, raw)
        self.pos = save
        return out

    def _scan_stream(self, start):
        """Recover a stream whose /Length is wrong or indirect."""
        end = self.data.find(b"endstream", start)
        if end < 0:
            raise PdfError("unterminated stream")
        raw = self.data[start:end]
        if raw.endswith(b"\r\n"):
            raw = raw[:-2]
        elif raw.endswith(b"\n") or raw.endswith(b"\r"):
            raw = raw[:-1]
        return raw, end + 9

    def parse_keyword_or_number(self):
        d, n = self.data, len(self.data)
        start = self.pos
        while self.pos < n and d[self.pos] not in WHITESPACE and d[self.pos] not in DELIMITERS:
            self.pos += 1
        token = d[start:self.pos]
        if not token:
            raise PdfError("empty token at %d" % start)

        if token == b"true":
            return True
        if token == b"false":
            return False
        if token == b"null":
            return None

        if re.fullmatch(rb"[+-]?\d+", token):
            # "12 0 R" is a reference; "12 0 obj" starts one. Look ahead.
            save = self.pos
            try:
                self.skip_space()
                s2 = self.pos
                while self.pos < n and d[self.pos] not in WHITESPACE and d[self.pos] not in DELIMITERS:
                    self.pos += 1
                second = d[s2:self.pos]
                if re.fullmatch(rb"\d+", second):
                    self.skip_space()
                    s3 = self.pos
                    while self.pos < n and d[self.pos] not in WHITESPACE and d[self.pos] not in DELIMITERS:
                        self.pos += 1
                    third = d[s3:self.pos]
                    if third == b"R":
                        return Ref(int(token), int(second))
            except PdfError:
                pass
            self.pos = save
            return int(token)

        if re.fullmatch(rb"[+-]?(\d*\.\d*|\d+)", token):
            try:
                return float(token)
            except ValueError:
                return 0.0
        return Name(token.decode("latin-1"))


# --------------------------------------------------------------------------
# the document
# --------------------------------------------------------------------------

class Document:
    def __init__(self, data):
        self.data = data
        self.xref = {}          # objnum -> ("n", offset) | ("o", stream_objnum, index)
        self.trailer = {}
        self._cache = {}
        # An incremental update should use the same cross-reference flavour as
        # the file it is updating; mixing the two confuses some readers.
        self.uses_xref_streams = False
        # Where the newest cross-reference section starts, or None when the
        # file had no usable one and the table was rebuilt by scanning.
        self.startxref = None
        self._load_xref()

    @classmethod
    def open(cls, path):
        with open(path, "rb") as fh:
            return cls(fh.read())

    # -- cross references ---------------------------------------------------

    def _startxref(self):
        tail = self.data[-2048:]
        matches = list(re.finditer(rb"startxref\s+(\d+)", tail))
        if not matches:
            raise PdfError("no startxref - not a PDF, or truncated")
        return int(matches[-1].group(1))

    def _load_xref(self):
        seen = set()
        try:
            offset = self._startxref()
        except PdfError:
            # No usable pointer. This is precisely when scanning is needed, so
            # raising here would make the recovery path unreachable.
            self._rebuild_by_scanning()
            return
        self.startxref = offset
        while offset is not None and offset not in seen and 0 <= offset < len(self.data):
            seen.add(offset)
            trailer = self._read_xref_section(offset)
            if trailer is None:
                break
            for key, value in trailer.items():
                self.trailer.setdefault(key, value)
            # A hybrid file points at both; /XRefStm carries the entries for
            # objects the classic table cannot describe.
            hybrid = trailer.get("XRefStm")
            if isinstance(hybrid, int) and hybrid not in seen:
                seen.add(hybrid)
                self._read_xref_section(hybrid)
            nxt = trailer.get("Prev")
            offset = int(nxt) if isinstance(nxt, (int, float)) else None

        if not self.xref or "Root" not in self.trailer:
            self._rebuild_by_scanning()
            self.startxref = None

    def _read_xref_section(self, offset):
        parser = Parser(self.data, offset)
        parser.skip_space()
        if self.data[parser.pos:parser.pos + 4] == b"xref":
            return self._read_xref_table(parser)
        result = self._read_xref_stream(offset)
        if result is not None:
            self.uses_xref_streams = True
        return result

    def _read_xref_table(self, parser):
        parser.pos += 4
        while True:
            parser.skip_space()
            if self.data[parser.pos:parser.pos + 7] == b"trailer":
                parser.pos += 7
                trailer = parser.parse()
                return trailer if isinstance(trailer, dict) else {}
            first = parser.parse()
            count = parser.parse()
            if not isinstance(first, int) or not isinstance(count, int):
                return {}
            parser.skip_space()
            for i in range(count):
                entry = self.data[parser.pos:parser.pos + 20]
                m = re.match(rb"\s*(\d{1,10})\s+(\d{1,5})\s+([nf])", entry)
                if not m:
                    return {}
                if m.group(3) == b"n":
                    # First writer wins: we walk newest to oldest.
                    self.xref.setdefault(first + i, ("n", int(m.group(1))))
                parser.pos += 20 if len(entry) >= 20 and entry[18:19] in b"\r\n " else m.end()

    def _read_xref_stream(self, offset):
        parser = Parser(self.data, offset)
        parser.skip_space()
        m = re.match(rb"(\d+)\s+(\d+)\s+obj", self.data[parser.pos:parser.pos + 32])
        if not m:
            return None
        parser.pos += m.end()
        obj = parser.parse()
        if not isinstance(obj, Stream) or obj.dict.get("Type") not in (None, "XRef"):
            return None

        widths = [int(w) for w in obj.dict.get("W", [1, 1, 1])]
        size = int(obj.dict.get("Size", 0) or 0)
        index = obj.dict.get("Index") or [0, size]
        index = [int(v) for v in index]
        payload = obj.data()

        row = sum(widths)
        pos = 0
        for i in range(0, len(index) - 1, 2):
            start, count = index[i], index[i + 1]
            for j in range(count):
                if pos + row > len(payload):
                    break
                fields = []
                for w in widths:
                    fields.append(int.from_bytes(payload[pos:pos + w], "big") if w else None)
                    pos += w
                kind = fields[0] if widths[0] else 1      # default type is 1
                num = start + j
                if kind == 1:
                    self.xref.setdefault(num, ("n", fields[1]))
                elif kind == 2:
                    self.xref.setdefault(num, ("o", fields[1], fields[2]))
        return obj.dict

    def _rebuild_by_scanning(self):
        """Last resort for a damaged file: find every `N G obj` in the bytes."""
        for m in re.finditer(rb"(?:^|[\s>])(\d+)\s+(\d+)\s+obj\b", self.data):
            self.xref[int(m.group(1))] = ("n", m.start(1))
        if "Root" not in self.trailer:
            for m in re.finditer(rb"trailer", self.data):
                try:
                    t = Parser(self.data, m.end()).parse()
                    if isinstance(t, dict) and "Root" in t:
                        self.trailer.update(t)
                except PdfError:
                    continue
            if "Root" not in self.trailer:
                # Catalog without a usable trailer - find it directly.
                for num in list(self.xref):
                    try:
                        obj = self.get(num)
                    except PdfError:
                        continue
                    d = obj.dict if isinstance(obj, Stream) else obj
                    if isinstance(d, dict) and d.get("Type") == "Catalog":
                        self.trailer["Root"] = Ref(num, 0)
                        break

    # -- objects ------------------------------------------------------------

    def get(self, num):
        if num in self._cache:
            return self._cache[num]
        entry = self.xref.get(num)
        if entry is None:
            return None
        self._cache[num] = None                 # break reference cycles
        try:
            if entry[0] == "n":
                value = self._parse_at(entry[1], num)
            else:
                value = self._from_object_stream(entry[1], entry[2], num)
        except (PdfError, zlib.error, ValueError):
            value = None
        self._cache[num] = value
        return value

    def _parse_at(self, offset, expect):
        if not (0 <= offset < len(self.data)):
            raise PdfError("offset %d out of range" % offset)
        window = self.data[offset:offset + 48]
        m = re.match(rb"\s*(\d+)\s+(\d+)\s+obj", window)
        if not m:
            # Offsets are often a few bytes out in files produced by bad
            # writers; look nearby for the header before giving up.
            near = self.data[max(0, offset - 64):offset + 256]
            m2 = re.search(rb"(?<![0-9])" + str(expect).encode() + rb"\s+\d+\s+obj", near)
            if not m2:
                raise PdfError("no object header at %d" % offset)
            offset = max(0, offset - 64) + m2.start()
            m = re.match(rb"\s*(\d+)\s+(\d+)\s+obj", self.data[offset:offset + 48])
        parser = Parser(self.data, offset + m.end())
        return parser.parse()

    def _from_object_stream(self, container, index, want):
        stream = self.get(container)
        if not isinstance(stream, Stream):
            raise PdfError("object stream %d is missing" % container)
        payload = stream.data()
        n = int(self.resolve(stream.dict.get("N", 0)) or 0)
        first = int(self.resolve(stream.dict.get("First", 0)) or 0)
        header = Parser(payload, 0)
        pairs = []
        for _ in range(n):
            num = header.parse()
            off = header.parse()
            pairs.append((int(num), int(off)))
        for i, (num, off) in enumerate(pairs):
            if num == want or i == index:
                return Parser(payload, first + off).parse()
        raise PdfError("object %d not in stream %d" % (want, container))

    def resolve(self, value, depth=0):
        while isinstance(value, Ref) and depth < 64:
            value = self.get(value.num)
            depth += 1
        return value

    def dget(self, dictionary, key, default=None):
        if isinstance(dictionary, Stream):
            dictionary = dictionary.dict
        if not isinstance(dictionary, dict):
            return default
        value = dictionary.get(key, default)
        return self.resolve(value)

    # -- pages --------------------------------------------------------------

    def pages(self):
        """Every page, in order, with the object number that owns it."""
        root = self.dget(self.trailer, "Root")
        tree = self.dget(root, "Pages") if isinstance(root, dict) else None
        found = []
        if isinstance(tree, dict):
            self._walk_pages(tree, found, set(), {})
        if not found:
            # No usable page tree; take every /Type /Page object we can see.
            for num in sorted(self.xref):
                obj = self.get(num)
                d = obj.dict if isinstance(obj, Stream) else obj
                if isinstance(d, dict) and d.get("Type") == "Page":
                    found.append((num, d, self._inherited(d, {})))
        return [self._page_info(i, num, d, inh) for i, (num, d, inh) in enumerate(found)]

    INHERITED = ("Resources", "MediaBox", "CropBox", "Rotate")

    def _inherited(self, node, parent_values):
        out = dict(parent_values)
        for key in self.INHERITED:
            if key in node:
                out[key] = node[key]
        return out

    def _walk_pages(self, node, out, seen, inherited, depth=0):
        if depth > 64 or not isinstance(node, dict):
            return
        values = self._inherited(node, inherited)
        kids = self.dget(node, "Kids")
        if node.get("Type") == "Page" or (kids is None and "Contents" in node):
            num = self._number_of(node)
            if num is not None and num not in seen:
                seen.add(num)
                out.append((num, node, values))
            return
        if not isinstance(kids, list):
            return
        for kid in kids:
            num = kid.num if isinstance(kid, Ref) else None
            child = self.resolve(kid)
            if not isinstance(child, dict):
                continue
            if child.get("Type") == "Page" or "Contents" in child or "Kids" not in child:
                if num is not None and num not in seen:
                    seen.add(num)
                    out.append((num, child, self._inherited(child, values)))
            else:
                self._walk_pages(child, out, seen, values, depth + 1)

    def _number_of(self, target):
        for num in self.xref:
            if self._cache.get(num) is target:
                return num
        for num in sorted(self.xref):
            if self.get(num) is target:
                return num
        return None

    def _page_info(self, index, num, node, inherited):
        box = self.resolve(node.get("MediaBox", inherited.get("MediaBox")))
        if not (isinstance(box, list) and len(box) == 4):
            box = [0, 0, 612, 792]                  # US Letter, the PDF default
        box = [float(self.resolve(v) or 0) for v in box]
        x0, y0, x1, y1 = min(box[0], box[2]), min(box[1], box[3]), \
                         max(box[0], box[2]), max(box[1], box[3])
        rotate = self.resolve(node.get("Rotate", inherited.get("Rotate", 0))) or 0
        try:
            rotate = int(rotate) % 360
        except (TypeError, ValueError):
            rotate = 0
        return {
            "index": index,
            "objnum": num,
            "width": round(x1 - x0, 3),
            "height": round(y1 - y0, 3),
            "x0": round(x0, 3),
            "y0": round(y0, 3),
            "rotate": rotate,
        }


# --------------------------------------------------------------------------
# serialising
# --------------------------------------------------------------------------

def _escape_string(raw):
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    out = bytearray(b"(")
    for byte in raw:
        if byte in (0x28, 0x29, 0x5C):      # ( ) \
            out += b"\\" + bytes([byte])
        elif byte == 0x0A:
            out += b"\\n"
        elif byte == 0x0D:
            out += b"\\r"
        elif byte < 32 or byte > 126:
            out += ("\\%03o" % byte).encode("ascii")
        else:
            out.append(byte)
    out += b")"
    return bytes(out)


def _escape_name(text):
    out = bytearray(b"/")
    for byte in str(text).encode("latin-1", "replace"):
        if byte in WHITESPACE or byte in DELIMITERS or byte == 0x23 or byte < 33 or byte > 126:
            out += ("#%02X" % byte).encode("ascii")
        else:
            out.append(byte)
    return bytes(out)


def serialise(value):
    if value is None:
        return b"null"
    if isinstance(value, bool):
        return b"true" if value else b"false"
    if isinstance(value, Ref):
        return b"%d %d R" % (value.num, value.gen)
    if isinstance(value, Name):
        return _escape_name(value)
    if isinstance(value, int):
        return b"%d" % value
    if isinstance(value, float):
        # No exponent form: PDF real syntax does not allow it.
        text = ("%.6f" % value).rstrip("0").rstrip(".")
        return (text or "0").encode("ascii")
    if isinstance(value, (bytes, bytearray)):
        return _escape_string(bytes(value))
    if isinstance(value, str):
        return _escape_string(value)
    if isinstance(value, list):
        return b"[" + b" ".join(serialise(v) for v in value) + b"]"
    if isinstance(value, dict):
        parts = [_escape_name(k) + b" " + serialise(v) for k, v in value.items()]
        return b"<<" + b" ".join(parts) + b">>"
    if isinstance(value, Stream):
        body = value.raw
        d = dict(value.dict)
        d["Length"] = len(body)
        return serialise(d) + b"\nstream\n" + body + b"\nendstream"
    raise PdfError("cannot serialise %r" % type(value))


# --------------------------------------------------------------------------
# drawing
# --------------------------------------------------------------------------

def _num(v):
    text = ("%.4f" % float(v)).rstrip("0").rstrip(".")
    return (text or "0").encode("ascii")


def build_content(ops, font_name="OmaHelv"):
    """Turn annotation operations into a PDF content stream.

    Coordinates are PDF user space: origin bottom-left, y upwards. Callers
    working in screen coordinates convert before calling.
    """
    out = bytearray()
    uses_font = False

    for op in ops:
        kind = op.get("type")
        colour = op.get("colour", op.get("color", [0, 0, 0]))
        try:
            r, g, b = [max(0.0, min(1.0, float(c))) for c in colour[:3]]
        except (TypeError, ValueError):
            r = g = b = 0.0

        if kind == "ink":
            points = op.get("points") or []
            if len(points) < 2:
                continue
            width = float(op.get("width", 2.0))
            out += b"q\n"
            out += b"%s %s %s RG\n" % (_num(r), _num(g), _num(b))
            out += b"%s w\n1 J 1 j\n" % _num(width)
            first = points[0]
            out += b"%s %s m\n" % (_num(first[0]), _num(first[1]))
            for point in points[1:]:
                out += b"%s %s l\n" % (_num(point[0]), _num(point[1]))
            out += b"S\nQ\n"

        elif kind == "text":
            body = op.get("text", "")
            if not body:
                continue
            size = float(op.get("size", 12.0))
            x, y = float(op.get("x", 0)), float(op.get("y", 0))
            uses_font = True
            out += b"q\nBT\n"
            out += _escape_name(font_name) + b" %s Tf\n" % _num(size)
            out += b"%s %s %s rg\n" % (_num(r), _num(g), _num(b))
            out += b"%s %s Td\n" % (_num(x), _num(y))
            leading = size * 1.2
            lines = str(body).split("\n")
            for i, line in enumerate(lines):
                if i:
                    out += b"0 %s Td\n" % _num(-leading)
                # WinAnsi is what the standard fonts expect.
                out += _escape_string(line.encode("cp1252", "replace")) + b" Tj\n"
            out += b"ET\nQ\n"

        elif kind in ("rect", "highlight"):
            x, y = float(op.get("x", 0)), float(op.get("y", 0))
            w, h = float(op.get("width", 0)), float(op.get("height", 0))
            out += b"q\n"
            if kind == "highlight":
                # Multiply keeps the text underneath readable.
                out += b"%s %s %s rg\n" % (_num(r), _num(g), _num(b))
                out += b"/OmaMultiply gs\n"
                out += b"%s %s %s %s re\nf\n" % (_num(x), _num(y), _num(w), _num(h))
            else:
                out += b"%s %s %s RG\n" % (_num(r), _num(g), _num(b))
                out += b"%s w\n" % _num(float(op.get("line", 1.5)))
                out += b"%s %s %s %s re\nS\n" % (_num(x), _num(y), _num(w), _num(h))
            out += b"Q\n"

    return bytes(out), uses_font


def needs_multiply(ops):
    return any(op.get("type") == "highlight" for op in ops)


# --------------------------------------------------------------------------
# incremental update
# --------------------------------------------------------------------------

HELVETICA = {
    "Type": Name("Font"),
    "Subtype": Name("Type1"),
    "BaseFont": Name("Helvetica"),
    "Encoding": Name("WinAnsiEncoding"),
}

MULTIPLY = {"Type": Name("ExtGState"), "BM": Name("Multiply")}


def annotate(document, annotations, compress=True):
    """Return the bytes to append to `document.data` to add `annotations`.

    annotations: {page_index: [op, ...]} in PDF user-space coordinates.

    The original bytes are never rewritten. Everything new is appended after
    them, with a cross-reference section that points back at the previous one,
    so the document you started with is still intact inside the result - and a
    bad annotation costs you an undo, not a file.
    """
    pages = document.pages()
    by_index = {p["index"]: p for p in pages}

    next_num = max([int(document.trailer.get("Size", 0) or 0) - 1] + list(document.xref) or [0]) + 1
    new_objects = {}          # objnum -> value

    def allocate(value):
        nonlocal next_num
        num = next_num
        next_num += 1
        new_objects[num] = value
        return Ref(num, 0)

    touched = False
    for index in sorted(annotations):
        ops = annotations[index]
        page = by_index.get(index)
        if not page or not ops:
            continue
        content, uses_font = build_content(ops)
        if not content:
            continue
        touched = True

        node = document.get(page["objnum"])
        if not isinstance(node, dict):
            continue
        node = dict(node)

        # Wrap whatever the page already draws, so an unbalanced graphics
        # state in the original cannot leak into the annotation.
        opener = allocate(_stream(b"q\n", compress))
        # Leading newline is not cosmetic. Streams in a /Contents array are
        # concatenated, and the spec says the division may fall only at a token
        # boundary - that is the producer's job, not the reader's. The page's
        # existing content commonly ends with "ET" and no trailing whitespace,
        # which would glue onto our "Q" and produce the invalid token "ETQ".
        drawing = allocate(_stream(b"\nQ\n" + content, compress))

        existing = node.get("Contents")
        chain = []
        if isinstance(existing, list):
            chain = list(existing)
        elif existing is not None:
            chain = [existing]
        node["Contents"] = [opener] + chain + [drawing]

        resources = document.resolve(node.get("Resources"))
        if not isinstance(resources, dict):
            inherited = next((document.dget(p_node, "Resources")
                              for p_node in [node] if isinstance(p_node, dict)), None)
            resources = inherited if isinstance(inherited, dict) else {}
        resources = dict(resources)

        if uses_font:
            fonts = document.resolve(resources.get("Font"))
            fonts = dict(fonts) if isinstance(fonts, dict) else {}
            fonts["OmaHelv"] = allocate(dict(HELVETICA))
            resources["Font"] = allocate(fonts)
        if needs_multiply(ops):
            states = document.resolve(resources.get("ExtGState"))
            states = dict(states) if isinstance(states, dict) else {}
            states["OmaMultiply"] = allocate(dict(MULTIPLY))
            resources["ExtGState"] = allocate(states)

        node["Resources"] = allocate(resources)
        new_objects[page["objnum"]] = node

    if not touched:
        return b""

    return _render_update(document, new_objects, next_num)


def _stream(payload, compress):
    if compress:
        return Stream({"Filter": Name("FlateDecode")}, zlib.compress(payload, 9))
    return Stream({}, payload)


def _render_update(document, new_objects, next_num):
    base = len(document.data)
    out = bytearray()
    # A file that does not end in a newline would otherwise glue its last token
    # to our first object header.
    if document.data[-1:] not in (b"\n", b"\r"):
        out += b"\n"

    offsets = {}
    for num in sorted(new_objects):
        offsets[num] = base + len(out)
        out += b"%d 0 obj\n" % num
        out += serialise(new_objects[num])
        out += b"\nendobj\n"

    startxref = base + len(out)
    previous = document.startxref

    listed = dict(offsets)
    if previous is None:
        # The source had no usable cross-reference section, so there is nothing
        # to chain to with /Prev. This section has to describe every object we
        # know about or the reader will not find the originals.
        for num, entry in document.xref.items():
            if num not in listed and entry[0] == "n":
                listed.setdefault(num, entry[1])

    if document.uses_xref_streams:
        out += _xref_stream(new_objects, listed, next_num, previous,
                            document.trailer, startxref)
    else:
        out += _xref_table(new_objects, listed, next_num, previous, document.trailer)

    out += b"startxref\n%d\n%%%%EOF\n" % startxref
    return bytes(out)


def _contiguous(numbers):
    """Group sorted object numbers into runs, which is what a section needs."""
    runs = []
    for num in numbers:
        if runs and num == runs[-1][-1] + 1:
            runs[-1].append(num)
        else:
            runs.append([num])
    return runs


def _xref_table(new_objects, offsets, size, previous, trailer):
    out = bytearray(b"xref\n")
    for run in _contiguous(sorted(offsets)):
        out += b"%d %d\n" % (run[0], len(run))
        for num in run:
            out += b"%010d %05d n \n" % (offsets[num], 0)
    keep = {}
    for key in ("Root", "Info", "ID"):
        if key in trailer:
            keep[key] = trailer[key]
    keep["Size"] = size
    if previous is not None:
        keep["Prev"] = previous
    out += b"trailer\n" + serialise(keep) + b"\n"
    return bytes(out)


def _xref_stream(new_objects, offsets, size, previous, trailer, self_offset):
    # The cross-reference stream describes itself as well, so it gets an object
    # number of its own and appears in its own table.
    own = size
    size += 1
    entries = dict(offsets)
    entries[own] = self_offset

    rows = bytearray()
    index = []
    for run in _contiguous(sorted(entries)):
        index += [run[0], len(run)]
        for num in run:
            rows += b"\x01"
            rows += entries[num].to_bytes(4, "big")
            rows += (0).to_bytes(2, "big")

    payload = zlib.compress(bytes(rows), 9)
    d = {
        "Type": Name("XRef"),
        "Size": size,
        "Index": index,
        "W": [1, 4, 2],
        "Filter": Name("FlateDecode"),
    }
    if previous is not None:
        d["Prev"] = previous
    for key in ("Root", "Info", "ID"):
        if key in trailer:
            d[key] = trailer[key]

    out = bytearray()
    out += b"%d 0 obj\n" % own
    out += serialise(Stream(d, payload))
    out += b"\nendobj\n"
    return bytes(out)


def save_annotated(source_path, target_path, annotations, compress=True):
    """Write `source_path` plus `annotations` to `target_path`."""
    with open(source_path, "rb") as fh:
        original = fh.read()
    document = Document(original)
    update = annotate(document, annotations, compress=compress)
    with open(target_path, "wb") as fh:
        fh.write(original)
        if update:
            fh.write(update)
    return len(update)
