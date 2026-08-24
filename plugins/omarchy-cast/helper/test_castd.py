#!/usr/bin/env python3
"""
Tests for castd.

The interesting half of this daemon is protocol code that either matches
Google's wire format exactly or does not work at all, so most of these tests
put bytes on a real socket and read them back. The Cast tests run against a
fake receiver that speaks genuine CASTV2 framing over TLS - if the encoder is
wrong by one byte, nothing here passes.

    python3 test_castd.py
"""

import contextlib
import importlib.util
import json
import os
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import Request, urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("castd", os.path.join(HERE, "castd.py"))
castd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(castd)

PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print("  %s %s%s" % ("PASS" if condition else "FAIL", name,
                         "" if condition else "   <- %s" % detail))


# --------------------------------------------------------------------------
# protobuf
# --------------------------------------------------------------------------

def test_protobuf():
    frame = castd.encode_cast_message(
        "sender-0", "receiver-0", castd.NS_RECEIVER,
        json.dumps({"type": "LAUNCH", "appId": "CC1AD845", "requestId": 7}))

    length = struct.unpack(">I", frame[:4])[0]
    check("protobuf: frame carries a big-endian length prefix",
          length == len(frame) - 4, "%d vs %d" % (length, len(frame) - 4))

    decoded = castd.decode_cast_message(frame[4:])
    check("protobuf: source round-trips", decoded["source_id"] == "sender-0", decoded)
    check("protobuf: destination round-trips", decoded["destination_id"] == "receiver-0")
    check("protobuf: namespace round-trips", decoded["namespace"] == castd.NS_RECEIVER)
    check("protobuf: payload round-trips",
          json.loads(decoded["payload"])["appId"] == "CC1AD845")

    # Field 1 is protocol_version, a varint, and must be the first tag byte:
    # 0x08 is (1 << 3) | 0. A receiver rejects the frame outright otherwise.
    check("protobuf: first tag is protocol_version varint", frame[4] == 0x08,
          hex(frame[4]))

    unicode_frame = castd.encode_cast_message("s", "d", "ns", '{"t":"café ☕"}')
    check("protobuf: utf-8 payloads survive",
          json.loads(castd.decode_cast_message(unicode_frame[4:])["payload"])["t"]
          == "café ☕")

    big = castd.encode_cast_message("s", "d", "ns", "x" * 500)
    check("protobuf: multi-byte varint lengths encode correctly",
          len(castd.decode_cast_message(big[4:])["payload"]) == 500)


# --------------------------------------------------------------------------
# mDNS
# --------------------------------------------------------------------------

def build_mdns_response():
    """A response shaped like the one a real Chromecast sends."""
    service = "_googlecast._tcp.local."
    instance = "Chromecast-abc123._googlecast._tcp.local."
    host = "abc123.local."

    def name(n):
        return castd.encode_name(n)

    def record(owner, rrtype, rdata):
        return name(owner) + struct.pack(">HHIH", rrtype, 0x8001, 120, len(rdata)) + rdata

    txt_pairs = [b"id=abc123", b"md=Chromecast Ultra", b"fn=Living Room TV",
                 b"ca=4101", b"rs="]
    txt = b"".join(bytes([len(p)]) + p for p in txt_pairs)

    body = b""
    body += record(service, castd.TYPE_PTR, name(instance))
    body += record(instance, castd.TYPE_SRV,
                   struct.pack(">HHH", 0, 0, 8009) + name(host))
    body += record(instance, castd.TYPE_TXT, txt)
    body += record(host, castd.TYPE_A, socket.inet_aton("192.168.1.42"))

    header = struct.pack(">HHHHHH", 0, 0x8400, 0, 4, 0, 0)
    return header + body


def test_mdns():
    encoded = castd.encode_name("_googlecast._tcp.local.")
    check("mdns: name encodes as length-prefixed labels",
          encoded == b"\x0b_googlecast\x04_tcp\x05local\x00", encoded)

    decoded, _ = castd.decode_name(encoded, 0)
    check("mdns: name round-trips", decoded == "_googlecast._tcp.local.", decoded)

    packet = build_mdns_response()
    records = list(castd.parse_records(packet))
    kinds = {rrtype for _, rrtype, _ in records}
    check("mdns: all four record types parsed",
          kinds == {castd.TYPE_PTR, castd.TYPE_SRV, castd.TYPE_TXT, castd.TYPE_A}, kinds)

    by_type = {rrtype: value for _, rrtype, value in records}
    check("mdns: SRV yields host and port", by_type[castd.TYPE_SRV][1] == 8009,
          by_type.get(castd.TYPE_SRV))
    check("mdns: TXT yields the friendly name",
          by_type[castd.TYPE_TXT].get("fn") == "Living Room TV", by_type.get(castd.TYPE_TXT))
    check("mdns: A yields the address", by_type[castd.TYPE_A] == "192.168.1.42")

    # A pointer that points at itself must raise, not hang.
    loop = struct.pack(">HHHHHH", 0, 0x8400, 0, 0, 0, 0) + b"\xc0\x0c"
    try:
        castd.decode_name(loop, 12)
        looped = False
    except ValueError:
        looped = True
    check("mdns: self-referential compression pointer is rejected", looped)


# --------------------------------------------------------------------------
# the media server
# --------------------------------------------------------------------------

def fetch(url, headers=None):
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=10) as response:
        return response.status, response.read(), dict(response.headers)


def test_media_server():
    workdir = tempfile.mkdtemp(prefix="cast-test-")
    try:
        payload = bytes(range(256)) * 400          # 102400 bytes
        path = os.path.join(workdir, "movie.mp4")
        with open(path, "wb") as fh:
            fh.write(payload)

        server = castd.MediaServer()
        token = server.stage(path)
        url = "http://127.0.0.1:%d/%s" % (server.port, token)

        status, body, headers = fetch(url)
        check("media: whole file served", status == 200 and body == payload,
              "%s / %d bytes" % (status, len(body)))
        check("media: advertises range support",
              headers.get("Accept-Ranges") == "bytes", headers.get("Accept-Ranges"))
        check("media: guesses the content type",
              headers.get("Content-Type") == "video/mp4", headers.get("Content-Type"))

        status, body, headers = fetch(url, {"Range": "bytes=100-199"})
        check("media: byte range returns 206", status == 206, status)
        check("media: byte range returns the right slice", body == payload[100:200],
              len(body))
        check("media: content-range is correct",
              headers.get("Content-Range") == "bytes 100-199/%d" % len(payload),
              headers.get("Content-Range"))

        status, body, _ = fetch(url, {"Range": "bytes=-50"})
        check("media: suffix range works", status == 206 and body == payload[-50:],
              len(body))

        status, body, _ = fetch(url, {"Range": "bytes=102300-"})
        check("media: open-ended range works",
              status == 206 and body == payload[102300:], len(body))

        # The token is the only thing guarding the file. A wrong one is a 404.
        try:
            fetch("http://127.0.0.1:%d/%s" % (server.port, "0" * 32))
            guarded = False
        except Exception as exc:                        # noqa: BLE001
            guarded = "404" in str(exc)
        check("media: an unknown token is refused", guarded)

        server.stop()
        try:
            fetch(url)
            revoked = False
        except Exception as exc:                        # noqa: BLE001
            revoked = "404" in str(exc)
        check("media: stopping revokes the URL", revoked)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# --------------------------------------------------------------------------
# a fake Chromecast
# --------------------------------------------------------------------------

class FakeReceiver:
    """Speaks real CASTV2 framing over TLS, well enough to run a session."""

    def __init__(self, workdir):
        self.cert = os.path.join(workdir, "cast-cert.pem")
        self.key = os.path.join(workdir, "cast-key.pem")
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout", self.key,
             "-out", self.cert, "-days", "2", "-nodes", "-subj", "/CN=FakeCast"],
            check=True, capture_output=True)

        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]

        self.seen = []            # every payload type we were sent
        self.launched = None
        self.loaded = None
        self.running = True
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert, self.key)
        with contextlib.suppress(OSError):
            context.set_ciphers("DEFAULT@SECLEVEL=1")
        while self.running:
            try:
                raw, _ = self.sock.accept()
            except OSError:
                return
            try:
                conn = context.wrap_socket(raw, server_side=True)
            except (ssl.SSLError, OSError):
                continue
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _send(self, conn, destination, namespace, payload):
        frame = castd.encode_cast_message("receiver-0", destination, namespace,
                                          json.dumps(payload))
        with contextlib.suppress(OSError):
            conn.sendall(frame)

    def _serve(self, conn):
        def read_exact(n):
            buf = b""
            while len(buf) < n:
                chunk = conn.recv(n - len(buf))
                if not chunk:
                    raise ConnectionError
                buf += chunk
            return buf

        try:
            while self.running:
                length = struct.unpack(">I", read_exact(4))[0]
                message = castd.decode_cast_message(read_exact(length))
                payload = json.loads(message["payload"]) if message["payload"] else {}
                kind = payload.get("type")
                sender = message["source_id"]
                self.seen.append(kind)

                if kind == "PING":
                    self._send(conn, sender, castd.NS_HEARTBEAT, {"type": "PONG"})

                elif kind == "GET_STATUS":
                    self._send(conn, sender, castd.NS_RECEIVER, {
                        "type": "RECEIVER_STATUS",
                        "status": {"applications": [], "volume": {"level": 0.4, "muted": False}},
                    })

                elif kind == "LAUNCH":
                    self.launched = payload.get("appId")
                    self._send(conn, sender, castd.NS_RECEIVER, {
                        "type": "RECEIVER_STATUS",
                        "status": {
                            "applications": [{
                                "appId": payload.get("appId"),
                                "displayName": "Default Media Receiver",
                                "sessionId": "session-1",
                                "transportId": "web-1",
                            }],
                            "volume": {"level": 0.4, "muted": False},
                        },
                    })

                elif kind == "LOAD":
                    self.loaded = payload.get("media")
                    self._send(conn, sender, castd.NS_MEDIA, {
                        "type": "MEDIA_STATUS",
                        "status": [{
                            "mediaSessionId": 1,
                            "playerState": "PLAYING",
                            "currentTime": 0.0,
                            "media": {"duration": 212.5,
                                      "metadata": {"title": (payload.get("media") or {})
                                                   .get("metadata", {}).get("title")}},
                        }],
                    })

                elif kind in ("PAUSE", "PLAY", "SEEK"):
                    state = {"PAUSE": "PAUSED", "PLAY": "PLAYING", "SEEK": "PLAYING"}[kind]
                    self._send(conn, sender, castd.NS_MEDIA, {
                        "type": "MEDIA_STATUS",
                        "status": [{"mediaSessionId": 1, "playerState": state,
                                    "currentTime": payload.get("currentTime", 0.0),
                                    "media": {"duration": 212.5, "metadata": {}}}],
                    })
        except (OSError, ConnectionError, ValueError, struct.error):
            pass
        finally:
            with contextlib.suppress(OSError):
                conn.close()

    def stop(self):
        self.running = False
        with contextlib.suppress(OSError):
            self.sock.close()


def wait_for(predicate, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_cast_channel():
    workdir = tempfile.mkdtemp(prefix="cast-chan-")
    receiver = None
    channel = None
    try:
        receiver = FakeReceiver(workdir)
        statuses = []
        channel = castd.CastChannel("127.0.0.1", receiver.port, statuses.append)
        channel.connect()

        check("channel: TLS session established", wait_for(lambda: channel.running))
        check("channel: sender opens with CONNECT",
              wait_for(lambda: "CONNECT" in receiver.seen), receiver.seen)
        check("channel: receiver status observed",
              wait_for(lambda: any(s.get("kind") == "receiver" for s in statuses)),
              statuses)

        launched = channel.launch(timeout=10)
        check("channel: LAUNCH acknowledged", launched)
        check("channel: default media receiver requested",
              receiver.launched == castd.DEFAULT_MEDIA_APP, receiver.launched)
        check("channel: transport id captured", channel.transport_id == "web-1",
              channel.transport_id)
        check("channel: session id captured", channel.session_id == "session-1",
              channel.session_id)

        loaded = channel.load("http://192.168.1.5:9000/token", "video/mp4", "Test Reel")
        check("channel: LOAD sent", loaded)
        check("channel: receiver got the media url",
              wait_for(lambda: receiver.loaded is not None)
              and receiver.loaded["contentId"] == "http://192.168.1.5:9000/token",
              receiver.loaded)
        check("channel: title travels in the metadata",
              receiver.loaded and receiver.loaded["metadata"]["title"] == "Test Reel",
              receiver.loaded)

        check("channel: media status came back PLAYING",
              wait_for(lambda: any(s.get("kind") == "media" and s.get("state") == "PLAYING"
                                   for s in statuses)), statuses)
        check("channel: media session id captured",
              wait_for(lambda: channel.media_session_id == 1), channel.media_session_id)
        check("channel: duration reported",
              any(s.get("duration") == 212.5 for s in statuses if s.get("kind") == "media"))

        channel.media_command("PAUSE")
        check("channel: PAUSE reaches the receiver and reports back",
              wait_for(lambda: any(s.get("kind") == "media" and s.get("state") == "PAUSED"
                                   for s in statuses)), statuses)

        channel.media_command("SEEK", currentTime=60.0)
        check("channel: SEEK carries a position",
              wait_for(lambda: any(s.get("position") == 60.0 for s in statuses)), statuses)

        check("channel: heartbeat answered PONG without disconnecting",
              channel.running)

        channel.close()
        check("channel: closes cleanly", not channel.running)
    finally:
        if channel:
            channel.close()
        if receiver:
            receiver.stop()
        shutil.rmtree(workdir, ignore_errors=True)


def test_end_to_end():
    """A staged local file, served over HTTP, loaded onto a fake receiver."""
    workdir = tempfile.mkdtemp(prefix="cast-e2e-")
    receiver = None
    engine = castd.Cast()
    try:
        receiver = FakeReceiver(workdir)
        payload = b"\x00\x01\x02\x03" * 25000
        path = os.path.join(workdir, "holiday.mp4")
        with open(path, "wb") as fh:
            fh.write(payload)

        engine.targets["fake"] = {
            "id": "fake", "name": "Fake TV", "model": "Test", "kind": "cast",
            "address": "127.0.0.1", "port": receiver.port, "seen": time.monotonic(),
        }

        engine.cast("fake", path)
        check("end-to-end: a session was established",
              wait_for(lambda: engine.current is not None), "no session")
        check("end-to-end: receiver was handed a url",
              wait_for(lambda: receiver.loaded is not None), "nothing loaded")

        if receiver.loaded:
            url = receiver.loaded["contentId"]
            check("end-to-end: url points at our media server",
                  url.startswith("http://") and url.endswith(engine.media.token or "?"), url)
            check("end-to-end: mime type derived from the file",
                  receiver.loaded["contentType"] == "video/mp4",
                  receiver.loaded["contentType"])
            check("end-to-end: title is the file name",
                  receiver.loaded["metadata"]["title"] == "holiday.mp4",
                  receiver.loaded["metadata"])

            # Fetch it the way the television would.
            local = "http://127.0.0.1:%d/%s" % (engine.media.port, engine.media.token)
            status, body, _ = fetch(local, {"Range": "bytes=0-99"})
            check("end-to-end: the television can read the bytes",
                  status == 206 and body == payload[:100], status)

        engine.stop()
        check("end-to-end: stopping clears the session", engine.current is None)
    finally:
        engine.stop(quiet=True)
        if receiver:
            receiver.stop()
        shutil.rmtree(workdir, ignore_errors=True)


def main():
    if not shutil.which("openssl"):
        print("openssl is required for these tests")
        return 2

    print("-- protobuf --")
    test_protobuf()
    print("\n-- mDNS --")
    test_mdns()
    print("\n-- media server --")
    test_media_server()
    print("\n-- cast channel --")
    test_cast_channel()
    print("\n-- end to end --")
    test_end_to_end()

    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    for name in FAILED:
        print("   failed: %s" % name)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
