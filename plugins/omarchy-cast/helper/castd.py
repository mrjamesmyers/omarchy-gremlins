#!/usr/bin/env python3
"""
omarchy-cast helper daemon - find the screens in the house and put things on them.

Three device families, discovered together and presented as one list:

  Google Cast   Chromecast, Google TV, Nest Hub, and the "Chromecast built-in"
                badge on most Sony / TCL / Hisense / Philips sets. Spoken
                natively here: mDNS to find them, then CASTV2 over TLS on
                port 8009.
  DLNA          The UPnP MediaRenderer nearly every smart TV still answers to,
                found over SSDP and driven with SOAP.
  AirPlay       Discovered and listed. Apple's modern video path needs a
                key exchange Apple has never published, so these are marked
                as such rather than silently failing.

No third-party libraries. The Cast protocol is protobuf over TLS, so there is
a protobuf encoder in here - all seven fields of it, which is what CastMessage
actually needs and a great deal less than a dependency.

Transport contract with QML: newline-delimited JSON.
stdin  - commands  {"cmd": "...", ...}
stdout - events    {"ev": "...", ...}
"""

import contextlib
import json
import mimetypes
import os
import queue
import random
import re
import select
import socket
import ssl
import struct
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MDNS_GROUP = "224.0.0.251"
MDNS_PORT = 5353
SSDP_GROUP = "239.255.255.250"
SSDP_PORT = 1900

CAST_PORT = 8009
DEFAULT_MEDIA_APP = "CC1AD845"          # Google's Default Media Receiver

NS_CONNECTION = "urn:x-cast:com.google.cast.tp.connection"
NS_HEARTBEAT = "urn:x-cast:com.google.cast.tp.heartbeat"
NS_RECEIVER = "urn:x-cast:com.google.cast.receiver"
NS_MEDIA = "urn:x-cast:com.google.cast.media"

SERVICES = {
    "_googlecast._tcp.local.": "cast",
    "_airplay._tcp.local.": "airplay",
}

TARGET_TTL = 180.0


def log(msg):
    sys.stderr.write("castd: %s\n" % msg)
    sys.stderr.flush()


class Emitter:
    def __init__(self):
        self._lock = threading.Lock()

    def __call__(self, event, **fields):
        fields["ev"] = event
        line = json.dumps(fields, separators=(",", ":"))
        with self._lock:
            try:
                sys.stdout.write(line + "\n")
                sys.stdout.flush()
            except (BrokenPipeError, ValueError):
                os._exit(0)


emit = Emitter()


# --------------------------------------------------------------------------
# just enough protobuf
# --------------------------------------------------------------------------
#
# CastMessage, from Google's cast_channel.proto:
#
#   1 protocol_version  varint
#   2 source_id         string
#   3 destination_id    string
#   4 namespace         string
#   5 payload_type      varint    (0 = STRING, 1 = BINARY)
#   6 payload_utf8      string
#   7 payload_binary    bytes
#
# Every message on the wire is a 4-byte big-endian length followed by that.
# Nothing else in the protocol needs protobuf, so nothing else is implemented.

def _varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _read_varint(buf, pos):
    result = shift = 0
    while True:
        if pos >= len(buf):
            raise ValueError("truncated varint")
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")


def _tag(field, wire):
    return _varint((field << 3) | wire)


def encode_cast_message(source_id, destination_id, namespace, payload):
    body = bytearray()
    body += _tag(1, 0) + _varint(0)                       # protocol_version
    for field, text in ((2, source_id), (3, destination_id), (4, namespace)):
        raw = text.encode("utf-8")
        body += _tag(field, 2) + _varint(len(raw)) + raw
    body += _tag(5, 0) + _varint(0)                       # payload_type STRING
    raw = payload.encode("utf-8")
    body += _tag(6, 2) + _varint(len(raw)) + raw
    return struct.pack(">I", len(body)) + bytes(body)


def decode_cast_message(body):
    fields = {}
    pos = 0
    while pos < len(body):
        tag, pos = _read_varint(body, pos)
        field, wire = tag >> 3, tag & 0x07
        if wire == 0:
            value, pos = _read_varint(body, pos)
            fields[field] = value
        elif wire == 2:
            length, pos = _read_varint(body, pos)
            fields[field] = body[pos:pos + length]
            pos += length
        elif wire == 5:
            pos += 4
        elif wire == 1:
            pos += 8
        else:
            raise ValueError("unsupported wire type %d" % wire)

    def text(index):
        raw = fields.get(index)
        return raw.decode("utf-8", "replace") if isinstance(raw, bytes) else ""

    return {
        "source_id": text(2),
        "destination_id": text(3),
        "namespace": text(4),
        "payload": text(6),
    }


# --------------------------------------------------------------------------
# mDNS / DNS-SD
# --------------------------------------------------------------------------
#
# Hand-rolled rather than shelling out to avahi-browse, because Omarchy does
# not ship Avahi and a plugin that needs `sudo pacman -S` to find your TV is a
# plugin most people never get working. This is a query builder and a parser
# for the five record types DNS-SD actually uses.

TYPE_A, TYPE_PTR, TYPE_TXT, TYPE_SRV = 1, 12, 16, 33


def encode_name(name):
    out = bytearray()
    for label in name.rstrip(".").split("."):
        raw = label.encode("utf-8")
        out.append(len(raw))
        out += raw
    out.append(0)
    return bytes(out)


def decode_name(buf, pos, depth=0):
    """Read a DNS name, following compression pointers.

    Returns (name, position-after-the-name). The depth guard exists because a
    pointer loop in a malformed packet is otherwise an infinite loop inside
    the shell's helper, and packets arrive from anything on the LAN.
    """
    if depth > 16:
        raise ValueError("compression pointer loop")
    labels = []
    jumped_from = None
    while True:
        if pos >= len(buf):
            raise ValueError("truncated name")
        length = buf[pos]
        if length == 0:
            pos += 1
            break
        if length & 0xC0 == 0xC0:
            if pos + 1 >= len(buf):
                raise ValueError("truncated pointer")
            target = ((length & 0x3F) << 8) | buf[pos + 1]
            if jumped_from is None:
                jumped_from = pos + 2
            name, _ = decode_name(buf, target, depth + 1)
            labels.append(name.rstrip("."))
            pos = jumped_from
            return ".".join(l for l in labels if l) + ".", pos
        pos += 1
        labels.append(buf[pos:pos + length].decode("utf-8", "replace"))
        pos += length
    return ".".join(labels) + ".", pos


def build_query(names):
    header = struct.pack(">HHHHHH", 0, 0, len(names), 0, 0, 0)
    body = b"".join(encode_name(n) + struct.pack(">HH", TYPE_PTR, 0x0001)
                    for n in names)
    return header + body


def parse_records(buf):
    """Yield (name, rrtype, rdata-as-python) for every record in a response."""
    if len(buf) < 12:
        return
    _, _, qd, an, ns, ar = struct.unpack(">HHHHHH", buf[:12])
    pos = 12
    for _ in range(qd):
        _, pos = decode_name(buf, pos)
        pos += 4
    for _ in range(an + ns + ar):
        if pos >= len(buf):
            return
        name, pos = decode_name(buf, pos)
        if pos + 10 > len(buf):
            return
        rrtype, _rrclass, _ttl, rdlen = struct.unpack(">HHIH", buf[pos:pos + 10])
        pos += 10
        rdata = buf[pos:pos + rdlen]
        end = pos + rdlen

        try:
            if rrtype == TYPE_PTR:
                value, _ = decode_name(buf, pos)
            elif rrtype == TYPE_SRV:
                if rdlen < 6:
                    pos = end
                    continue
                _prio, _weight, port = struct.unpack(">HHH", rdata[:6])
                target, _ = decode_name(buf, pos + 6)
                value = (target, port)
            elif rrtype == TYPE_TXT:
                pairs = {}
                i = 0
                while i < len(rdata):
                    length = rdata[i]
                    i += 1
                    chunk = rdata[i:i + length].decode("utf-8", "replace")
                    i += length
                    key, _, val = chunk.partition("=")
                    if key:
                        pairs[key] = val
                value = pairs
            elif rrtype == TYPE_A:
                if rdlen != 4:
                    pos = end
                    continue
                value = socket.inet_ntoa(rdata)
            else:
                pos = end
                continue
        except (ValueError, struct.error):
            pos = end
            continue

        yield name, rrtype, value
        pos = end


def local_ipv4s():
    found = []
    for destination in ("8.8.8.8", "1.1.1.1"):
        with contextlib.suppress(OSError):
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            with contextlib.closing(probe):
                probe.connect((destination, 9))
                found.append(probe.getsockname()[0])
                break
    return [ip for ip in found if not ip.startswith("127.")]


def mdns_scan(duration=3.0):
    """One multicast question, then listen. Returns {instance: {...}}."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    with contextlib.suppress(AttributeError, OSError):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    try:
        sock.bind(("", MDNS_PORT))
    except OSError:
        # Something else owns 5353 - almost always a running Avahi. Fall back
        # to an ephemeral port: we lose nothing but unsolicited announcements,
        # and our own questions are still answered.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        with contextlib.suppress(OSError):
            sock.bind(("", 0))

    with contextlib.closing(sock):
        with contextlib.suppress(OSError):
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        group = socket.inet_aton(MDNS_GROUP)
        for ip in local_ipv4s() or ["0.0.0.0"]:
            with contextlib.suppress(OSError):
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                                group + socket.inet_aton(ip))

        query = build_query(list(SERVICES))
        for _ in range(2):                      # one repeat; mDNS is lossy
            with contextlib.suppress(OSError):
                sock.sendto(query, (MDNS_GROUP, MDNS_PORT))
            time.sleep(0.25)

        instances, srv, txt, addr, kinds = {}, {}, {}, {}, {}
        deadline = time.time() + duration
        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            try:
                ready, _, _ = select.select([sock], [], [], remaining)
                if not ready:
                    continue
                raw, _origin = sock.recvfrom(9000)
            except (OSError, ValueError):
                break

            try:
                records = list(parse_records(raw))
            except (ValueError, struct.error):
                continue

            for name, rrtype, value in records:
                if rrtype == TYPE_PTR and name in SERVICES:
                    instances[value] = SERVICES[name]
                    kinds[value] = SERVICES[name]
                elif rrtype == TYPE_SRV:
                    srv[name] = value
                elif rrtype == TYPE_TXT:
                    txt[name] = value
                elif rrtype == TYPE_A:
                    addr[name] = value

        found = {}
        for instance, kind in instances.items():
            host_port = srv.get(instance)
            if not host_port:
                continue
            hostname, port = host_port
            ip = addr.get(hostname)
            if not ip:
                # Some receivers answer SRV but leave the A record to a second
                # question. Resolving the .local name is a reasonable fallback
                # on a box running a resolver that understands mDNS.
                with contextlib.suppress(OSError, socket.gaierror):
                    ip = socket.gethostbyname(hostname.rstrip("."))
            if not ip:
                continue

            info = txt.get(instance, {})
            label = info.get("fn") or instance.split(".")[0].replace("-", " ")
            found[instance] = {
                "id": info.get("id") or instance,
                "name": label,
                "model": info.get("md") or ("AirPlay" if kind == "airplay" else "Cast"),
                "kind": kind,
                "address": ip,
                "port": int(port),
            }
        return found


# --------------------------------------------------------------------------
# SSDP / DLNA
# --------------------------------------------------------------------------

SSDP_SEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    "HOST: %s:%d\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 2\r\n"
    "ST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n"
    "\r\n" % (SSDP_GROUP, SSDP_PORT)
).encode()


def http_get(url, timeout=6):
    from urllib.request import Request, urlopen
    try:
        with urlopen(Request(url, headers={"User-Agent": "omarchy-cast/1.0"}),
                     timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")
    except Exception:                                   # noqa: BLE001
        return None


def absolute_url(base, path):
    from urllib.parse import urljoin
    return urljoin(base, path)


def ssdp_scan(duration=3.0):
    """Find UPnP MediaRenderers and the AVTransport endpoint on each."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(1.0)
    with contextlib.suppress(OSError):
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

    locations = {}
    with contextlib.closing(sock):
        for _ in range(2):
            with contextlib.suppress(OSError):
                sock.sendto(SSDP_SEARCH, (SSDP_GROUP, SSDP_PORT))
            time.sleep(0.2)

        deadline = time.time() + duration
        while time.time() < deadline:
            try:
                raw, origin = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            text = raw.decode("utf-8", "replace")
            match = re.search(r"^LOCATION:\s*(\S+)", text, re.I | re.M)
            if match:
                locations[match.group(1)] = origin[0]

    found = {}
    for location, ip in locations.items():
        xml = http_get(location)
        if not xml:
            continue
        name = re.search(r"<friendlyName>(.*?)</friendlyName>", xml, re.S)
        model = re.search(r"<modelName>(.*?)</modelName>", xml, re.S)
        udn = re.search(r"<UDN>(.*?)</UDN>", xml, re.S)

        # The AVTransport service is what actually plays things. A renderer
        # without one can be listed but cannot be driven, so it is skipped.
        control = None
        for block in re.findall(r"<service>(.*?)</service>", xml, re.S):
            if "AVTransport" in block:
                url = re.search(r"<controlURL>(.*?)</controlURL>", block, re.S)
                if url:
                    control = absolute_url(location, url.group(1).strip())
                break
        if not control:
            continue

        identity = (udn.group(1).strip() if udn else location)
        found[identity] = {
            "id": identity,
            "name": (name.group(1).strip() if name else ip),
            "model": (model.group(1).strip() if model else "DLNA renderer"),
            "kind": "dlna",
            "address": ip,
            "port": 0,
            "control": control,
        }
    return found


def soap(control_url, action, body, timeout=10):
    from urllib.request import Request, urlopen
    service = "urn:schemas-upnp-org:service:AVTransport:1"
    envelope = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        "<s:Body><u:%s xmlns:u=\"%s\">%s</u:%s></s:Body></s:Envelope>"
        % (action, service, body, action)
    ).encode("utf-8")

    request = Request(control_url, data=envelope, headers={
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPAction": '"%s#%s"' % (service, action),
    })
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status in (200, 204)
    except Exception as exc:                            # noqa: BLE001
        log("SOAP %s failed: %s" % (action, exc))
        return False


def xml_escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def dlna_play(target, url, title, mime):
    metadata = xml_escape(
        '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
        '<item id="0" parentID="-1" restricted="1">'
        "<dc:title>%s</dc:title>"
        "<upnp:class>object.item.%s</upnp:class>"
        '<res protocolInfo="http-get:*:%s:*">%s</res>'
        "</item></DIDL-Lite>"
        % (xml_escape(title),
           "videoItem" if mime.startswith("video") else
           ("audioItem.musicTrack" if mime.startswith("audio") else "imageItem"),
           mime, xml_escape(url))
    )
    ok = soap(target["control"], "SetAVTransportURI",
              "<InstanceID>0</InstanceID>"
              "<CurrentURI>%s</CurrentURI>"
              "<CurrentURIMetaData>%s</CurrentURIMetaData>"
              % (xml_escape(url), metadata))
    if not ok:
        return False
    return soap(target["control"], "Play",
                "<InstanceID>0</InstanceID><Speed>1</Speed>")


def dlna_simple(target, action, extra=""):
    return soap(target["control"], action, "<InstanceID>0</InstanceID>" + extra)


# --------------------------------------------------------------------------
# the local media server
# --------------------------------------------------------------------------

class MediaServer:
    """Serves one staged local file to the television.

    A Chromecast will not read your filesystem; it fetches a URL. So a local
    file becomes a URL for as long as it is playing, bound to the LAN address
    the receiver can actually reach, and serving exactly one path - a token
    nobody else on the network is going to guess.

    Range support is not optional: without it the receiver cannot seek, and
    several firmwares refuse to start playback at all.
    """

    def __init__(self):
        self.httpd = None
        self.path = None
        self.token = None
        self.mime = "application/octet-stream"
        self.port = 0
        self.lock = threading.Lock()

    def stage(self, path):
        with self.lock:
            self.path = path
            self.token = uuid.uuid4().hex
            self.mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
            if self.httpd is None:
                self._start()
            return self.token

    def url(self, host_ip):
        if not (self.httpd and self.token):
            return None
        return "http://%s:%d/%s" % (host_ip, self.port, self.token)

    def _start(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _resolve(self):
                with server.lock:
                    token, path, mime = server.token, server.path, server.mime
                if not token or self.path.lstrip("/") != token:
                    return None
                if not path or not os.path.isfile(path):
                    return None
                return path, mime

            def do_HEAD(self):
                self._serve(head_only=True)

            def do_GET(self):
                self._serve(head_only=False)

            def _serve(self, head_only):
                resolved = self._resolve()
                if not resolved:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                path, mime = resolved
                size = os.path.getsize(path)

                start, end = 0, size - 1
                partial = False
                header = self.headers.get("Range")
                if header:
                    match = re.match(r"bytes=(\d*)-(\d*)", header.strip())
                    if match:
                        first, last = match.group(1), match.group(2)
                        if first:
                            start = min(int(first), size - 1)
                            if last:
                                end = min(int(last), size - 1)
                        elif last:
                            start = max(0, size - int(last))
                        partial = True

                if start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", "bytes */%d" % size)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return

                length = end - start + 1
                self.send_response(206 if partial else 200)
                self.send_header("Content-Type", mime)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(length))
                if partial:
                    self.send_header("Content-Range",
                                     "bytes %d-%d/%d" % (start, end, size))
                self.end_headers()
                if head_only:
                    return

                try:
                    with open(path, "rb") as fh:
                        fh.seek(start)
                        remaining = length
                        while remaining > 0:
                            chunk = fh.read(min(256 * 1024, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                except (OSError, BrokenPipeError, ConnectionResetError):
                    # The television stopped reading. Entirely normal on stop
                    # or seek; not worth a line in the log.
                    pass

        self.httpd = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever,
                         kwargs={"poll_interval": 0.5}, daemon=True).start()

    def stop(self):
        with self.lock:
            self.token = None
            self.path = None


# --------------------------------------------------------------------------
# the Cast channel
# --------------------------------------------------------------------------

class CastChannel:
    """One TLS conversation with one Google Cast receiver."""

    def __init__(self, host, port, on_status):
        self.host = host
        self.port = port
        self.on_status = on_status
        self.sock = None
        self.source = "sender-%s" % uuid.uuid4().hex[:8]
        self.request_id = 0
        self.session_id = None
        self.transport_id = None
        self.media_session_id = None
        self.app_ready = threading.Event()
        self.running = False
        self.lock = threading.Lock()
        # Every byte in either direction goes through one thread. An OpenSSL
        # session is a single object with a single state machine, and reading
        # on one thread while writing on another corrupts it - not reliably,
        # which is worse: it works in testing and drops the session an hour
        # into a film. So writes queue here and the I/O loop drains them.
        self.outbox = queue.Queue()

    # -- plumbing ---------------------------------------------------------

    def next_id(self):
        with self.lock:
            self.request_id += 1
            return self.request_id

    def connect(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        # Receivers in the field still present certificates that Python's
        # default security level rejects outright. There is no CA chain to
        # verify here anyway - the trust boundary is the LAN - so insisting on
        # SECLEVEL 2 buys nothing and loses half the devices in the house.
        with contextlib.suppress(ssl.SSLError):
            context.set_ciphers("DEFAULT@SECLEVEL=1")

        raw = socket.create_connection((self.host, self.port), timeout=10)
        self.sock = context.wrap_socket(raw)
        # A short read timeout is what drives the I/O loop. Never None: a
        # blocking recv here wedges the only thread that can also send.
        self.sock.settimeout(0.15)
        self.running = True

        threading.Thread(target=self._io_loop, daemon=True).start()

        self.send(NS_CONNECTION, {"type": "CONNECT"}, "receiver-0")
        self.send(NS_RECEIVER, {"type": "GET_STATUS",
                                "requestId": self.next_id()}, "receiver-0")

    def send(self, namespace, payload, destination):
        if not self.running:
            return False
        self.outbox.put(encode_cast_message(self.source, destination, namespace,
                                            json.dumps(payload)))
        return True

    def _read_exact(self, count, opening=False):
        """Read exactly `count` bytes, or None if `opening` and none arrived.

        The distinction matters. A timeout with nothing read means the wire is
        simply idle and the loop should go back to sending. A timeout partway
        through a frame means the rest is still coming and giving up would
        lose framing for the remainder of the session, so that case waits.
        """
        buf = b""
        deadline = time.monotonic() + 20.0
        while len(buf) < count:
            try:
                chunk = self.sock.recv(count - len(buf))
            except socket.timeout:
                if opening and not buf:
                    return None
                if time.monotonic() > deadline:
                    raise ConnectionError("frame stalled mid-read")
                continue
            if not chunk:
                raise ConnectionError("receiver closed the channel")
            buf += chunk
        return buf

    def _read_frame(self):
        """Read one frame if one is there. Returns False when the wire is idle."""
        header = self._read_exact(4, opening=True)
        if header is None:
            return False
        length = struct.unpack(">I", header)[0]
        if length > 8 * 1024 * 1024:
            raise ValueError("absurd frame length %d" % length)
        self._dispatch(decode_cast_message(self._read_exact(length)))
        return True

    def _io_loop(self):
        # One thread owns the socket. It alternates between draining the
        # outbox and reading whatever has arrived; the read blocks for at most
        # the socket timeout, which is what keeps sends responsive.
        #
        # Deliberately not select(): after a TLS 1.3 handshake the receiver
        # sends session tickets, which make the raw socket readable while
        # yielding no application data. select() says "go read" and the read
        # then blocks forever, taking the sending half of this loop with it.
        next_ping = time.monotonic() + 4.5
        try:
            while self.running:
                while True:
                    try:
                        self.sock.sendall(self.outbox.get_nowait())
                    except queue.Empty:
                        break

                if time.monotonic() >= next_ping:
                    next_ping = time.monotonic() + 4.5
                    self.sock.sendall(encode_cast_message(
                        self.source, "receiver-0", NS_HEARTBEAT,
                        json.dumps({"type": "PING"})))

                # Keep reading while frames are actually there, so a burst
                # does not trickle out one per timeout.
                for _ in range(32):
                    if not self.running or not self._read_frame():
                        break
        except (OSError, ValueError, ConnectionError, AttributeError) as exc:
            if self.running:
                log("channel to %s ended: %s" % (self.host, exc))
        finally:
            self.close()

    def _dispatch(self, message):
        namespace = message["namespace"]
        try:
            payload = json.loads(message["payload"]) if message["payload"] else {}
        except ValueError:
            return
        kind = payload.get("type")

        if namespace == NS_HEARTBEAT and kind == "PING":
            self.send(NS_HEARTBEAT, {"type": "PONG"}, message["source_id"])
            return

        if namespace == NS_RECEIVER and kind == "RECEIVER_STATUS":
            status = payload.get("status") or {}
            apps = status.get("applications") or []
            for app in apps:
                if app.get("transportId"):
                    fresh = app["transportId"] != self.transport_id
                    self.transport_id = app["transportId"]
                    self.session_id = app.get("sessionId")
                    if fresh:
                        # Every app gets its own virtual connection.
                        self.send(NS_CONNECTION, {"type": "CONNECT"}, self.transport_id)
                    self.app_ready.set()
                    break
            else:
                self.transport_id = None
                self.app_ready.clear()

            volume = status.get("volume") or {}
            self.on_status({"kind": "receiver", "volume": volume.get("level"),
                            "muted": volume.get("muted"),
                            "app": apps[0].get("displayName") if apps else None})
            return

        if namespace == NS_MEDIA and kind == "MEDIA_STATUS":
            entries = payload.get("status") or []
            if not entries:
                return
            state = entries[0]
            self.media_session_id = state.get("mediaSessionId", self.media_session_id)
            media = state.get("media") or {}
            self.on_status({
                "kind": "media",
                "state": state.get("playerState"),
                "position": state.get("currentTime"),
                "duration": media.get("duration"),
                "title": ((media.get("metadata") or {}).get("title")),
            })

    # -- the things a user asks for ---------------------------------------

    def launch(self, app_id=DEFAULT_MEDIA_APP, timeout=15):
        self.app_ready.clear()
        self.send(NS_RECEIVER, {"type": "LAUNCH", "appId": app_id,
                                "requestId": self.next_id()}, "receiver-0")
        return self.app_ready.wait(timeout)

    def load(self, url, mime, title, subtitle=None):
        if not self.transport_id:
            return False
        media = {
            "contentId": url,
            "contentType": mime,
            "streamType": "BUFFERED",
            "metadata": {
                "metadataType": 0,
                "title": title,
                "subtitle": subtitle or "",
            },
        }
        return self.send(NS_MEDIA, {
            "type": "LOAD", "media": media, "autoplay": True,
            "currentTime": 0, "requestId": self.next_id(),
            "sessionId": self.session_id,
        }, self.transport_id)

    def media_command(self, kind, **extra):
        if not (self.transport_id and self.media_session_id):
            return False
        payload = {"type": kind, "mediaSessionId": self.media_session_id,
                   "requestId": self.next_id()}
        payload.update(extra)
        return self.send(NS_MEDIA, payload, self.transport_id)

    def set_volume(self, level):
        return self.send(NS_RECEIVER, {
            "type": "SET_VOLUME",
            "volume": {"level": max(0.0, min(1.0, float(level)))},
            "requestId": self.next_id(),
        }, "receiver-0")

    def quit_app(self):
        if self.session_id:
            self.send(NS_RECEIVER, {"type": "STOP", "sessionId": self.session_id,
                                    "requestId": self.next_id()}, "receiver-0")

    def close(self):
        if not self.running:
            return
        self.running = False
        with contextlib.suppress(OSError):
            if self.sock:
                self.sock.close()
        self.sock = None
        self.app_ready.clear()


# --------------------------------------------------------------------------
# the daemon
# --------------------------------------------------------------------------

def source_address_for(host):
    """Which of our addresses this receiver will be able to reach us on.

    A laptop on wifi with a docked ethernet port has two, and handing the
    television the wrong one produces a spinner and no error. Asking the
    routing table which source it would use for that specific destination is
    the only answer that is right on every topology.
    """
    with contextlib.suppress(OSError):
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        with contextlib.closing(probe):
            probe.connect((host, 9))
            return probe.getsockname()[0]
    addresses = local_ipv4s()
    return addresses[0] if addresses else "127.0.0.1"


class Cast:
    def __init__(self):
        self.targets = {}
        self.lock = threading.Lock()
        self.channel = None
        self.current = None
        self.media = MediaServer()
        self.running = True
        self.scanning = False

    # -- discovery ---------------------------------------------------------

    def scan(self, duration=3.0):
        if self.scanning:
            return
        self.scanning = True
        emit("scanning", active=True)

        found = {}
        results = {}

        def run(name, fn):
            try:
                results[name] = fn(duration)
            except Exception as exc:                    # noqa: BLE001
                log("%s scan failed: %s" % (name, exc))
                results[name] = {}

        threads = [threading.Thread(target=run, args=("mdns", mdns_scan), daemon=True),
                   threading.Thread(target=run, args=("ssdp", ssdp_scan), daemon=True)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=duration + 6)

        for bundle in results.values():
            found.update(bundle)

        now = time.monotonic()
        with self.lock:
            for key, target in found.items():
                target["seen"] = now
                self.targets[key] = target
            stale = [k for k, t in self.targets.items()
                     if now - t.get("seen", now) > TARGET_TTL]
            for key in stale:
                del self.targets[key]
            listing = [self._public(t) for t in self.targets.values()]

        listing.sort(key=lambda t: (t["kind"] != "cast", t["name"].lower()))
        self.scanning = False
        emit("scanning", active=False)
        emit("targets", targets=listing)

    @staticmethod
    def _public(target):
        return {k: target[k] for k in ("id", "name", "model", "kind", "address")}

    def find(self, target_id):
        with self.lock:
            return self.targets.get(target_id)

    # -- playing -----------------------------------------------------------

    def cast(self, target_id, source, title=None):
        target = self.find(target_id)
        if not target:
            emit("error", message="That device is no longer on the network.")
            return

        # Tear the previous session down BEFORE staging the new media. stop()
        # revokes the media server's token, and revoking it after the URL is
        # built hands the television a link to a file the server will no
        # longer serve - a spinner on the TV and no error anywhere.
        self.stop(quiet=True)

        is_url = bool(re.match(r"^https?://", source or ""))
        path = None
        if not is_url:
            path = os.path.expanduser(source or "")
            if path.startswith("file://"):
                from urllib.parse import unquote, urlparse
                path = unquote(urlparse(path).path)
            if not os.path.isfile(path):
                emit("error", message="%s is not a file." % os.path.basename(path or ""))
                return

        if is_url:
            url = source
            mime = "video/mp4"
            label = title or url
        else:
            token = self.media.stage(path)
            our_ip = source_address_for(target["address"])
            url = "http://%s:%d/%s" % (our_ip, self.media.port, token)
            mime = self.media.mime
            label = title or os.path.basename(path)

        if target["kind"] == "cast":
            self._cast_google(target, url, mime, label)
        elif target["kind"] == "dlna":
            self._cast_dlna(target, url, mime, label)
        else:
            emit("error", message=(
                "%s is an AirPlay receiver. Apple has never published the "
                "handshake its video path needs, so Omarchy can see it but "
                "cannot drive it." % target["name"]))

    def _cast_google(self, target, url, mime, label):
        try:
            channel = CastChannel(target["address"], target["port"] or CAST_PORT,
                                  self._on_status)
            channel.connect()
        except (OSError, ssl.SSLError) as exc:
            emit("error", message="Could not reach %s: %s" % (target["name"], exc))
            return

        if not channel.launch():
            channel.close()
            emit("error", message="%s did not start its media receiver." % target["name"])
            return

        if not channel.load(url, mime, label):
            channel.close()
            emit("error", message="%s refused the media." % target["name"])
            return

        self.channel = channel
        self.current = {"target": self._public(target), "title": label, "url": url}
        emit("casting", target=self.current["target"], title=label)

    def _cast_dlna(self, target, url, mime, label):
        if not dlna_play(target, url, label, mime):
            emit("error", message="%s refused the media." % target["name"])
            return
        self.current = {"target": self._public(target), "title": label, "url": url}
        emit("casting", target=self.current["target"], title=label)
        # DLNA renderers do not push status, so report the one thing we know.
        emit("status", state="PLAYING", title=label)

    def _on_status(self, status):
        if status.get("kind") == "media":
            emit("status", state=status.get("state"), position=status.get("position"),
                 duration=status.get("duration"), title=status.get("title"))
        else:
            emit("receiver", volume=status.get("volume"), muted=status.get("muted"),
                 app=status.get("app"))

    # -- transport ---------------------------------------------------------

    def control(self, action, value=None):
        if not self.current:
            return
        kind = self.current["target"]["kind"]

        if kind == "cast":
            if not self.channel:
                return
            if action == "pause":
                self.channel.media_command("PAUSE")
            elif action == "play":
                self.channel.media_command("PLAY")
            elif action == "seek":
                self.channel.media_command("SEEK", currentTime=float(value or 0))
            elif action == "volume":
                self.channel.set_volume(value)
        elif kind == "dlna":
            if action == "pause":
                dlna_simple(self.current_target_object(), "Pause")
            elif action == "play":
                dlna_simple(self.current_target_object(), "Play", "<Speed>1</Speed>")
            elif action == "seek":
                seconds = int(float(value or 0))
                stamp = "%d:%02d:%02d" % (seconds // 3600, (seconds // 60) % 60, seconds % 60)
                dlna_simple(self.current_target_object(), "Seek",
                            "<Unit>REL_TIME</Unit><Target>%s</Target>" % stamp)

    def current_target_object(self):
        return self.find(self.current["target"]["id"]) if self.current else None

    def stop(self, quiet=False):
        if self.channel:
            self.channel.quit_app()
            self.channel.close()
            self.channel = None
        if self.current and self.current["target"]["kind"] == "dlna":
            target = self.current_target_object()
            if target:
                dlna_simple(target, "Stop")
        self.media.stop()
        self.current = None
        if not quiet:
            emit("stopped")


def handle_command(cast, msg):
    cmd = msg.get("cmd")
    if cmd == "scan":
        threading.Thread(target=cast.scan, daemon=True).start()
    elif cmd == "cast":
        threading.Thread(target=cast.cast,
                         args=(msg.get("target"), msg.get("source"), msg.get("title")),
                         daemon=True).start()
    elif cmd in ("pause", "play", "seek", "volume"):
        cast.control(cmd, msg.get("value"))
    elif cmd == "stop":
        cast.stop()
    elif cmd == "quit":
        cast.stop(quiet=True)
        cast.running = False


def main():
    cast = Cast()
    emit("ready", addresses=local_ipv4s())
    threading.Thread(target=cast.scan, daemon=True).start()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if not isinstance(msg, dict):
            continue
        try:
            handle_command(cast, msg)
        except Exception as exc:                        # noqa: BLE001
            log("command %r failed: %s" % (msg.get("cmd"), exc))
            emit("error", message=str(exc))
        if not cast.running:
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
