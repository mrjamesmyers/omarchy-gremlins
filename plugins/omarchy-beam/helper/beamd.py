#!/usr/bin/env python3
"""
omarchy-beam helper daemon - a LocalSend v2.2 node.

Speaks the LocalSend protocol so that Omarchy shows up in the device list of
the LocalSend apps people already run on iOS, Android, macOS and Windows.
That is the whole trick: we are not inventing a transfer protocol and asking
the world to adopt it, we are joining one that already has clients on every
platform AirDrop refuses to talk to.

Transport contract with the QML side: newline-delimited JSON both ways.
stdin  - commands  {"cmd": "...", ...}
stdout - events    {"ev": "...", ...}
stderr - human-readable log lines, never parsed.

Every line written to stdout is a complete JSON object followed by "\n" and an
explicit flush, because the QML SplitParser on the other end splits on
newlines and a partial write would desynchronise it for the rest of the
session.

Dependencies: the Python 3 standard library, and `openssl` for one-time
certificate generation. Nothing else. No pip, no sudo, no install hooks -
Omarchy plugins are cloned, not installed, and a plugin that needs a package
manager to work is a plugin most people will never get working.
"""

import contextlib
import errno
import hashlib
import http.client
import json
import mimetypes
import os
import random
import re
import secrets
import select
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROTOCOL_VERSION = "2.1"
MULTICAST_GROUP = "224.0.0.167"
DEFAULT_PORT = 53317

# How long a peer survives without being heard from. LocalSend clients
# re-announce on a timer; three missed announcements is a reasonable "gone".
PEER_TTL = 90.0
ANNOUNCE_INTERVAL = 25.0

# How long a prepare-upload request blocks waiting for the user to hit accept.
# The sending app shows a spinner for this whole window, so it wants to be
# long enough to walk back to the desk and short enough that a forgotten
# dialog does not pin a socket open forever.
ACCEPT_TIMEOUT = 90.0

# A session that has not moved a byte in this long stops blocking new ones.
SESSION_IDLE_TIMEOUT = 90.0
# How long a finished session is remembered before being forgotten entirely.
SESSION_KEEP = 300.0

STATE_DIR = os.path.join(
    os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
    "omarchy-beam",
)

ADJECTIVES = ["Amber", "Brave", "Clever", "Dusty", "Eager", "Frosty", "Golden",
              "Hidden", "Ivory", "Jolly", "Keen", "Lucky", "Merry", "Noble",
              "Olive", "Quiet", "Rapid", "Silver", "Tidy", "Violet"]
NOUNS = ["Otter", "Falcon", "Cedar", "Harbor", "Lantern", "Meadow", "Compass",
         "Beacon", "Cobalt", "Ember", "Garnet", "Juniper", "Anchor", "Willow"]


def log(msg):
    sys.stderr.write("beamd: %s\n" % msg)
    sys.stderr.flush()


class Emitter:
    """Serialises writes to stdout so two threads cannot interleave a line."""

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
                # The shell went away. Nothing left to talk to; die quietly
                # rather than spraying tracebacks into the journal.
                os._exit(0)


emit = Emitter()


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------

def ensure_state_dir():
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)


def load_or_make_alias():
    path = os.path.join(STATE_DIR, "alias")
    if os.path.exists(path):
        with open(path) as fh:
            alias = fh.read().strip()
            if alias:
                return alias
    alias = "%s %s" % (random.choice(ADJECTIVES), random.choice(NOUNS))
    with open(path, "w") as fh:
        fh.write(alias)
    return alias


def ensure_certificate():
    """Return (certfile, keyfile, sha256-of-DER) or None if openssl is absent.

    LocalSend defaults to HTTPS with a self-signed certificate and uses the
    certificate hash as the device fingerprint, so generating one here is what
    lets a default-configured phone talk to us without the user changing a
    setting. The key never leaves this directory and is only ever presented on
    the LAN.
    """
    cert = os.path.join(STATE_DIR, "cert.pem")
    key = os.path.join(STATE_DIR, "key.pem")

    if not (os.path.exists(cert) and os.path.exists(key)):
        if not shutil.which("openssl"):
            return None
        try:
            subprocess.run(
                ["openssl", "req", "-x509", "-newkey", "rsa:2048",
                 "-keyout", key, "-out", cert, "-days", "3650", "-nodes",
                 "-subj", "/CN=LocalSend", "-sha256"],
                check=True, capture_output=True, timeout=60,
            )
            os.chmod(key, 0o600)
        except (subprocess.SubprocessError, OSError) as exc:
            log("certificate generation failed: %s" % exc)
            return None

    try:
        with open(cert, "rb") as fh:
            pem = fh.read()
        der = ssl.PEM_cert_to_DER_cert(pem.decode("ascii"))
        return cert, key, hashlib.sha256(der).hexdigest()
    except (OSError, ValueError, ssl.SSLError) as exc:
        log("certificate unreadable: %s" % exc)
        return None


# --------------------------------------------------------------------------
# network helpers
# --------------------------------------------------------------------------

def local_ipv4s():
    """Every global IPv4 on this host, best effort.

    Used for two things: joining the multicast group on each interface (a
    laptop on wifi and a dock at once is the common case, and joining only the
    default route misses half the LAN), and telling peers where to reach us.
    """
    found = []

    if shutil.which("ip"):
        try:
            out = subprocess.run(["ip", "-4", "-o", "addr", "show", "scope", "global"],
                                 capture_output=True, text=True, timeout=5).stdout
            for line in out.splitlines():
                m = re.search(r"\binet\s+(\d+\.\d+\.\d+\.\d+)", line)
                if m:
                    found.append(m.group(1))
        except (subprocess.SubprocessError, OSError):
            pass

    if not found:
        # No iproute2, or it told us nothing. Ask the routing table which
        # source address it would pick for an off-link destination. Connecting
        # a UDP socket only sets the route, so this sends no packets.
        for destination in ("8.8.8.8", "1.1.1.1"):
            with contextlib.suppress(OSError):
                probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                with contextlib.closing(probe):
                    probe.connect((destination, 9))
                    found.append(probe.getsockname()[0])
                    break

    seen, uniq = set(), []
    for ip in found:
        if ip not in seen and not ip.startswith("127."):
            seen.add(ip)
            uniq.append(ip)
    return uniq


def safe_filename(name):
    """Reduce a peer-supplied filename to a single harmless path component.

    The name arrives from another device over the network and lands in a
    directory full of the user's files, so it gets no say in where it goes:
    directory separators, parent references, and leading dots are all removed
    rather than escaped.
    """
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = name.replace("\x00", "")
    name = re.sub(r"^\.+", "", name).strip()
    name = re.sub(r'[\x00-\x1f<>:"|?*]', "_", name)
    if not name or name in (".", ".."):
        name = "beam-%s" % secrets.token_hex(4)
    return name[:200]


def unique_path(directory, name):
    """Never overwrite. 'photo.jpg' collides into 'photo (2).jpg'."""
    candidate = os.path.join(directory, name)
    if not os.path.exists(candidate):
        return candidate
    stem, ext = os.path.splitext(name)
    for n in range(2, 10000):
        candidate = os.path.join(directory, "%s (%d)%s" % (stem, n, ext))
        if not os.path.exists(candidate):
            return candidate
    return os.path.join(directory, "%s-%s%s" % (stem, secrets.token_hex(4), ext))


# --------------------------------------------------------------------------
# daemon state
# --------------------------------------------------------------------------

class Session:
    """One inbound transfer, from prepare-upload through to the last byte."""

    def __init__(self, session_id, sender, files):
        self.id = session_id
        self.sender = sender
        self.files = files                 # file id -> metadata dict
        self.tokens = {}                   # file id -> token
        self.decision = threading.Event()
        self.accepted = False
        self.destination = None
        self.saved = []
        self.received = set()
        self.cancelled = False
        self.closed = False
        self.created = time.monotonic()
        self.last_activity = self.created

    def touch(self):
        self.last_activity = time.monotonic()

    def close(self):
        self.closed = True
        self.touch()


class Beam:
    def __init__(self):
        ensure_state_dir()

        self.alias = load_or_make_alias()
        # BEAM_PORT exists for two reasons: the test suite needs to run a
        # node without fighting a real LocalSend for 53317, and so does
        # anyone whose network already has something on that port.
        try:
            self.port = int(os.environ.get("BEAM_PORT") or DEFAULT_PORT)
        except ValueError:
            self.port = DEFAULT_PORT
        self.download_dir = os.path.expanduser("~/Downloads")
        self.auto_accept = False
        self.pin = None
        self.quiet = False          # "invisible": stay off the multicast group

        material = ensure_certificate()
        if material:
            self.certfile, self.keyfile, self.fingerprint = material
            self.protocol = "https"
        else:
            self.certfile = self.keyfile = None
            self.fingerprint = secrets.token_hex(32)
            self.protocol = "http"
            log("no certificate available - falling back to plaintext HTTP")

        self.peers = {}                    # fingerprint -> peer dict
        self.peers_lock = threading.Lock()
        self.sessions = {}                 # session id -> Session
        self.sessions_lock = threading.Lock()

        self.httpd = None
        self.mcast = None
        self.running = True

    # -- identity ----------------------------------------------------------

    def info(self, announce=None):
        body = {
            "alias": self.alias,
            "version": PROTOCOL_VERSION,
            "deviceModel": "Omarchy",
            "deviceType": "desktop",
            "fingerprint": self.fingerprint,
            "port": self.port,
            "protocol": self.protocol,
            "download": False,
        }
        if announce is not None:
            body["announce"] = announce
        return body

    # -- peers -------------------------------------------------------------

    def remember_peer(self, data, address):
        fp = data.get("fingerprint")
        if not fp or fp == self.fingerprint:
            return None                    # ourselves, or unidentifiable

        peer = {
            "fingerprint": fp,
            "alias": data.get("alias") or "Unknown device",
            "deviceModel": data.get("deviceModel"),
            "deviceType": data.get("deviceType") or "desktop",
            "protocol": data.get("protocol") or "http",
            "port": int(data.get("port") or DEFAULT_PORT),
            "address": address,
            "seen": time.monotonic(),
        }

        with self.peers_lock:
            previous = self.peers.get(fp)
            self.peers[fp] = peer
            # Only surface a peer to the UI when something the user can see
            # actually changed, otherwise a 25-second announce cycle becomes a
            # 25-second stream of redundant list rebuilds.
            changed = (
                previous is None
                or previous["alias"] != peer["alias"]
                or previous["address"] != peer["address"]
                or previous["port"] != peer["port"]
                or previous["protocol"] != peer["protocol"]
            )

        if changed:
            emit("peer", device={k: peer[k] for k in
                                 ("fingerprint", "alias", "deviceModel",
                                  "deviceType", "protocol", "port", "address")})
        return peer

    def expire_peers(self):
        now = time.monotonic()
        with self.peers_lock:
            dead = [fp for fp, p in self.peers.items() if now - p["seen"] > PEER_TTL]
            for fp in dead:
                del self.peers[fp]
        for fp in dead:
            emit("peer-gone", fingerprint=fp)

    def peer(self, fingerprint):
        with self.peers_lock:
            p = self.peers.get(fingerprint)
            return dict(p) if p else None

    # -- outbound HTTP -----------------------------------------------------

    def connection(self, host, port, protocol, timeout=15):
        if protocol == "https":
            # Peers are self-signed by design - the protocol pins identity on
            # the certificate fingerprint, not on a CA chain, so chain
            # verification here would reject every legitimate device.
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
        return http.client.HTTPConnection(host, port, timeout=timeout)

    # -- discovery ---------------------------------------------------------

    def open_multicast(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # SO_REUSEPORT lets us share 53317 with a LocalSend app running on the
        # same machine instead of one of them failing to start. Not present on
        # every kernel, so it is best effort.
        with contextlib.suppress(AttributeError, OSError):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

        try:
            sock.bind(("", self.port))
        except OSError as exc:
            log("cannot bind UDP %d: %s" % (self.port, exc))
            emit("error", message="UDP port %d is in use; discovery is off." % self.port)
            sock.close()
            return None

        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)

        group = socket.inet_aton(MULTICAST_GROUP)
        joined = 0
        for ip in local_ipv4s() or ["0.0.0.0"]:
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                                group + socket.inet_aton(ip))
                joined += 1
            except OSError as exc:
                if exc.errno not in (errno.EADDRINUSE, errno.EADDRNOTAVAIL):
                    log("multicast join on %s failed: %s" % (ip, exc))
        if not joined:
            with contextlib.suppress(OSError):
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                                group + socket.inet_aton("0.0.0.0"))
        return sock

    def announce(self, announce_flag=True):
        if self.quiet or not self.mcast:
            return
        payload = json.dumps(self.info(announce=announce_flag)).encode()
        for ip in local_ipv4s() or ["0.0.0.0"]:
            with contextlib.suppress(OSError):
                self.mcast.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                                      socket.inet_aton(ip))
                self.mcast.sendto(payload, (MULTICAST_GROUP, self.port))

    def register_with(self, peer):
        """Answer someone else's announcement over HTTP, per section 3.1."""
        try:
            conn = self.connection(peer["address"], peer["port"], peer["protocol"], timeout=8)
            with contextlib.closing(conn):
                body = json.dumps(self.info()).encode()
                conn.request("POST", "/api/localsend/v2/register", body=body,
                             headers={"Content-Type": "application/json"})
                conn.getresponse().read()
        except (OSError, http.client.HTTPException, ssl.SSLError):
            # Perfectly normal: the peer may only speak the UDP fallback, or
            # may have gone away between announcing and our reply.
            pass

    def multicast_loop(self):
        while self.running:
            if not self.mcast:
                time.sleep(2.0)
                continue
            try:
                ready, _, _ = select.select([self.mcast], [], [], 1.0)
                if not ready:
                    continue
                raw, addr = self.mcast.recvfrom(65535)
            except (OSError, ValueError):
                continue

            try:
                data = json.loads(raw.decode("utf-8", "replace"))
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(data, dict):
                continue

            peer = self.remember_peer(data, addr[0])
            if peer and data.get("announce"):
                # They are asking who is out here. Reply directly, and also put
                # a non-announcing packet back on the group for clients that
                # only listen on UDP.
                threading.Thread(target=self.register_with, args=(peer,),
                                 daemon=True).start()
                self.announce(announce_flag=False)

    def announce_loop(self):
        while self.running:
            self.announce(announce_flag=True)
            self.expire_peers()
            self.prune_sessions()
            # Jitter so a room full of machines that booted together does not
            # synchronise into a thundering herd every 25 seconds.
            time.sleep(ANNOUNCE_INTERVAL + random.uniform(-3.0, 3.0))

    # -- inbound: the HTTP server -----------------------------------------

    def active_inbound(self):
        """The session, if any, that should make a second sender wait.

        A session stops blocking the moment it is closed - finished, declined,
        cancelled or failed - and also once it has simply gone quiet. Without
        the idle rule a sender that walks out of wifi mid-transfer wedges
        every future transfer until the shell restarts, which is a far worse
        failure than two senders overlapping.
        """
        now = time.monotonic()
        with self.sessions_lock:
            for s in self.sessions.values():
                if s.closed or s.cancelled or not s.accepted:
                    continue
                if len(s.received) >= len(s.files):
                    continue
                if now - s.last_activity > SESSION_IDLE_TIMEOUT:
                    continue
                return s
        return None

    def prune_sessions(self):
        now = time.monotonic()
        with self.sessions_lock:
            stale = [sid for sid, s in self.sessions.items()
                     if (s.closed or s.cancelled)
                     and now - s.last_activity > SESSION_KEEP]
            for sid in stale:
                del self.sessions[sid]

    def start_session(self, sender, files):
        session = Session(uuid.uuid4().hex, sender, files)
        with self.sessions_lock:
            self.sessions[session.id] = session
        return session

    def decide(self, session_id, accepted, destination=None):
        with self.sessions_lock:
            session = self.sessions.get(session_id)
        if not session:
            return False
        session.accepted = bool(accepted)
        if destination:
            session.destination = destination
        if not session.accepted:
            session.close()
        session.touch()
        session.decision.set()
        return True

    def cancel_session(self, session_id):
        with self.sessions_lock:
            session = self.sessions.get(session_id)
        if not session:
            return False
        session.cancelled = True
        session.accepted = False
        session.close()
        session.decision.set()
        emit("finished", sessionId=session_id, direction="in", ok=False,
             reason="cancelled", saved=session.saved)
        return True

    def serve(self):
        beam = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "LocalSend"
            sys_version = ""

            def log_message(self, fmt, *args):        # noqa: A003 - base API
                pass

            # -- helpers ---------------------------------------------------

            def _query(self):
                if "?" not in self.path:
                    return {}
                out = {}
                for pair in self.path.split("?", 1)[1].split("&"):
                    if not pair:
                        continue
                    k, _, v = pair.partition("=")
                    from urllib.parse import unquote_plus
                    out[unquote_plus(k)] = unquote_plus(v)
                return out

            def _route(self):
                return self.path.split("?", 1)[0].rstrip("/")

            def _json_body(self):
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > 32 * 1024 * 1024:
                    return None
                try:
                    return json.loads(self.rfile.read(length).decode("utf-8", "replace"))
                except ValueError:
                    return None

            def _reply(self, code, payload=None):
                body = b"" if payload is None else json.dumps(payload).encode()
                self.send_response(code)
                if body:
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    with contextlib.suppress(OSError):
                        self.wfile.write(body)

            # -- routes ----------------------------------------------------

            def do_GET(self):                          # noqa: N802 - base API
                route = self._route()
                if route in ("/api/localsend/v2/info", "/api/localsend/v1/info"):
                    self._reply(200, beam.info())
                else:
                    self._reply(404)

            def do_POST(self):                         # noqa: N802 - base API
                route = self._route()
                if route == "/api/localsend/v2/register":
                    self._register()
                elif route == "/api/localsend/v2/prepare-upload":
                    self._prepare_upload()
                elif route == "/api/localsend/v2/upload":
                    self._upload()
                elif route == "/api/localsend/v2/cancel":
                    self._cancel()
                else:
                    self._reply(404)

            def _register(self):
                data = self._json_body()
                if not isinstance(data, dict):
                    return self._reply(400)
                beam.remember_peer(data, self.client_address[0])
                self._reply(200, beam.info())

            def _prepare_upload(self):
                data = self._json_body()
                if not isinstance(data, dict):
                    return self._reply(400)

                if beam.pin and self._query().get("pin") != str(beam.pin):
                    return self._reply(401)

                sender = data.get("info") or {}
                raw_files = data.get("files") or {}
                if not isinstance(raw_files, dict) or not raw_files:
                    # 204 means "nothing to do", which is exactly right for a
                    # request that carried no files rather than an error.
                    return self._reply(204)

                if beam.active_inbound():
                    return self._reply(409)

                beam.remember_peer(sender, self.client_address[0])

                files = {}
                for fid, meta in raw_files.items():
                    if not isinstance(meta, dict):
                        continue
                    files[str(fid)] = {
                        "id": str(fid),
                        "fileName": safe_filename(meta.get("fileName")),
                        "size": int(meta.get("size") or 0),
                        "fileType": meta.get("fileType") or "application/octet-stream",
                        "sha256": meta.get("sha256"),
                    }
                if not files:
                    return self._reply(400)

                session = beam.start_session(sender, files)
                total = sum(f["size"] for f in files.values())

                emit("incoming",
                     sessionId=session.id,
                     sender={"alias": sender.get("alias") or "Unknown device",
                           "deviceType": sender.get("deviceType") or "desktop",
                           "deviceModel": sender.get("deviceModel"),
                           "fingerprint": sender.get("fingerprint"),
                           "address": self.client_address[0]},
                     files=list(files.values()),
                     totalSize=total,
                     autoAccepted=beam.auto_accept)

                if beam.auto_accept:
                    beam.decide(session.id, True)

                if not session.decision.wait(ACCEPT_TIMEOUT):
                    session.close()
                    emit("finished", sessionId=session.id, direction="in",
                         ok=False, reason="timeout", saved=[])
                    return self._reply(403)

                if not session.accepted:
                    return self._reply(403)

                destination = session.destination or beam.download_dir
                try:
                    os.makedirs(destination, exist_ok=True)
                except OSError as exc:
                    emit("error", sessionId=session.id,
                         message="Cannot write to %s: %s" % (destination, exc))
                    return self._reply(500)
                session.destination = destination

                for fid in files:
                    session.tokens[fid] = secrets.token_hex(16)
                self._reply(200, {"sessionId": session.id, "files": dict(session.tokens)})

            def _upload(self):
                q = self._query()
                sid, fid, token = q.get("sessionId"), q.get("fileId"), q.get("token")
                if not (sid and fid and token):
                    return self._reply(400)

                with beam.sessions_lock:
                    session = beam.sessions.get(sid)
                if not session or not session.accepted:
                    return self._reply(403)
                if session.cancelled:
                    return self._reply(409)
                if session.tokens.get(fid) != token:
                    return self._reply(403)

                meta = session.files.get(fid)
                if not meta:
                    return self._reply(400)

                path = unique_path(session.destination, meta["fileName"])
                declared = int(self.headers.get("Content-Length") or meta["size"] or 0)
                digest = hashlib.sha256()
                written = 0
                last_emit = 0.0

                try:
                    with open(path, "wb") as out:
                        remaining = declared
                        while remaining > 0:
                            chunk = self.rfile.read(min(256 * 1024, remaining))
                            if not chunk:
                                break
                            out.write(chunk)
                            digest.update(chunk)
                            written += len(chunk)
                            remaining -= len(chunk)

                            now = time.monotonic()
                            if now - last_emit > 0.12:
                                last_emit = now
                                session.touch()
                                emit("progress", sessionId=sid, direction="in",
                                     fileName=meta["fileName"], bytes=written,
                                     total=declared,
                                     done=len(session.received), count=len(session.files))
                except OSError as exc:
                    with contextlib.suppress(OSError):
                        os.remove(path)
                    session.close()
                    emit("error", sessionId=sid, message="Write failed: %s" % exc)
                    emit("finished", sessionId=sid, direction="in", ok=False,
                         reason="write-failed", saved=list(session.saved))
                    return self._reply(500)

                if written < declared:
                    with contextlib.suppress(OSError):
                        os.remove(path)
                    session.close()
                    emit("finished", sessionId=sid, direction="in", ok=False,
                         reason="truncated", saved=list(session.saved))
                    return self._reply(500)

                expected = meta.get("sha256")
                if expected and digest.hexdigest().lower() != str(expected).lower():
                    with contextlib.suppress(OSError):
                        os.remove(path)
                    session.close()
                    emit("error", sessionId=sid,
                         message="%s failed its checksum and was discarded." % meta["fileName"])
                    emit("finished", sessionId=sid, direction="in", ok=False,
                         reason="checksum", saved=list(session.saved))
                    return self._reply(422)

                session.received.add(fid)
                session.saved.append(path)
                emit("progress", sessionId=sid, direction="in",
                     fileName=meta["fileName"], bytes=written, total=declared,
                     done=len(session.received), count=len(session.files))
                self._reply(200)

                if len(session.received) >= len(session.files):
                    session.close()
                    emit("finished", sessionId=sid, direction="in", ok=True,
                         saved=list(session.saved))

            def _cancel(self):
                sid = self._query().get("sessionId")
                if sid:
                    beam.cancel_session(sid)
                self._reply(200)

        try:
            httpd = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        except OSError as exc:
            emit("error", message="Cannot listen on TCP %d: %s" % (self.port, exc))
            return None

        httpd.daemon_threads = True
        if self.protocol == "https":
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(self.certfile, self.keyfile)
            httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)

        self.httpd = httpd
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.5},
                         daemon=True).start()
        return httpd

    # -- outbound: sending -------------------------------------------------

    def send(self, fingerprints, paths):
        """Push files to one or more peers. Runs on its own thread per peer."""
        entries = []
        for path in paths:
            path = os.path.expanduser(path)
            if path.startswith("file://"):
                from urllib.parse import unquote, urlparse
                path = unquote(urlparse(path).path)
            if os.path.isdir(path):
                emit("error", message="%s is a folder; zip it first."
                     % os.path.basename(path))
                continue
            if not os.path.isfile(path):
                emit("error", message="%s no longer exists." % os.path.basename(path))
                continue
            entries.append(path)

        if not entries:
            return

        for fp in fingerprints:
            peer = self.peer(fp)
            if not peer:
                emit("error", message="That device is no longer on the network.")
                continue
            threading.Thread(target=self._send_to, args=(peer, list(entries)),
                             daemon=True).start()

    def _send_to(self, peer, paths):
        files, order = {}, []
        for path in paths:
            fid = uuid.uuid4().hex
            guessed = mimetypes.guess_type(path)[0] or "application/octet-stream"
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            files[fid] = {
                "id": fid,
                "fileName": os.path.basename(path),
                "size": size,
                "fileType": guessed,
            }
            order.append((fid, path, size))

        if not order:
            return

        label = peer["alias"]
        local_id = uuid.uuid4().hex
        emit("outgoing", sessionId=local_id, to=label, count=len(order),
             totalSize=sum(s for _, _, s in order))

        try:
            conn = self.connection(peer["address"], peer["port"], peer["protocol"], timeout=20)
            with contextlib.closing(conn):
                body = json.dumps({"info": self.info(), "files": files}).encode()
                conn.request("POST", "/api/localsend/v2/prepare-upload", body=body,
                             headers={"Content-Type": "application/json"})
                response = conn.getresponse()
                raw = response.read()
                status = response.status
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            emit("finished", sessionId=local_id, direction="out", ok=False,
                 reason="unreachable", message="Could not reach %s: %s" % (label, exc))
            return

        if status == 204:
            emit("finished", sessionId=local_id, direction="out", ok=True, saved=[])
            return
        if status == 403:
            emit("finished", sessionId=local_id, direction="out", ok=False,
                 reason="rejected", message="%s declined." % label)
            return
        if status == 401:
            emit("finished", sessionId=local_id, direction="out", ok=False,
                 reason="pin", message="%s wants a PIN." % label)
            return
        if status == 409:
            emit("finished", sessionId=local_id, direction="out", ok=False,
                 reason="busy", message="%s is busy with another transfer." % label)
            return
        if status != 200:
            emit("finished", sessionId=local_id, direction="out", ok=False,
                 reason="error", message="%s returned HTTP %d." % (label, status))
            return

        try:
            prepared = json.loads(raw.decode("utf-8", "replace"))
            remote_session = prepared["sessionId"]
            tokens = prepared["files"]
        except (ValueError, KeyError):
            emit("finished", sessionId=local_id, direction="out", ok=False,
                 reason="error", message="%s sent a malformed reply." % label)
            return

        sent = 0
        for fid, path, size in order:
            token = tokens.get(fid)
            if not token:
                # The receiver is allowed to accept only some of the files.
                continue
            if not self._send_one(peer, remote_session, fid, token, path, size,
                                  local_id, files[fid]["fileName"], sent, len(order)):
                emit("finished", sessionId=local_id, direction="out", ok=False,
                     reason="error", message="Transfer to %s failed." % label)
                return
            sent += 1

        emit("finished", sessionId=local_id, direction="out", ok=True, count=sent)

    def _send_one(self, peer, session_id, fid, token, path, size,
                  local_id, name, index, total_files):
        from urllib.parse import urlencode
        query = urlencode({"sessionId": session_id, "fileId": fid, "token": token})
        url = "/api/localsend/v2/upload?" + query

        class Reader:
            """Wraps the file so every read reports progress upward.

            http.client will iterate a file-like body in chunks when given an
            explicit Content-Length, so this streams straight off disk and a
            4 GB video never lands in RAM.
            """

            def __init__(self, fh):
                self.fh = fh
                self.sent = 0
                self.last = 0.0

            def read(self, amount=-1):
                chunk = self.fh.read(64 * 1024 if amount is None or amount < 0
                                     else min(amount, 256 * 1024))
                if chunk:
                    self.sent += len(chunk)
                    now = time.monotonic()
                    if now - self.last > 0.12:
                        self.last = now
                        emit("progress", sessionId=local_id, direction="out",
                             fileName=name, bytes=self.sent, total=size,
                             done=index, count=total_files)
                return chunk

        try:
            conn = self.connection(peer["address"], peer["port"], peer["protocol"], timeout=None)
            with contextlib.closing(conn), open(path, "rb") as fh:
                conn.request("POST", url, body=Reader(fh), headers={
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(size),
                })
                response = conn.getresponse()
                response.read()
                ok = response.status in (200, 204)
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            log("upload of %s failed: %s" % (name, exc))
            return False

        if ok:
            emit("progress", sessionId=local_id, direction="out", fileName=name,
                 bytes=size, total=size, done=index + 1, count=total_files)
        return ok


# --------------------------------------------------------------------------
# command loop
# --------------------------------------------------------------------------

def handle_command(beam, msg):
    cmd = msg.get("cmd")

    if cmd == "config":
        if msg.get("alias"):
            beam.alias = str(msg["alias"])[:64]
            with contextlib.suppress(OSError):
                with open(os.path.join(STATE_DIR, "alias"), "w") as fh:
                    fh.write(beam.alias)
        if msg.get("downloadDir"):
            beam.download_dir = os.path.expanduser(str(msg["downloadDir"]))
        if "autoAccept" in msg:
            beam.auto_accept = bool(msg["autoAccept"])
        if "pin" in msg:
            pin = str(msg["pin"] or "").strip()
            beam.pin = pin or None
        if "quiet" in msg:
            was = beam.quiet
            beam.quiet = bool(msg["quiet"])
            if was and not beam.quiet:
                beam.announce(True)
        emit("config", alias=beam.alias, downloadDir=beam.download_dir,
             autoAccept=beam.auto_accept, pinSet=bool(beam.pin), quiet=beam.quiet)

    elif cmd == "scan":
        beam.announce(True)
        beam.expire_peers()
        with beam.peers_lock:
            peers = [dict(p) for p in beam.peers.values()]
        for p in peers:
            p.pop("seen", None)
            emit("peer", device=p)

    elif cmd == "send":
        beam.send(msg.get("targets") or [], msg.get("paths") or [])

    elif cmd == "accept":
        beam.decide(msg.get("sessionId"), True, msg.get("destination"))

    elif cmd == "reject":
        beam.decide(msg.get("sessionId"), False)

    elif cmd == "cancel":
        beam.cancel_session(msg.get("sessionId"))

    elif cmd == "quit":
        beam.running = False


def main():
    beam = Beam()

    if beam.serve() is None:
        # Without a listening socket we can still send, but we are invisible.
        emit("error", message="Beam could not open port %d. Receiving is off."
             % beam.port)

    beam.mcast = beam.open_multicast()
    threading.Thread(target=beam.multicast_loop, daemon=True).start()
    threading.Thread(target=beam.announce_loop, daemon=True).start()

    emit("ready", alias=beam.alias, fingerprint=beam.fingerprint, port=beam.port,
         protocol=beam.protocol, addresses=local_ipv4s(),
         downloadDir=beam.download_dir)

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
            handle_command(beam, msg)
        except Exception as exc:                       # noqa: BLE001
            # One malformed command must never take the daemon down; the shell
            # would show a device list frozen at whatever it last knew.
            log("command %r failed: %s" % (msg.get("cmd"), exc))
            emit("error", message=str(exc))
        if not beam.running:
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
