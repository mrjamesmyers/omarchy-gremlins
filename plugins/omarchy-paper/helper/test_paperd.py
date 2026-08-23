#!/usr/bin/env python3
"""
Tests for paperd.

IPP is a binary encoding that either matches RFC 8011 exactly or the printer
ignores you, so most of these build real request bytes and parse real response
bytes, and the round-trip runs over an actual HTTP socket against a mock
printer. The CUPS half is tested by feeding real lpstat output through the
parsers.

    python3 test_paperd.py
"""

import contextlib
import importlib.util
import os
import struct
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("paperd", os.path.join(HERE, "paperd.py"))
paperd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(paperd)

PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print("  %s %s%s" % ("PASS" if condition else "FAIL", name,
                         "" if condition else "   <- %s" % detail))


# --------------------------------------------------------------------------
# IPP encoding
# --------------------------------------------------------------------------

def test_ipp_request():
    body = paperd.build_get_printer_attributes("ipp://192.168.1.9:631/ipp/print", 7)

    version, op, rid = struct.unpack(">HHI", body[:8])
    check("ipp: version is 2.0", version == 0x0200, hex(version))
    check("ipp: operation is Get-Printer-Attributes",
          op == paperd.OP_GET_PRINTER_ATTRIBUTES, hex(op))
    check("ipp: request id round-trips", rid == 7, rid)
    check("ipp: operation group opens the body", body[8] == paperd.TAG_OPERATION,
          hex(body[8]))
    check("ipp: ends with end-of-attributes", body[-1] == paperd.TAG_END, hex(body[-1]))

    # RFC 8011 requires charset first, then natural-language, before anything else.
    charset_at = body.find(b"attributes-charset")
    language_at = body.find(b"attributes-natural-language")
    uri_at = body.find(b"printer-uri")
    check("ipp: charset precedes natural-language precedes printer-uri",
          0 < charset_at < language_at < uri_at, (charset_at, language_at, uri_at))
    check("ipp: printer uri is carried", b"ipp://192.168.1.9:631/ipp/print" in body)

    # Additional values must use a zero-length name, or the printer reads them
    # as separate unknown attributes and ignores all but the first.
    check("ipp: requested-attributes appears exactly once as a name",
          body.count(b"requested-attributes") == 1, body.count(b"requested-attributes"))
    for attribute in (b"printer-state", b"marker-levels", b"printer-make-and-model"):
        check("ipp: requests %s" % attribute.decode(), attribute in body)


def build_response(status=0x0000):
    """A response shaped like a real printer's, with multi-value attributes."""
    out = bytearray()
    out += struct.pack(">HHI", 0x0200, status, 1)
    out.append(paperd.TAG_PRINTER)

    def attr(tag, name, value):
        n = name.encode()
        # bool must be tested before int: in Python, True is an instance of int,
        # so the int branch would otherwise encode a boolean as four bytes.
        if isinstance(value, bool):
            v = b"\x01" if value else b"\x00"
        elif isinstance(value, int):
            v = struct.pack(">i", value)
        else:
            v = value.encode()
        return struct.pack(">BH", tag, len(n)) + n + struct.pack(">H", len(v)) + v

    out += attr(paperd.TAG_NAME, "printer-name", "Brother HL-L2350DW")
    out += attr(paperd.TAG_TEXT, "printer-make-and-model", "Brother HL-L2350DW series")
    out += attr(paperd.TAG_ENUM, "printer-state", 4)                 # printing
    out += attr(paperd.TAG_KEYWORD, "printer-state-reasons", "media-low")
    out += attr(paperd.TAG_KEYWORD, "", "toner-low")                 # additional value
    out += attr(paperd.TAG_TEXT, "printer-location", "Study")
    out += attr(paperd.TAG_BOOLEAN, "printer-is-accepting-jobs", True)
    out += attr(paperd.TAG_INTEGER, "queued-job-count", 2)
    out += attr(paperd.TAG_NAME, "marker-names", "Black Toner")
    out += attr(paperd.TAG_NAME, "", "Drum Unit")
    out += attr(paperd.TAG_INTEGER, "marker-levels", 42)
    out += attr(paperd.TAG_INTEGER, "", 88)
    out += attr(paperd.TAG_BOOLEAN, "color-supported", False)
    out.append(paperd.TAG_END)
    return bytes(out)


def test_ipp_parse():
    attributes = paperd.parse_ipp(build_response())
    check("parse: status extracted", attributes["_status"] == 0)
    check("parse: name", attributes["printer-name"] == "Brother HL-L2350DW",
          attributes.get("printer-name"))
    check("parse: enum decoded as int", attributes["printer-state"] == 4,
          attributes.get("printer-state"))
    check("parse: integer decoded", attributes["queued-job-count"] == 2)
    check("parse: boolean true", attributes["printer-is-accepting-jobs"] is True)
    check("parse: boolean false", attributes["color-supported"] is False)

    # The zero-length-name rule is the easiest thing to get wrong in IPP.
    check("parse: multi-value reasons collected",
          attributes["printer-state-reasons"] == ["media-low", "toner-low"],
          attributes.get("printer-state-reasons"))
    check("parse: parallel marker arrays stay aligned",
          attributes["marker-names"] == ["Black Toner", "Drum Unit"]
          and attributes["marker-levels"] == [42, 88],
          (attributes.get("marker-names"), attributes.get("marker-levels")))

    four_byte = struct.pack(">BH", paperd.TAG_BOOLEAN, 4) + b"flag" + \
                struct.pack(">H", 4) + struct.pack(">i", 1)
    framed = struct.pack(">HHI", 0x0200, 0, 1) + bytes([paperd.TAG_PRINTER]) + \
             four_byte + bytes([paperd.TAG_END])
    check("parse: a four-byte boolean still reads as true",
          paperd.parse_ipp(framed).get("flag") is True, paperd.parse_ipp(framed).get("flag"))

    check("parse: a truncated response raises rather than hanging",
          _raises(lambda: paperd.parse_ipp(b"\x02\x00")))


def _raises(fn):
    try:
        fn()
        return False
    except Exception:                                   # noqa: BLE001
        return True


# --------------------------------------------------------------------------
# a mock printer, over real HTTP
# --------------------------------------------------------------------------

class MockPrinter:
    def __init__(self):
        self.requests = []
        printer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                printer.requests.append({
                    "path": self.path,
                    "type": self.headers.get("Content-Type"),
                    "body": self.rfile.read(length),
                })
                body = build_response()
                self.send_response(200)
                self.send_header("Content-Type", "application/ipp")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        with contextlib.suppress(Exception):
            self.httpd.shutdown()


def test_round_trip():
    printer = MockPrinter()
    try:
        info = paperd.query_printer("127.0.0.1", printer.port, "ipp/print", False)

        check("round-trip: content type is application/ipp",
              printer.requests and printer.requests[0]["type"] == "application/ipp",
              printer.requests[0]["type"] if printer.requests else None)
        check("round-trip: posted to the rp path",
              printer.requests[0]["path"] == "/ipp/print", printer.requests[0]["path"])
        check("round-trip: state mapped to a word", info["state"] == "printing",
              info["state"])
        check("round-trip: model carried", "Brother" in info["makeAndModel"],
              info["makeAndModel"])
        check("round-trip: location carried", info["location"] == "Study")
        check("round-trip: 'none' reasons would be dropped, real ones kept",
              info["reasons"] == ["media-low", "toner-low"], info["reasons"])
        check("round-trip: markers paired into objects",
              info["markers"] == [{"name": "Black Toner", "level": 42, "color": ""},
                                  {"name": "Drum Unit", "level": 88, "color": ""}],
              info["markers"])
        check("round-trip: queued count", info["queued"] == 2)
        check("round-trip: mono printer reported as mono", info["color"] is False)
        check("round-trip: uri rebuilt correctly",
              info["uri"] == "ipp://127.0.0.1:%d/ipp/print" % printer.port, info["uri"])
    finally:
        printer.stop()


# --------------------------------------------------------------------------
# CUPS parsing
# --------------------------------------------------------------------------

LPSTAT_P = """printer Brother_HL_L2350DW is idle.  enabled since Sun 24 Aug 2026 08:14:22
printer Office_Colour is printing.  enabled since Sun 24 Aug 2026 09:01:00
\tStatus: Loading paper tray
printer Old_Laser disabled since Fri 22 Aug 2026 17:40:11
\tStatus: Paused by user
"""

LPSTAT_V = """device for Brother_HL_L2350DW: ipp://192.168.1.9:631/ipp/print
device for Office_Colour: ipps://printer.lan:631/ipp/print
device for Old_Laser: usb://Old/Laser?serial=X1
"""

LPSTAT_D = "system default destination: Brother_HL_L2350DW\n"

LPSTAT_O = """Brother_HL_L2350DW-42   james   10240   Sun 24 Aug 2026 09:02:11
Office_Colour-7         james   88112   Sun 24 Aug 2026 09:03:40
"""


def with_fake_cups(fn):
    """Swap paperd.run for canned lpstat output, then put it back."""
    real_run, real_which = paperd.run, paperd.shutil.which

    def fake_run(args, timeout=8):
        if args[:2] == ["lpstat", "-p"]:
            return 0, LPSTAT_P, ""
        if args[:2] == ["lpstat", "-v"]:
            return 0, LPSTAT_V, ""
        if args[:2] == ["lpstat", "-d"]:
            return 0, LPSTAT_D, ""
        if args[:2] == ["lpstat", "-o"]:
            return 0, LPSTAT_O, ""
        return 1, "", "unexpected: %s" % args

    paperd.run = fake_run
    paperd.shutil.which = lambda name: "/usr/bin/" + name
    try:
        return fn()
    finally:
        paperd.run, paperd.shutil.which = real_run, real_which


def test_cups_parsing():
    def body():
        queues, default = paperd.cups_queues()
        jobs = paperd.cups_jobs()
        return queues, default, jobs

    queues, default, jobs = with_fake_cups(body)
    by_name = {q["queue"]: q for q in queues}

    check("cups: all three queues parsed", len(queues) == 3, [q["queue"] for q in queues])
    check("cups: idle state read", by_name["Brother_HL_L2350DW"]["state"] == "idle",
          by_name.get("Brother_HL_L2350DW"))
    check("cups: printing state read", by_name["Office_Colour"]["state"] == "printing")
    check("cups: disabled state read", by_name["Old_Laser"]["state"] == "disabled",
          by_name["Old_Laser"]["state"])
    check("cups: indented status line attaches to its printer",
          by_name["Office_Colour"]["reason"] == "Status: Loading paper tray",
          by_name["Office_Colour"]["reason"])
    check("cups: default destination found", default == "Brother_HL_L2350DW", default)
    check("cups: device uri captured",
          by_name["Brother_HL_L2350DW"]["device"] == "ipp://192.168.1.9:631/ipp/print",
          by_name["Brother_HL_L2350DW"].get("device"))
    check("cups: jobs listed", len(jobs) == 2 and jobs[0]["id"] == "Brother_HL_L2350DW-42",
          jobs)
    check("cups: job owner parsed", jobs[0]["user"] == "james", jobs)


def test_host_matching():
    cases = [
        ("ipp://192.168.1.9:631/ipp/print", "192.168.1.9"),
        ("ipps://Printer.LAN:631/ipp/print", "printer.lan"),
        ("usb://Old/Laser?serial=X1", "old"),
        ("socket://10.0.0.5:9100", "10.0.0.5"),
        ("", None),
        (None, None),
    ]
    ok = True
    for uri, expected in cases:
        got = paperd.host_of(uri)
        if got != expected:
            ok = False
            check("host: %r -> %r" % (uri, expected), False, got)
    check("host: every device uri resolves to the right host", ok)


def test_no_privilege_escalation():
    """The plugin must never run a privileged command. This is load-bearing."""
    source = open(os.path.join(HERE, "paperd.py")).read()
    import ast
    tree = ast.parse(source)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            rendered = ast.unparse(node)
            is_exec = (isinstance(node.func, ast.Name) and node.func.id == "run") or \
                      (isinstance(node.func, ast.Attribute) and node.func.attr in ("run", "Popen"))
            if is_exec and any(w in rendered for w in ("lpadmin", "sudo", "pkexec", "doas")):
                offenders.append(rendered[:70])
    check("privilege: no privileged command is ever executed", not offenders, offenders)

    # It should still TELL the user the command - that is the whole design.
    check("privilege: the setup command is offered as text", "lpadmin -p" in source)


def test_setup_command_is_safe():
    """A printer name off the network must not be able to inject shell syntax."""
    paper = paperd.Paper()
    paper.discovered = {
        "evil._ipp._tcp.local.": {
            "name": 'Printer"; rm -rf ~; echo "',
            "host": "192.168.1.50", "port": 631, "rp": "ipp/print",
            "secure": False, "note": "",
        }
    }
    captured = {}
    real_emit = paperd.emit
    paperd.emit = lambda ev, **f: captured.update({ev: f}) if ev == "snapshot" else None
    real_run, real_which = paperd.run, paperd.shutil.which
    paperd.run = lambda args, timeout=8: (1, "", "no cups")
    paperd.shutil.which = lambda name: None
    try:
        paper.snapshot()
    finally:
        paperd.emit, paperd.run, paperd.shutil.which = real_emit, real_run, real_which

    printers = captured.get("snapshot", {}).get("printers", [])
    check("injection: the hostile printer still appears", len(printers) == 1, printers)
    if printers:
        cmd = printers[0]["setupCommand"] or ""
        check("injection: shell metacharacters stripped from the queue name",
              ";" not in cmd and "rm -rf" not in cmd and '"' in cmd, cmd)
        check("injection: queue name reduced to safe characters",
              __import__("re").search(r"lpadmin -p ([A-Za-z0-9_-]+) ", cmd) is not None, cmd)


def main():
    print("-- IPP request encoding --")
    test_ipp_request()
    print("\n-- IPP response parsing --")
    test_ipp_parse()
    print("\n-- round trip over HTTP --")
    test_round_trip()
    print("\n-- CUPS output parsing --")
    test_cups_parsing()
    print("\n-- device uri matching --")
    test_host_matching()
    print("\n-- privilege boundary --")
    test_no_privilege_escalation()
    print("\n-- untrusted printer names --")
    test_setup_command_is_safe()

    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    for name in FAILED:
        print("   failed: %s" % name)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
