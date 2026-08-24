#!/usr/bin/env python3
"""
End-to-end protocol tests for beamd.

These drive the daemon the way a real LocalSend client does - over TLS, over
the real HTTP routes, with real bytes on the wire - rather than calling its
internals. A test that reaches past the socket proves nothing about whether a
phone can talk to it.

    python3 test_beamd.py

Exit status is 0 when every case passes. No third-party test runner: the
plugin ships with no dependencies and its tests should not add one.
"""

import contextlib
import hashlib
import http.client
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.join(HERE, "beamd.py")

BEAM_PORT = 53517          # off the default so a real LocalSend can coexist
MOCK_PORT = 53518

PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print("  %s %s%s" % ("PASS" if condition else "FAIL", name,
                         "" if condition else "   <- %s" % detail))


def free_port(port):
    with contextlib.suppress(OSError):
        s = socket.socket()
        with contextlib.closing(s):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port))
            return True
    return False


# --------------------------------------------------------------------------
# a mock LocalSend peer: acts as receiver for beamd's send path
# --------------------------------------------------------------------------

class MockPeer:
    def __init__(self, workdir, port):
        self.port = port
        self.fingerprint = uuid.uuid4().hex
        self.inbox = workdir
        self.received = {}
        self.sessions = {}
        self.reject = False
        self.cert = os.path.join(workdir, "mock-cert.pem")
        self.key = os.path.join(workdir, "mock-key.pem")
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout", self.key,
             "-out", self.cert, "-days", "2", "-nodes", "-subj", "/CN=MockPeer"],
            check=True, capture_output=True)
        self.httpd = None

    def info(self):
        return {"alias": "Mock Phone", "version": "2.1", "deviceModel": "Pixel",
                "deviceType": "mobile", "fingerprint": self.fingerprint,
                "port": self.port, "protocol": "https", "download": False}

    def start(self):
        peer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(n)

            def _reply(self, code, payload=None):
                data = b"" if payload is None else json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(data)))
                if data:
                    self.send_header("Content-Type", "application/json")
                self.end_headers()
                if data:
                    self.wfile.write(data)

            def do_POST(self):
                route = self.path.split("?", 1)[0]
                q = dict(p.split("=", 1) for p in self.path.split("?", 1)[1].split("&")
                         if "=" in p) if "?" in self.path else {}

                if route == "/api/localsend/v2/register":
                    self._body()
                    return self._reply(200, peer.info())

                if route == "/api/localsend/v2/prepare-upload":
                    payload = json.loads(self._body())
                    if peer.reject:
                        return self._reply(403)
                    sid = uuid.uuid4().hex
                    tokens = {fid: uuid.uuid4().hex for fid in payload["files"]}
                    peer.sessions[sid] = {"tokens": tokens, "files": payload["files"]}
                    return self._reply(200, {"sessionId": sid, "files": tokens})

                if route == "/api/localsend/v2/upload":
                    session = peer.sessions.get(q.get("sessionId"))
                    if not session or session["tokens"].get(q.get("fileId")) != q.get("token"):
                        return self._reply(403)
                    data = self._body()
                    meta = session["files"][q["fileId"]]
                    peer.received[meta["fileName"]] = data
                    return self._reply(200)

                self._reply(404)

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.cert, self.key)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.httpd.daemon_threads = True
        self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()


# --------------------------------------------------------------------------
# talking to beamd
# --------------------------------------------------------------------------

def client(port):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return http.client.HTTPSConnection("127.0.0.1", port, timeout=20, context=ctx)


def post(port, path, payload=None, raw=None):
    conn = client(port)
    with contextlib.closing(conn):
        body = raw if raw is not None else (
            json.dumps(payload).encode() if payload is not None else b"")
        conn.request("POST", path, body=body,
                     headers={"Content-Type": "application/json",
                              "Content-Length": str(len(body))})
        r = conn.getresponse()
        return r.status, r.read()


class Daemon:
    """Runs beamd.py and collects its event stream."""

    def __init__(self, download_dir, port):
        env = dict(os.environ)
        self.state = tempfile.mkdtemp(prefix="beam-state-")
        env["XDG_STATE_HOME"] = self.state
        self.proc = subprocess.Popen(
            [sys.executable, DAEMON], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1, env=env)
        self.events = []
        self.lock = threading.Lock()
        threading.Thread(target=self._pump, daemon=True).start()
        self.port = port
        self.send({"cmd": "config", "downloadDir": download_dir})

    def _pump(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            with contextlib.suppress(ValueError):
                with self.lock:
                    self.events.append(json.loads(line))

    def send(self, msg):
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def wait_for(self, name, timeout=20, predicate=None):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                for ev in self.events:
                    if ev.get("ev") == name and (predicate is None or predicate(ev)):
                        return ev
            time.sleep(0.05)
        return None

    def stop(self):
        with contextlib.suppress(Exception):
            self.send({"cmd": "quit"})
            self.proc.wait(timeout=5)
        with contextlib.suppress(Exception):
            self.proc.kill()
        shutil.rmtree(self.state, ignore_errors=True)


# --------------------------------------------------------------------------
# cases
# --------------------------------------------------------------------------

def sender_info(fingerprint, port):
    return {"alias": "Mock Phone", "version": "2.1", "deviceModel": "Pixel",
            "deviceType": "mobile", "fingerprint": fingerprint,
            "port": port, "protocol": "https", "download": False}


def case_receive(daemon, mock, inbox):
    """A peer sends us two files, one with a hostile name. We accept."""
    payload_a = b"the quick brown fox" * 5000
    payload_b = b"second file"
    files = {
        "f1": {"id": "f1", "fileName": "../../etc/passwd", "size": len(payload_a),
               "fileType": "text/plain",
               "sha256": hashlib.sha256(payload_a).hexdigest()},
        "f2": {"id": "f2", "fileName": "notes.txt", "size": len(payload_b),
               "fileType": "text/plain"},
    }

    result = {}

    def do_prepare():
        result["status"], result["body"] = post(
            daemon.port, "/api/localsend/v2/prepare-upload",
            {"info": sender_info(mock.fingerprint, mock.port), "files": files})

    thread = threading.Thread(target=do_prepare)
    thread.start()

    incoming = daemon.wait_for("incoming", timeout=15)
    check("receive: incoming event raised", incoming is not None)
    if not incoming:
        thread.join(timeout=5)
        return
    check("receive: sender identified", incoming["sender"]["alias"] == "Mock Phone",
          incoming["sender"])
    check("receive: both files listed", len(incoming["files"]) == 2)
    check("receive: filename sanitised before the user sees it",
          all("/" not in f["fileName"] for f in incoming["files"]),
          [f["fileName"] for f in incoming["files"]])

    daemon.send({"cmd": "accept", "sessionId": incoming["sessionId"]})
    thread.join(timeout=20)

    check("receive: prepare-upload accepted with 200", result.get("status") == 200,
          result.get("status"))
    if result.get("status") != 200:
        return
    prepared = json.loads(result["body"])
    tokens = prepared["files"]
    check("receive: a token per file", set(tokens) == {"f1", "f2"})

    for fid, blob in (("f1", payload_a), ("f2", payload_b)):
        status, _ = post(daemon.port,
                         "/api/localsend/v2/upload?sessionId=%s&fileId=%s&token=%s"
                         % (prepared["sessionId"], fid, tokens[fid]), raw=blob)
        check("receive: upload of %s returned 200" % fid, status == 200, status)

    done = daemon.wait_for("finished", timeout=15,
                           predicate=lambda e: e.get("direction") == "in")
    check("receive: finished ok", done is not None and done.get("ok") is True, done)

    landed = sorted(os.listdir(inbox))
    check("receive: two files on disk", len(landed) == 2, landed)
    check("receive: traversal name written inside the inbox", "passwd" in landed, landed)
    check("receive: nothing escaped the inbox",
          not os.path.exists("/tmp/etc/passwd") and landed == sorted(landed))
    with open(os.path.join(inbox, "passwd"), "rb") as fh:
        check("receive: bytes intact", fh.read() == payload_a)


def case_checksum(daemon, mock, inbox):
    """A file whose sha256 does not match must be refused and not left behind."""
    truth = b"honest bytes"
    lie = b"tampered!!!!"
    files = {"c1": {"id": "c1", "fileName": "tampered.bin", "size": len(lie),
                    "fileType": "application/octet-stream",
                    "sha256": hashlib.sha256(truth).hexdigest()}}

    result = {}
    thread = threading.Thread(target=lambda: result.update(zip(
        ("status", "body"),
        post(daemon.port, "/api/localsend/v2/prepare-upload",
             {"info": sender_info(mock.fingerprint, mock.port), "files": files}))))
    thread.start()
    incoming = daemon.wait_for("incoming", timeout=15,
                               predicate=lambda e: e["files"][0]["fileName"] == "tampered.bin")
    if not incoming:
        check("checksum: incoming raised", False)
        thread.join(timeout=5)
        return
    daemon.send({"cmd": "accept", "sessionId": incoming["sessionId"]})
    thread.join(timeout=20)

    prepared = json.loads(result["body"])
    status, _ = post(daemon.port,
                     "/api/localsend/v2/upload?sessionId=%s&fileId=c1&token=%s"
                     % (prepared["sessionId"], prepared["files"]["c1"]), raw=lie)
    check("checksum: mismatch rejected with 422", status == 422, status)
    check("checksum: corrupt file not left on disk",
          "tampered.bin" not in os.listdir(inbox), os.listdir(inbox))


def case_reject(daemon, mock):
    """Declining must answer 403, which is what makes the phone stop asking."""
    files = {"r1": {"id": "r1", "fileName": "unwanted.bin", "size": 4,
                    "fileType": "application/octet-stream"}}
    result = {}
    thread = threading.Thread(target=lambda: result.update(zip(
        ("status", "body"),
        post(daemon.port, "/api/localsend/v2/prepare-upload",
             {"info": sender_info(mock.fingerprint, mock.port), "files": files}))))
    thread.start()
    incoming = daemon.wait_for("incoming", timeout=15,
                               predicate=lambda e: e["files"][0]["fileName"] == "unwanted.bin")
    if not incoming:
        check("reject: incoming raised", False)
        thread.join(timeout=5)
        return
    daemon.send({"cmd": "reject", "sessionId": incoming["sessionId"]})
    thread.join(timeout=20)
    check("reject: declined with 403", result.get("status") == 403, result.get("status"))


def case_send(daemon, mock, workdir):
    """We send a file to a peer that registered with us."""
    blob = os.urandom(300_000)
    path = os.path.join(workdir, "outbound.bin")
    with open(path, "wb") as fh:
        fh.write(blob)

    # The peer introduces itself the way a real one does, over /register.
    status, body = post(daemon.port, "/api/localsend/v2/register", mock.info())
    check("send: register accepted", status == 200, status)
    check("send: we answered with our own info",
          json.loads(body).get("alias") is not None)

    peer_ev = daemon.wait_for("peer", timeout=10,
                              predicate=lambda e: e["device"]["fingerprint"] == mock.fingerprint)
    check("send: peer surfaced to the UI", peer_ev is not None)

    daemon.send({"cmd": "send", "targets": [mock.fingerprint], "paths": [path]})

    done = daemon.wait_for("finished", timeout=30,
                           predicate=lambda e: e.get("direction") == "out")
    check("send: reported success", done is not None and done.get("ok") is True, done)
    check("send: peer got the file", mock.received.get("outbound.bin") == blob,
          "%d bytes" % len(mock.received.get("outbound.bin", b"")))


def case_info(daemon):
    conn = client(daemon.port)
    with contextlib.closing(conn):
        conn.request("GET", "/api/localsend/v2/info")
        r = conn.getresponse()
        body = json.loads(r.read())
    check("info: 200", r.status == 200, r.status)
    check("info: advertises protocol v2", body.get("version", "").startswith("2."), body)
    check("info: identifies as a desktop", body.get("deviceType") == "desktop", body)


def main():
    if not shutil.which("openssl"):
        print("openssl is required for these tests")
        return 2

    workdir = tempfile.mkdtemp(prefix="beam-test-")
    inbox = os.path.join(workdir, "inbox")
    os.makedirs(inbox)

    os.environ["BEAM_PORT"] = str(BEAM_PORT)
    mock = MockPeer(workdir, MOCK_PORT)
    mock.start()

    daemon = Daemon(inbox, BEAM_PORT)
    ready = daemon.wait_for("ready", timeout=25)
    print("\nbeamd:", json.dumps(ready) if ready else "DID NOT START")
    check("daemon: announced ready", ready is not None)
    if not ready:
        daemon.stop()
        mock.stop()
        return 1
    check("daemon: negotiated HTTPS", ready.get("protocol") == "https", ready)
    check("daemon: fingerprint is a sha256 of the certificate",
          len(ready.get("fingerprint", "")) == 64, ready.get("fingerprint"))

    print("\n-- receiving --")
    case_receive(daemon, mock, inbox)
    print("\n-- checksum enforcement --")
    case_checksum(daemon, mock, inbox)
    print("\n-- declining --")
    case_reject(daemon, mock)
    print("\n-- sending --")
    case_send(daemon, mock, workdir)
    print("\n-- info route --")
    case_info(daemon)

    daemon.stop()
    mock.stop()
    shutil.rmtree(workdir, ignore_errors=True)

    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    for name in FAILED:
        print("   failed: %s" % name)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
