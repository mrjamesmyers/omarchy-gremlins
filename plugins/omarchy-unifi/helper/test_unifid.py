#!/usr/bin/env python3
"""
Tests for unifid, driven against a mock UniFi console over real TLS.

The parts worth testing here are the ones that are easy to get quietly wrong:
which base path the console answers on, whether pagination actually walks the
whole collection, whether a key file with loose permissions is refused, and
whether certificate pinning notices a swapped certificate.

    python3 test_unifid.py
"""

import contextlib
import importlib.util
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))

PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print("  %s %s%s" % ("PASS" if condition else "FAIL", name,
                         "" if condition else "   <- %s" % detail))


def load_module(state_dir):
    """Fresh import with STATE_DIR redirected, so pins land in the sandbox."""
    os.environ["XDG_STATE_HOME"] = state_dir
    spec = importlib.util.spec_from_file_location(
        "unifid_%d" % int(time.time() * 1000), os.path.join(HERE, "unifid.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


API_KEY = "test-key-abc123"
SITE_ID = "site-1"


class MockConsole:
    """A UniFi OS console, as far as the integration API is concerned."""

    def __init__(self, workdir, base_path="/proxy/network/integration/v1",
                 cert_name="console", client_total=250):
        self.base = base_path
        self.client_total = client_total
        self.seen_keys = []
        self.paths = []

        self.cert = os.path.join(workdir, "%s-cert.pem" % cert_name)
        self.key = os.path.join(workdir, "%s-key.pem" % cert_name)
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout", self.key,
             "-out", self.cert, "-days", "2", "-nodes", "-subj", "/CN=%s" % cert_name],
            check=True, capture_output=True)

        console = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _json(self, code, payload):
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                console.paths.append(self.path)
                console.seen_keys.append(self.headers.get("X-API-KEY"))
                if self.headers.get("X-API-KEY") != API_KEY:
                    return self._json(401, {"error": "unauthorised"})

                route, _, query = self.path.partition("?")
                params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
                offset = int(params.get("offset", 0))
                limit = int(params.get("limit", 200))

                if not route.startswith(console.base):
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                tail = route[len(console.base):]

                if tail == "/sites":
                    return self._json(200, {"offset": 0, "limit": limit, "count": 1,
                                            "totalCount": 1,
                                            "data": [{"id": SITE_ID, "name": "Home"}]})

                if tail == "/sites/%s/devices" % SITE_ID:
                    devices = [
                        {"id": "d-gw", "name": "Dream Machine", "model": "UDMPROSE",
                         "state": "ONLINE", "ipAddress": "192.168.1.1"},
                        {"id": "d-ap1", "name": "Loft AP", "model": "U6LR",
                         "state": "ONLINE", "ipAddress": "192.168.1.20"},
                        {"id": "d-ap2", "name": "Garage AP", "model": "U6LITE",
                         "state": "OFFLINE", "ipAddress": "192.168.1.21"},
                    ]
                    window = devices[offset:offset + limit]
                    return self._json(200, {"offset": offset, "limit": limit,
                                            "count": len(window),
                                            "totalCount": len(devices), "data": window})

                if tail == "/sites/%s/clients" % SITE_ID:
                    clients = [{"id": "c%d" % i, "name": "client-%d" % i,
                                "type": "WIRED" if i % 5 == 0 else "WIRELESS"}
                               for i in range(console.client_total)]
                    window = clients[offset:offset + limit]
                    return self._json(200, {"offset": offset, "limit": limit,
                                            "count": len(window),
                                            "totalCount": len(clients), "data": window})

                if tail == "/sites/%s/devices/d-gw/statistics/latest" % SITE_ID:
                    return self._json(200, {
                        "cpuUtilizationPct": 12.5, "memoryUtilizationPct": 43.0,
                        "uptimeSec": 864000,
                        "uplink": {"txRateBps": 1200000, "rxRateBps": 9800000},
                    })

                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert, self.key)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.httpd.socket = context.wrap_socket(self.httpd.socket, server_side=True)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        with contextlib.suppress(Exception):
            self.httpd.shutdown()


def make_key_file(workdir, mode=0o600, value=API_KEY):
    path = os.path.join(workdir, "unifi.key")
    with open(path, "w") as fh:
        fh.write(value + "\n")
    os.chmod(path, mode)
    return path


def collect(module):
    """Capture emitted events instead of writing them to stdout."""
    events = []
    module.emit = lambda ev, **f: events.append(dict(f, ev=ev))
    return events


# --------------------------------------------------------------------------
# cases
# --------------------------------------------------------------------------

def configure(unifi, console, key_path):
    unifi.host = "127.0.0.1"
    unifi.port = console.port
    unifi.key_file = key_path


def test_snapshot(workdir):
    state = tempfile.mkdtemp(dir=workdir)
    module = load_module(state)
    events = collect(module)
    console = MockConsole(workdir, cert_name="snap")
    try:
        unifi = module.Unifi()
        configure(unifi, console, make_key_file(workdir))
        unifi.snapshot()

        snaps = [e for e in events if e["ev"] == "snapshot"]
        check("snapshot: one snapshot emitted", len(snaps) == 1,
              [e["ev"] for e in events])
        if not snaps:
            return
        snap = snaps[0]

        check("snapshot: site resolved", snap["site"]["name"] == "Home", snap["site"])
        check("snapshot: every device listed", snap["deviceCount"] == 3,
              snap["deviceCount"])
        check("snapshot: online count correct", snap["devicesOnline"] == 2,
              snap["devicesOnline"])
        check("snapshot: offline device sorts last",
              snap["devices"][-1]["name"] == "Garage AP",
              [d["name"] for d in snap["devices"]])

        # 250 clients across a 200-item page is the whole point of paging.
        check("snapshot: pagination walked every client", snap["clientCount"] == 250,
              snap["clientCount"])
        check("snapshot: wired/wireless split", snap["wired"] == 50 and snap["wireless"] == 200,
              (snap["wired"], snap["wireless"]))

        check("snapshot: gateway identified",
              snap["gateway"] and snap["gateway"]["model"] == "UDMPROSE", snap["gateway"])
        check("snapshot: gateway statistics fetched",
              snap["uplink"].get("cpu") == 12.5 and snap["uplink"].get("rxRate") == 9800000,
              snap["uplink"])

        check("snapshot: api key sent on every request",
              console.seen_keys and all(k == API_KEY for k in console.seen_keys),
              set(console.seen_keys))
    finally:
        console.stop()


def test_base_path_probe(workdir):
    """A console on the plural spelling must still be found."""
    state = tempfile.mkdtemp(dir=workdir)
    module = load_module(state)
    collect(module)
    console = MockConsole(workdir, base_path="/proxy/network/integrations/v1",
                          cert_name="plural", client_total=3)
    try:
        unifi = module.Unifi()
        configure(unifi, console, make_key_file(workdir))
        base = unifi.resolve_base()
        check("probe: found the plural base path",
              base == "/proxy/network/integrations/v1", base)
        check("probe: singular was tried first",
              console.paths and console.paths[0].startswith("/proxy/network/integration/v1"),
              console.paths[:2])

        console.paths.clear()
        unifi.resolve_base()
        check("probe: result is cached, not re-probed", console.paths == [], console.paths)
    finally:
        console.stop()


def test_key_handling(workdir):
    state = tempfile.mkdtemp(dir=workdir)
    module = load_module(state)
    events = collect(module)
    console = MockConsole(workdir, cert_name="keys", client_total=3)
    try:
        unifi = module.Unifi()

        # A key file the world can read is refused, not used.
        loose = make_key_file(workdir, mode=0o644)
        configure(unifi, console, loose)
        raised = False
        try:
            unifi.snapshot()
        except module.AuthProblem:
            raised = True
        check("key: world-readable key file is refused", raised)
        check("key: and the user is told to fix it",
              any("chmod 600" in (e.get("message") or "") for e in events),
              [e.get("message") for e in events])

        # A wrong key must surface as an authorisation failure, not a blank panel.
        events.clear()
        wrong = os.path.join(workdir, "wrong.key")
        with open(wrong, "w") as fh:
            fh.write("nope")
        os.chmod(wrong, 0o600)
        unifi.key_file = wrong
        unifi.base = None
        raised = False
        message = ""
        try:
            unifi.resolve_base()
        except module.AuthProblem as exc:
            raised = True
            message = str(exc)
        check("key: a rejected key raises rather than looking empty", raised)
        check("key: and says the key was rejected, not that the host is down",
              "key" in message.lower() and "found" not in message.lower(), message)

        # The environment overrides the file, so a key never has to hit disk.
        os.environ["UNIFI_API_KEY"] = API_KEY
        try:
            check("key: environment variable takes precedence",
                  module.read_key(wrong) == API_KEY, module.read_key(wrong))
        finally:
            del os.environ["UNIFI_API_KEY"]
    finally:
        console.stop()


def test_pinning(workdir):
    """Trust on first use: remember the certificate, then notice a swap."""
    state = tempfile.mkdtemp(dir=workdir)
    module = load_module(state)
    events = collect(module)
    key_path = make_key_file(workdir)

    console = MockConsole(workdir, cert_name="pin-a", client_total=3)
    port = console.port
    try:
        unifi = module.Unifi()
        configure(unifi, console, key_path)
        unifi.snapshot()

        pinned = [e for e in events if e["ev"] == "pinned"]
        check("pin: certificate recorded on first contact", len(pinned) == 1, events)
        fingerprint = pinned[0]["fingerprint"] if pinned else None
        check("pin: fingerprint is a sha256",
              fingerprint and len(fingerprint) == 64, fingerprint)
        check("pin: written to disk",
              module.load_pin("127.0.0.1") == fingerprint, module.load_pin("127.0.0.1"))

        events.clear()
        unifi.snapshot()
        check("pin: a second connection does not re-pin",
              not any(e["ev"] == "pinned" for e in events))
        check("pin: and still works", any(e["ev"] == "snapshot" for e in events))
    finally:
        console.stop()

    # Same address, different certificate. This is the case that matters.
    swapped = None
    for _ in range(30):
        candidate = MockConsole(workdir, cert_name="pin-b", client_total=3)
        if candidate.port == port:
            swapped = candidate
            break
        candidate.stop()

    if swapped is None:
        # Rebinding the exact ephemeral port is not guaranteed; verify the
        # comparison directly instead of skipping the assertion entirely.
        module.save_pin("127.0.0.1", "0" * 64)
        console2 = MockConsole(workdir, cert_name="pin-c", client_total=3)
        try:
            unifi = module.Unifi()
            configure(unifi, console2, key_path)
            caught = False
            try:
                unifi.snapshot()
            except module.PinMismatch:
                caught = True
            check("pin: a changed certificate is rejected", caught)
        finally:
            console2.stop()
        return

    try:
        unifi = module.Unifi()
        configure(unifi, swapped, key_path)
        caught = False
        try:
            unifi.snapshot()
        except module.PinMismatch:
            caught = True
        check("pin: a changed certificate is rejected", caught)
    finally:
        swapped.stop()


def main():
    if not shutil.which("openssl"):
        print("openssl is required for these tests")
        return 2

    workdir = tempfile.mkdtemp(prefix="unifi-test-")
    try:
        print("-- snapshot --")
        test_snapshot(workdir)
        print("\n-- base path probing --")
        test_base_path_probe(workdir)
        print("\n-- api key handling --")
        test_key_handling(workdir)
        print("\n-- certificate pinning --")
        test_pinning(workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    for name in FAILED:
        print("   failed: %s" % name)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
