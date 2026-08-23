#!/usr/bin/env python3
"""
Tests for pdfcore.

Fixtures are built here rather than checked in, so both cross-reference
flavours are covered: the classic table that PDF 1.4 files use, and the
cross-reference stream with object streams that everything since 1.5 uses.
A parser that only handles the first works on almost nothing modern.

The load-bearing assertion is that the original file survives byte for byte
inside the annotated one. Everything else is recoverable; corrupting somebody's
signed contract is not.

    python3 test_pdfcore.py
"""

import importlib.util
import os
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("pdfcore", os.path.join(HERE, "pdfcore.py"))
pdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf)

PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print("  %s %s%s" % ("PASS" if condition else "FAIL", name,
                         "" if condition else "   <- %s" % detail))


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

def classic_pdf(pages=2, rotate=0, trailing_newline=True, wrong_length=False):
    """A PDF 1.4 with a classic xref table and an inherited MediaBox."""
    objects = {}
    kids = []
    first_page = 3
    for i in range(pages):
        page_num = first_page + i * 2
        content_num = page_num + 1
        kids.append(b"%d 0 R" % page_num)
        body = b"BT /F1 12 Tf 72 700 Td (page %d) Tj ET" % (i + 1)
        rot = b" /Rotate %d" % rotate if rotate else b""
        objects[page_num] = (b"<</Type/Page /Parent 2 0 R /Contents %d 0 R"
                             b" /Resources<</Font<</F1 99 0 R>>>>%s>>" % (content_num, rot))
        declared = len(body) + (7 if wrong_length else 0)
        objects[content_num] = (b"<</Length %d>>\nstream\n" % declared) + body + b"\nendstream"

    objects[1] = b"<</Type/Catalog /Pages 2 0 R>>"
    objects[2] = (b"<</Type/Pages /Kids[" + b" ".join(kids) +
                  b"] /Count %d /MediaBox[0 0 612 792]>>" % pages)
    objects[99] = b"<</Type/Font /Subtype/Type1 /BaseFont/Helvetica>>"

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for num in sorted(objects):
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + objects[num] + b"\nendobj\n"

    startxref = len(out)
    top = max(objects) + 1
    out += b"xref\n0 %d\n" % top
    out += b"0000000000 65535 f \n"
    for num in range(1, top):
        if num in offsets:
            out += b"%010d 00000 n \n" % offsets[num]
        else:
            out += b"0000000000 65535 f \n"
    out += b"trailer\n<</Size %d /Root 1 0 R>>\n" % top
    out += b"startxref\n%d\n%%%%EOF" % startxref
    if trailing_newline:
        out += b"\n"
    return bytes(out)


def xrefstream_pdf():
    """A PDF 1.5: catalog and page tree inside an object stream, xref stream."""
    # Objects 1 (catalog) and 2 (pages) live compressed inside object stream 6.
    inner = {
        1: b"<</Type/Catalog /Pages 2 0 R>>",
        2: b"<</Type/Pages /Kids[3 0 R] /Count 1 /MediaBox[0 0 400 500]>>",
    }
    body = bytearray()
    header = bytearray()
    for num in sorted(inner):
        header += b"%d %d " % (num, len(body))
        body += inner[num] + b" "
    payload = bytes(header) + bytes(body)
    first = len(header)
    objstm_raw = zlib.compress(payload, 9)

    content = b"BT /F1 12 Tf 40 400 Td (compressed) Tj ET"

    out = bytearray(b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}

    def emit(num, blob):
        offsets[num] = len(out)
        out.extend(b"%d 0 obj\n" % num + blob + b"\nendobj\n")

    emit(3, b"<</Type/Page /Parent 2 0 R /Contents 4 0 R /Resources<<>>>>")
    emit(4, b"<</Length %d>>\nstream\n" % len(content) + content + b"\nendstream")
    emit(6, (b"<</Type/ObjStm /N %d /First %d /Length %d /Filter/FlateDecode>>\nstream\n"
             % (len(inner), first, len(objstm_raw))) + objstm_raw + b"\nendstream")

    # Now the cross-reference stream, describing objects 0..7 including itself.
    xref_num = 7
    xref_offset = len(out)
    rows = bytearray()
    rows += b"\x00" + (0).to_bytes(4, "big") + (65535).to_bytes(2, "big")   # free
    rows += b"\x02" + (6).to_bytes(4, "big") + (0).to_bytes(2, "big")       # 1 in objstm
    rows += b"\x02" + (6).to_bytes(4, "big") + (1).to_bytes(2, "big")       # 2 in objstm
    for num in (3, 4):
        rows += b"\x01" + offsets[num].to_bytes(4, "big") + (0).to_bytes(2, "big")
    rows += b"\x00" + (0).to_bytes(4, "big") + (0).to_bytes(2, "big")       # 5 unused
    rows += b"\x01" + offsets[6].to_bytes(4, "big") + (0).to_bytes(2, "big")
    rows += b"\x01" + xref_offset.to_bytes(4, "big") + (0).to_bytes(2, "big")
    packed = zlib.compress(bytes(rows), 9)

    out += b"%d 0 obj\n" % xref_num
    out += (b"<</Type/XRef /Size %d /W[1 4 2] /Root 1 0 R /Filter/FlateDecode"
            b" /Length %d>>\nstream\n" % (xref_num + 1, len(packed)))
    out += packed + b"\nendstream\nendobj\n"
    out += b"startxref\n%d\n%%%%EOF\n" % xref_offset
    return bytes(out)


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

def test_parse_classic():
    d = pdf.Document(classic_pdf(pages=2))
    pages = d.pages()
    check("classic: both pages found", len(pages) == 2, len(pages))
    check("classic: MediaBox inherited from the Pages node",
          pages[0]["width"] == 612.0 and pages[0]["height"] == 792.0, pages[0])
    check("classic: page object numbers resolved", [p["objnum"] for p in pages] == [3, 5],
          [p["objnum"] for p in pages])
    check("classic: not flagged as using xref streams", d.uses_xref_streams is False)


def test_parse_xref_stream():
    d = pdf.Document(xrefstream_pdf())
    pages = d.pages()
    check("xrefstream: page found", len(pages) == 1, len(pages))
    # The catalog and page tree are inside a compressed object stream, so this
    # only works if object streams are being decompressed and indexed.
    check("xrefstream: MediaBox read out of a compressed object stream",
          pages[0]["width"] == 400.0 and pages[0]["height"] == 500.0, pages[0])
    check("xrefstream: flavour detected", d.uses_xref_streams is True)
    catalog = d.resolve(d.trailer.get("Root"))
    check("xrefstream: catalog resolves from inside the object stream",
          isinstance(catalog, dict) and catalog.get("Type") == "Catalog", catalog)


def test_rotation_and_boxes():
    d = pdf.Document(classic_pdf(pages=1, rotate=90))
    check("rotate: /Rotate carried through", d.pages()[0]["rotate"] == 90, d.pages()[0])
    d = pdf.Document(classic_pdf(pages=1, rotate=450))
    check("rotate: normalised into 0-359", d.pages()[0]["rotate"] == 90, d.pages()[0])


def test_wrong_length_recovered():
    """A wrong /Length is common in the wild and must not lose the stream."""
    d = pdf.Document(classic_pdf(pages=1, wrong_length=True))
    page = d.get(3)
    content = d.resolve(page["Contents"])
    check("recovery: stream with a wrong /Length still parses",
          isinstance(content, pdf.Stream), type(content))
    if isinstance(content, pdf.Stream):
        check("recovery: and its bytes end where endstream does",
              content.data().endswith(b"Tj ET"), content.data()[-24:])


def test_damaged_xref_rebuild():
    data = bytearray(classic_pdf(pages=1))
    at = data.rfind(b"startxref")
    data[at:at + 9] = b"startxrEf"          # corrupt the pointer's keyword
    d = pdf.Document(bytes(data))
    check("damaged: rebuilt by scanning for objects", len(d.pages()) == 1, len(d.pages()))
    check("damaged: catalog still located",
          isinstance(d.resolve(d.trailer.get("Root")), dict), d.trailer)


def test_object_and_string_syntax():
    p = pdf.Parser(b"<</A 1 0 R /B (a\\)b) /C <414243> /D [1 2.5 /N] /E#20F true>>")
    obj = p.parse()
    check("syntax: indirect reference", obj["A"] == pdf.Ref(1, 0), obj.get("A"))
    check("syntax: escaped bracket in a literal string", obj["B"] == b"a)b", obj.get("B"))
    check("syntax: hex string", obj["C"] == b"ABC", obj.get("C"))
    check("syntax: mixed array", obj["D"] == [1, 2.5, "N"], obj.get("D"))
    check("syntax: #20 escape in a name key", obj.get("E F") is True, list(obj))

    # "1 0 R" is a reference but "1 0" followed by anything else is two numbers.
    arr = pdf.Parser(b"[1 0 R 2 0 obj]").parse()
    check("syntax: only a real R makes a reference",
          arr[0] == pdf.Ref(1, 0) and arr[1] == 2, arr)


# --------------------------------------------------------------------------
# annotation
# --------------------------------------------------------------------------

INK = {"type": "ink", "points": [[100, 100], [150, 140], [200, 100]],
       "width": 2.5, "colour": [0, 0, 0.8]}
TEXT = {"type": "text", "text": "James Myers", "x": 90, "y": 200,
        "size": 14, "colour": [0, 0, 0]}


def annotate_bytes(original, annotations):
    d = pdf.Document(original)
    return original + pdf.annotate(d, annotations)


def test_original_is_preserved():
    """The whole safety argument: the source file survives byte for byte."""
    for label, original in (("classic", classic_pdf(pages=2)),
                            ("xrefstream", xrefstream_pdf())):
        out = annotate_bytes(original, {0: [INK, TEXT]})
        check("%s: output starts with the original, unchanged" % label,
              out.startswith(original), "len %d vs %d" % (len(out), len(original)))
        check("%s: something was actually appended" % label, len(out) > len(original))
        check("%s: original startxref still present" % label,
              out.count(b"startxref") >= 2, out.count(b"startxref"))


def test_annotated_reparses():
    for label, original in (("classic", classic_pdf(pages=2)),
                            ("xrefstream", xrefstream_pdf())):
        out = annotate_bytes(original, {0: [INK, TEXT]})
        d = pdf.Document(out)
        pages = d.pages()
        check("%s: annotated file still parses" % label, len(pages) >= 1, len(pages))
        if not pages:
            continue
        page = d.get(pages[0]["objnum"])
        contents = page.get("Contents")
        check("%s: contents became a chain" % label,
              isinstance(contents, list) and len(contents) >= 3, contents)

        drawn = b""
        for ref in contents or []:
            stream = d.resolve(ref)
            if isinstance(stream, pdf.Stream):
                drawn += stream.data()
        check("%s: the ink path is in the content" % label,
              b"100 100 m" in drawn and b"150 140 l" in drawn and b"\nS\n" in drawn,
              drawn[:120])
        # Streams are concatenated by the reader, so the producer must not let
        # the last token of one run into the first token of the next.
        check("%s: no tokens glued across the stream join" % label,
              b"ETQ" not in drawn and b"ETq" not in drawn, drawn[:160])
        check("%s: the text is in the content" % label,
              b"(James Myers) Tj" in drawn, drawn[-140:])
        check("%s: the original page content survives in the chain" % label,
              b"Tj ET" in drawn, drawn[:80])


def test_font_resource_added():
    original = classic_pdf(pages=1)
    out = annotate_bytes(original, {0: [TEXT]})
    d = pdf.Document(out)
    page = d.get(d.pages()[0]["objnum"])
    resources = d.resolve(page.get("Resources"))
    fonts = d.resolve(resources.get("Font")) if isinstance(resources, dict) else None
    check("font: a Font resource exists", isinstance(fonts, dict), fonts)
    if isinstance(fonts, dict):
        check("font: our font was added", "OmaHelv" in fonts, list(fonts))
        check("font: the page's original font was kept", "F1" in fonts, list(fonts))
        helv = d.resolve(fonts.get("OmaHelv"))
        check("font: it is a standard-14 Type1, needing no embedding",
              isinstance(helv, dict) and helv.get("BaseFont") == "Helvetica", helv)


def test_ink_only_adds_no_font():
    out = annotate_bytes(classic_pdf(pages=1), {0: [INK]})
    d = pdf.Document(out)
    page = d.get(d.pages()[0]["objnum"])
    fonts = d.resolve(d.resolve(page.get("Resources")).get("Font"))
    check("font: ink alone does not add our font",
          isinstance(fonts, dict) and "OmaHelv" not in fonts, list(fonts or {}))


def test_highlight_adds_blend_state():
    op = {"type": "highlight", "x": 50, "y": 50, "width": 200, "height": 20,
          "colour": [1, 1, 0]}
    out = annotate_bytes(classic_pdf(pages=1), {0: [op]})
    d = pdf.Document(out)
    page = d.get(d.pages()[0]["objnum"])
    states = d.resolve(d.resolve(page.get("Resources")).get("ExtGState"))
    check("highlight: a Multiply blend state was added",
          isinstance(states, dict) and "OmaMultiply" in states, states)
    if isinstance(states, dict):
        gs = d.resolve(states.get("OmaMultiply"))
        check("highlight: the blend mode is Multiply, so text stays readable",
              isinstance(gs, dict) and gs.get("BM") == "Multiply", gs)


def test_second_page_only():
    out = annotate_bytes(classic_pdf(pages=2), {1: [INK]})
    d = pdf.Document(out)
    pages = d.pages()
    first = d.get(pages[0]["objnum"])
    second = d.get(pages[1]["objnum"])
    check("pages: the untouched page keeps a single content stream",
          not isinstance(first.get("Contents"), list), first.get("Contents"))
    check("pages: the annotated page has a chain",
          isinstance(second.get("Contents"), list), second.get("Contents"))


def test_repeated_annotation():
    """Signing, then annotating again, must keep stacking - not overwrite."""
    original = classic_pdf(pages=1)
    once = annotate_bytes(original, {0: [INK]})
    twice = once + pdf.annotate(pdf.Document(once), {0: [TEXT]})
    d = pdf.Document(twice)
    page = d.get(d.pages()[0]["objnum"])
    drawn = b"".join(s.data() for s in
                     (d.resolve(r) for r in page.get("Contents", []))
                     if isinstance(s, pdf.Stream))
    check("repeat: both rounds survive", b"100 100 m" in drawn and b"(James Myers) Tj" in drawn,
          drawn[:60])
    check("repeat: three startxref sections", twice.count(b"startxref") == 3,
          twice.count(b"startxref"))


def test_xref_flavour_matches():
    out = annotate_bytes(xrefstream_pdf(), {0: [INK]})
    tail = out[len(xrefstream_pdf()):]
    check("xref: an updated stream file gets an XRef stream, not a table",
          b"/Type /XRef" in tail or b"/Type/XRef" in tail, tail[:100])
    out = annotate_bytes(classic_pdf(pages=1), {0: [INK]})
    tail = out[len(classic_pdf(pages=1)):]
    check("xref: an updated table file gets a table",
          tail.lstrip().startswith(b"\n") or b"\nxref\n" in tail, tail[:60])


def test_no_trailing_newline():
    original = classic_pdf(pages=1, trailing_newline=False)
    out = annotate_bytes(original, {0: [INK]})
    check("newline: a file not ending in a newline is separated properly",
          out.startswith(original) and out[len(original):len(original) + 1] == b"\n",
          out[len(original) - 6:len(original) + 8])
    check("newline: and the result still parses", len(pdf.Document(out).pages()) == 1)


def test_empty_annotation_is_a_no_op():
    original = classic_pdf(pages=1)
    check("empty: no ops means no bytes", pdf.annotate(pdf.Document(original), {}) == b"")
    check("empty: an empty list means no bytes",
          pdf.annotate(pdf.Document(original), {0: []}) == b"")


def test_save_annotated_on_disk():
    workdir = tempfile.mkdtemp(prefix="ink-")
    source = os.path.join(workdir, "in.pdf")
    target = os.path.join(workdir, "out.pdf")
    with open(source, "wb") as fh:
        fh.write(classic_pdf(pages=1))
    written = pdf.save_annotated(source, target, {0: [INK, TEXT]})
    check("disk: bytes were appended", written > 0, written)
    with open(source, "rb") as fh:
        before = fh.read()
    with open(target, "rb") as fh:
        after = fh.read()
    check("disk: the source file is untouched", before == classic_pdf(pages=1))
    check("disk: the target contains the source", after.startswith(before))
    check("disk: the target parses", len(pdf.Document(after).pages()) == 1)


def test_content_escaping():
    op = {"type": "text", "text": "a(b)c\\d", "x": 10, "y": 10}
    content, uses_font = pdf.build_content([op])
    check("escape: brackets and backslash escaped in the string",
          rb"(a\(b\)c\\d) Tj" in content, content)
    check("escape: text sets the font flag", uses_font is True)
    content, uses_font = pdf.build_content([INK])
    check("escape: ink does not set the font flag", uses_font is False)

    multi = {"type": "text", "text": "one\ntwo", "x": 0, "y": 0, "size": 10}
    content, _ = pdf.build_content([multi])
    check("escape: a newline becomes a second line, not a literal",
          b"(one) Tj" in content and b"(two) Tj" in content and b"Td" in content, content)


def main():
    print("-- parsing --")
    test_parse_classic(); test_parse_xref_stream(); test_rotation_and_boxes()
    print("\n-- damaged input --")
    test_wrong_length_recovered(); test_damaged_xref_rebuild()
    print("\n-- syntax --")
    test_object_and_string_syntax()
    print("\n-- byte preservation --")
    test_original_is_preserved()
    print("\n-- round trip --")
    test_annotated_reparses()
    print("\n-- resources --")
    test_font_resource_added(); test_ink_only_adds_no_font(); test_highlight_adds_blend_state()
    print("\n-- pages --")
    test_second_page_only(); test_repeated_annotation()
    print("\n-- update mechanics --")
    test_xref_flavour_matches(); test_no_trailing_newline(); test_empty_annotation_is_a_no_op()
    print("\n-- disk --")
    test_save_annotated_on_disk()
    print("\n-- content --")
    test_content_escaping()

    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    for name in FAILED:
        print("   failed: %s" % name)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
