#!/usr/bin/env python3
"""
omarchy-paper helper daemon - find the printers, say what they are doing.

There is not one printer plugin among the 1,099 in the Omarchy registry, which
is strange, because "it found my printer" is a moment that sells an operating
system and its absence is a common reason a new Linux user goes back.

Two sources, merged into one list:

  DNS-SD    Printers advertising _ipp._tcp / _ipps._tcp on the network. These
            are queried directly over IPP for their real state - idle, printing,
            stopped, out of paper, ink levels - whether or not CUPS knows them.
  CUPS      Queues already configured locally, via lpstat. These are the ones
            that can actually be printed to right now.

What it will not do is add a queue. lpadmin needs privileges this plugin does
not have and should not want; a desktop widget that asks for a root password is
a desktop widget people are right to distrust. Instead, a discovered printer
that CUPS does not know is shown as "not set up" together with the exact
command to set it up, which the user runs themselves.

Transport contract with QML: newline-delimited JSON.
"""

import contextlib
import json
import os
import re
import select
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

MDNS_GROUP = "224.0.0.251"
MDNS_PORT = 5353
IPP_SERVICES = {"_ipp._tcp.local.": "ipp", "_ipps._tcp.local.": "ipps"}

DEFAULT_POLL = 20.0
DISCOVERY_INTERVAL = 300.0


def log(msg):
    sys.stderr.write("paperd: %s\n" % msg)
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
# IPP
# --------------------------------------------------------------------------
#
# IPP is a binary encoding carried over HTTP POST with content-type
# application/ipp. The whole request this needs is:
#
#   version(2) operation-id(2) request-id(4)
#   0x01 operation-attributes-tag
#     attributes-charset, attributes-natural-language, printer-uri,
#     requested-attributes...
#   0x03 end-of-attributes-tag
#
# Implemented here rather than shelling out to ipptool because ipptool lives in
# cups-devel, which is not installed on a normal desktop, and a plugin that
# needs a package manager to see your printer is a plugin most people never get
# working.

OP_GET_PRINTER_ATTRIBUTES = 0x000B

TAG_OPERATION = 0x01
TAG_PRINTER = 0x04
TAG_END = 0x03

TAG_INTEGER = 0x21
TAG_BOOLEAN = 0x22
TAG_ENUM = 0x23
TAG_TEXT = 0x41
TAG_NAME = 0x42
TAG_KEYWORD = 0x44
TAG_URI = 0x45
TAG_CHARSET = 0x47
TAG_LANGUAGE = 0x48
TAG_MIME = 0x49

# printer-state is an enum with exactly three values, per RFC 8011.
PRINTER_STATE = {3: "idle", 4: "printing", 5: "stopped"}

WANTED = [
    "printer-name", "printer-make-and-model", "printer-state",
    "printer-state-reasons", "printer-state-message", "printer-info",
    "printer-location", "printer-is-accepting-jobs", "queued-job-count",
    "marker-names", "marker-levels", "marker-colors", "media-default",
    "document-format-supported", "color-supported", "sides-supported",
]


def _attr(tag, name, value):
    name = name.encode("utf-8")
    value = value.encode("utf-8") if isinstance(value, str) else value
    return struct.pack(">BH", tag, len(name)) + name + struct.pack(">H", len(value)) + value


def build_get_printer_attributes(printer_uri, request_id=1):
    out = bytearray()
    out += struct.pack(">HHI", 0x0200, OP_GET_PRINTER_ATTRIBUTES, request_id)
    out.append(TAG_OPERATION)
    out += _attr(TAG_CHARSET, "attributes-charset", "utf-8")
    out += _attr(TAG_LANGUAGE, "attributes-natural-language", "en")
    out += _attr(TAG_URI, "printer-uri", printer_uri)
    # The first requested-attributes carries the name; every value after it is
    # an "additional value", encoded with a zero-length name.
    for index, attribute in enumerate(WANTED):
        out += _attr(TAG_KEYWORD, "requested-attributes" if index == 0 else "", attribute)
    out.append(TAG_END)
    return bytes(out)


def parse_ipp(body):
    """Return {attribute-name: value-or-list} from an IPP response."""
    if len(body) < 8:
        raise ValueError("short IPP response")
    _version, status, _request_id = struct.unpack(">HHI", body[:8])
    pos = 8
    attributes = {}
    current = None

    while pos < len(body):
        tag = body[pos]
        pos += 1
        if tag == TAG_END:
            break
        if tag < 0x10:                      # a delimiter starting a new group
            current = None
            continue
        if pos + 2 > len(body):
            break
        name_len = struct.unpack(">H", body[pos:pos + 2])[0]
        pos += 2
        name = body[pos:pos + name_len].decode("utf-8", "replace")
        pos += name_len
        if pos + 2 > len(body):
            break
        value_len = struct.unpack(">H", body[pos:pos + 2])[0]
        pos += 2
        raw = body[pos:pos + value_len]
        pos += value_len

        if tag in (TAG_INTEGER, TAG_ENUM):
            value = struct.unpack(">i", raw)[0] if len(raw) == 4 else 0
        elif tag == TAG_BOOLEAN:
            # RFC 8011 says one byte. Some firmware sends four. Reading only
            # raw[0] turns a four-byte true into false, so read the whole value.
            value = bool(int.from_bytes(raw, "big")) if raw else False
        else:
            value = raw.decode("utf-8", "replace")

        if name_len == 0 and current:
            # An additional value for the attribute named just before it.
            existing = attributes[current]
            attributes[current] = existing + [value] if isinstance(existing, list) \
                else [existing, value]
        else:
            current = name
            attributes[name] = value

    attributes["_status"] = status
    return attributes


def ipp_request(host, port, path, secure, payload, timeout=6):
    import http.client
    import ssl
    if secure:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=context)
    else:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
    with contextlib.closing(conn):
        conn.request("POST", path, body=payload, headers={
            "Content-Type": "application/ipp",
            "Content-Length": str(len(payload)),
        })
        response = conn.getresponse()
        data = response.read()
        if response.status != 200:
            raise OSError("printer returned HTTP %d" % response.status)
        return parse_ipp(data)


def query_printer(host, port, rp, secure):
    scheme = "ipps" if secure else "ipp"
    path = "/" + (rp or "ipp/print").lstrip("/")
    uri = "%s://%s:%d%s" % (scheme, host, port, path)
    attributes = ipp_request(host, port, path, secure,
                             build_get_printer_attributes(uri))

    def one(key, default=""):
        value = attributes.get(key, default)
        return value[0] if isinstance(value, list) and value else value

    reasons = attributes.get("printer-state-reasons", [])
    if isinstance(reasons, str):
        reasons = [reasons]
    reasons = [r for r in reasons if r and r != "none"]

    markers = []
    names = attributes.get("marker-names", [])
    levels = attributes.get("marker-levels", [])
    colors = attributes.get("marker-colors", [])
    if isinstance(names, str):
        names, levels, colors = [names], [levels], [colors]
    for i, name in enumerate(names or []):
        level = levels[i] if isinstance(levels, list) and i < len(levels) else levels
        color = colors[i] if isinstance(colors, list) and i < len(colors) else colors
        with contextlib.suppress(TypeError, ValueError):
            markers.append({"name": name, "level": int(level),
                            "color": color if isinstance(color, str) else ""})

    return {
        "uri": uri,
        "state": PRINTER_STATE.get(one("printer-state", 0), "unknown"),
        "stateMessage": one("printer-state-message", ""),
        "reasons": reasons,
        "makeAndModel": one("printer-make-and-model", ""),
        "location": one("printer-location", ""),
        "acceptingJobs": bool(attributes.get("printer-is-accepting-jobs", True)),
        "queued": attributes.get("queued-job-count", 0) or 0,
        "markers": markers,
        "color": bool(attributes.get("color-supported", False)),
    }


# --------------------------------------------------------------------------
# DNS-SD
# --------------------------------------------------------------------------
#
# The same hand-rolled resolver the Cast plugin uses, pointed at _ipp._tcp
# instead. Omarchy ships no Avahi, so asking the network directly is the only
# way to find a printer without making the user install one.

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
    if depth > 16:
        raise ValueError("compression pointer loop")
    labels = []
    resume = None
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
            if resume is None:
                resume = pos + 2
            name, _ = decode_name(buf, target, depth + 1)
            labels.append(name.rstrip("."))
            return ".".join(l for l in labels if l) + ".", resume
        pos += 1
        labels.append(buf[pos:pos + length].decode("utf-8", "replace"))
        pos += length
    return ".".join(labels) + ".", pos


def parse_records(buf):
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
        rrtype, _cls, _ttl, rdlen = struct.unpack(">HHIH", buf[pos:pos + 10])
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
                _p, _w, port = struct.unpack(">HHH", rdata[:6])
                target, _ = decode_name(buf, pos + 6)
                value = (target, port)
            elif rrtype == TYPE_TXT:
                pairs, i = {}, 0
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


def discover(duration=3.0):
    """Returns {instance: {name, host, port, rp, secure, txt}}."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    with contextlib.suppress(AttributeError, OSError):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    try:
        sock.bind(("", MDNS_PORT))
    except OSError:
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

        header = struct.pack(">HHHHHH", 0, 0, len(IPP_SERVICES), 0, 0, 0)
        query = header + b"".join(encode_name(n) + struct.pack(">HH", TYPE_PTR, 1)
                                  for n in IPP_SERVICES)
        for _ in range(2):
            with contextlib.suppress(OSError):
                sock.sendto(query, (MDNS_GROUP, MDNS_PORT))
            time.sleep(0.25)

        instances, srv, txt, addr = {}, {}, {}, {}
        deadline = time.time() + duration
        while time.time() < deadline:
            try:
                ready, _, _ = select.select([sock], [], [], max(0.1, deadline - time.time()))
                if not ready:
                    continue
                raw, _ = sock.recvfrom(9000)
            except (OSError, ValueError):
                break
            try:
                records = list(parse_records(raw))
            except (ValueError, struct.error):
                continue
            for name, rrtype, value in records:
                if rrtype == TYPE_PTR and name in IPP_SERVICES:
                    instances[value] = IPP_SERVICES[name]
                elif rrtype == TYPE_SRV:
                    srv[name] = value
                elif rrtype == TYPE_TXT:
                    txt[name] = value
                elif rrtype == TYPE_A:
                    addr[name] = value

        found = {}
        for instance, kind in instances.items():
            hostport = srv.get(instance)
            if not hostport:
                continue
            hostname, port = hostport
            ip = addr.get(hostname)
            if not ip:
                with contextlib.suppress(OSError, socket.gaierror):
                    ip = socket.gethostbyname(hostname.rstrip("."))
            if not ip:
                continue
            info = txt.get(instance, {})
            label = instance.split(".")[0].replace("\\032", " ")
            found[instance] = {
                "name": info.get("ty") or label,
                "host": ip,
                "port": int(port),
                "rp": info.get("rp", "ipp/print"),
                "secure": kind == "ipps",
                "note": info.get("note", ""),
            }
        return found


# --------------------------------------------------------------------------
# CUPS
# --------------------------------------------------------------------------
#
# Read state with lpstat, submit with lp, cancel with cancel. All three are in
# the cups package itself and none of them needs privileges for the operations
# used here. Nothing in this file calls lpadmin.

def run(args, timeout=8):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout, result.stderr
    except (subprocess.SubprocessError, OSError) as exc:
        return 1, "", str(exc)


def cups_available():
    return shutil.which("lpstat") is not None


def cups_queues():
    """Configured queues, their enabled state, and the default."""
    if not cups_available():
        return [], None

    queues = {}
    code, out, _ = run(["lpstat", "-p"])
    if code == 0:
        for line in out.splitlines():
            # CUPS uses two shapes here and only one of them contains "is":
            #   printer Brother_HL is idle.  enabled since ...
            #   printer Old_Laser disabled since ...
            # Matching only the first drops every paused printer from the list,
            # which is the one state the user most needs to be shown.
            m = re.match(r"printer\s+(\S+)\s+(?:is\s+(\w+)|(disabled|stopped))", line)
            if m:
                state = (m.group(2) or m.group(3) or "unknown").lower()
                queues[m.group(1)] = {"queue": m.group(1), "state": state,
                                      "reason": "", "jobs": 0}
            elif line.startswith("\t") and queues:
                last = list(queues)[-1]
                text = line.strip()
                if text and not text.startswith("Form mounted"):
                    queues[last]["reason"] = text[:120]

    default = None
    code, out, _ = run(["lpstat", "-d"])
    if code == 0:
        m = re.search(r"destination:\s*(\S+)", out)
        if m:
            default = m.group(1)

    # Connection URI tells us which discovered printer a queue corresponds to.
    code, out, _ = run(["lpstat", "-v"])
    if code == 0:
        for line in out.splitlines():
            m = re.match(r"device for (\S+):\s*(\S+)", line)
            if m and m.group(1) in queues:
                queues[m.group(1)]["device"] = m.group(2)

    return list(queues.values()), default


def cups_jobs():
    if not cups_available():
        return []
    code, out, _ = run(["lpstat", "-o"])
    if code != 0:
        return []
    jobs = []
    for line in out.splitlines():
        # "Brother_HL-42  james  10240  Sun 24 Aug 2026 09:02:11"
        parts = line.split()
        if len(parts) >= 3:
            jobs.append({"id": parts[0], "user": parts[1],
                         "size": parts[2], "when": " ".join(parts[3:])[:40]})
    return jobs


def host_of(device_uri):
    """The host inside a CUPS device URI, lowercased, for matching discovery.

    Lowercased on purpose and on both paths: DNS is case-insensitive, and a
    console that reports "Printer.lan" while discovery reports "printer.lan"
    would otherwise never be matched to its own queue.
    """
    if not device_uri:
        return None
    with contextlib.suppress(ValueError):
        parsed = urlparse(device_uri)
        if parsed.hostname:
            return parsed.hostname.lower()
    m = re.search(r"//([^/:]+)", device_uri)
    return m.group(1).lower() if m else None


class Paper:
    def __init__(self):
        self.poll = DEFAULT_POLL
        self.running = True
        self.wake = threading.Event()
        self.discovered = {}
        self.lock = threading.Lock()
        self.last_discovery = 0.0

    def rescan(self, duration=3.0):
        emit("scanning", active=True)
        try:
            found = discover(duration)
        except Exception as exc:                        # noqa: BLE001
            log("discovery failed: %s" % exc)
            found = {}
        with self.lock:
            self.discovered = found
            self.last_discovery = time.monotonic()
        emit("scanning", active=False)
        self.wake.set()

    def snapshot(self):
        queues, default = cups_queues()
        jobs = cups_jobs()

        with self.lock:
            discovered = dict(self.discovered)

        by_host = {}
        for q in queues:
            h = host_of(q.get("device"))
            if h:
                by_host.setdefault(h, []).append(q["queue"])

        printers = []
        seen_queues = set()

        for instance, d in discovered.items():
            queue = None
            for q in by_host.get((d["host"] or "").lower(), []):
                queue = q
                break
            if queue:
                seen_queues.add(queue)

            live = {}
            with contextlib.suppress(Exception):
                live = query_printer(d["host"], d["port"], d["rp"], d["secure"])

            printers.append({
                "id": instance,
                "name": d["name"],
                "host": d["host"],
                "discovered": True,
                "queue": queue,
                "isDefault": queue is not None and queue == default,
                "state": live.get("state", "unknown"),
                "stateMessage": live.get("stateMessage", ""),
                "reasons": live.get("reasons", []),
                "model": live.get("makeAndModel", "") or d.get("note", ""),
                "location": live.get("location", ""),
                "acceptingJobs": live.get("acceptingJobs", True),
                "markers": live.get("markers", []),
                "color": live.get("color", False),
                # The command the user runs themselves. This daemon never does.
                "setupCommand": None if queue else
                    'lpadmin -p %s -E -v "%s://%s:%d/%s" -m everywhere' % (
                        re.sub(r"[^A-Za-z0-9_-]", "_", d["name"])[:40],
                        "ipps" if d["secure"] else "ipp",
                        d["host"], d["port"], d["rp"].lstrip("/")),
            })

        # Queues CUPS knows that nothing advertised - USB printers, mostly.
        for q in queues:
            if q["queue"] in seen_queues:
                continue
            printers.append({
                "id": "cups:" + q["queue"],
                "name": q["queue"].replace("_", " "),
                "host": host_of(q.get("device")) or "local",
                "discovered": False,
                "queue": q["queue"],
                "isDefault": q["queue"] == default,
                "state": "idle" if q["state"] == "idle" else q["state"],
                "stateMessage": q.get("reason", ""),
                "reasons": [],
                "model": "",
                "location": "",
                "acceptingJobs": q["state"] != "disabled",
                "markers": [],
                "color": False,
                "setupCommand": None,
            })

        printers.sort(key=lambda p: (not p["isDefault"], p["queue"] is None,
                                     p["name"].lower()))

        emit("snapshot", printers=printers, jobs=jobs, default=default,
             cups=cups_available(), at=int(time.time()))

    def print_file(self, path, queue=None, copies=1, duplex=False):
        path = os.path.expanduser(path or "")
        if path.startswith("file://"):
            from urllib.parse import unquote
            path = unquote(urlparse(path).path)
        if not os.path.isfile(path):
            emit("error", message="%s is not a file." % os.path.basename(path))
            return
        if not shutil.which("lp"):
            emit("error", message="CUPS is not installed, so there is nothing to print with.")
            return

        args = ["lp"]
        if queue:
            args += ["-d", queue]
        if copies and int(copies) > 1:
            args += ["-n", str(int(copies))]
        if duplex:
            args += ["-o", "sides=two-sided-long-edge"]
        args.append(path)

        code, out, err = run(args, timeout=30)
        if code != 0:
            emit("error", message=(err or out or "lp refused the job").strip()[:200])
            return
        m = re.search(r"request id is (\S+)", out)
        emit("submitted", job=m.group(1) if m else "", file=os.path.basename(path),
             queue=queue or "default")
        self.wake.set()

    def cancel(self, job_id):
        if not shutil.which("cancel") or not job_id:
            return
        run(["cancel", str(job_id)])
        self.wake.set()

    def loop(self):
        while self.running:
            try:
                if time.monotonic() - self.last_discovery > DISCOVERY_INTERVAL:
                    self.rescan()
                self.snapshot()
            except Exception as exc:                    # noqa: BLE001
                log("poll failed: %s" % exc)
                emit("error", message=str(exc))
            self.wake.wait(max(5.0, self.poll))
            self.wake.clear()


def handle_command(paper, msg):
    cmd = msg.get("cmd")
    if cmd == "config":
        with contextlib.suppress(TypeError, ValueError):
            paper.poll = float(msg.get("pollSeconds") or DEFAULT_POLL)
        paper.wake.set()
    elif cmd == "rescan":
        threading.Thread(target=paper.rescan, daemon=True).start()
    elif cmd == "refresh":
        paper.wake.set()
    elif cmd == "print":
        threading.Thread(target=paper.print_file,
                         args=(msg.get("path"), msg.get("queue"),
                               msg.get("copies", 1), msg.get("duplex", False)),
                         daemon=True).start()
    elif cmd == "cancel":
        paper.cancel(msg.get("job"))
    elif cmd == "quit":
        paper.running = False
        paper.wake.set()


def main():
    paper = Paper()
    emit("ready", cups=cups_available(),
         canPrint=shutil.which("lp") is not None)
    threading.Thread(target=paper.loop, daemon=True).start()

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
            handle_command(paper, msg)
        except Exception as exc:                        # noqa: BLE001
            log("command %r failed: %s" % (msg.get("cmd"), exc))
            emit("error", message=str(exc))
        if not paper.running:
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
