#!/usr/bin/env python3
"""
omarchy-unifi helper daemon - your network, in the bar.

Talks to the UniFi Network Integration API on a local console (UDM, UCG, UDR,
Cloud Key) or a self-hosted controller. Read-only: it lists, it never changes
anything.

Two decisions worth stating up front, because both are security decisions and
both differ from how most UniFi integrations are written.

The API key is never stored in shell.json. Omarchy's shell config is a file
people keep in a public dotfiles repository, and an API key with full read
access to your network does not belong there. It lives in its own file at mode
0600, or in the environment.

TLS uses trust on first use. UniFi consoles ship a self-signed certificate, so
every integration in the world tells you to disable verification and leaves it
there forever. Instead this records the certificate's SHA-256 the first time it
connects and refuses to talk to anything else afterwards - the same bargain SSH
makes, and a far better one than permanent blind trust.

Transport contract with QML: newline-delimited JSON.
"""

import contextlib
import hashlib
import http.client
import json
import os
import socket
import ssl
import sys
import threading
import time

DEFAULT_POLL = 20.0
STATE_DIR = os.path.join(
    os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
    "omarchy-unifi",
)
DEFAULT_KEY_FILE = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
    "omarchy", "unifi.key",
)

# The prefix moved between releases and the plural spelling still shows up in
# third-party docs, so both are tried once and the winner is remembered.
BASE_PATHS = [
    "/proxy/network/integration/v1",
    "/proxy/network/integrations/v1",
    "/v1",
]


def log(msg):
    sys.stderr.write("unifid: %s\n" % msg)
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


def read_key(path):
    """The key, from its file or the environment. Never from shell.json."""
    from_env = os.environ.get("UNIFI_API_KEY")
    if from_env:
        return from_env.strip()
    path = os.path.expanduser(path or DEFAULT_KEY_FILE)
    if not os.path.exists(path):
        return None
    try:
        mode = os.stat(path).st_mode & 0o077
        if mode:
            # Refusing is the point. A key readable by other accounts on the
            # machine is a key that should be rotated, not quietly used.
            emit("error", message="%s is readable by others. "
                                  "Run: chmod 600 %s" % (path, path))
            return None
        with open(path) as fh:
            return fh.read().strip() or None
    except OSError as exc:
        emit("error", message="Cannot read %s: %s" % (path, exc))
        return None


def pin_path(host):
    safe = "".join(c if c.isalnum() or c in ".-_" else "_" for c in host)
    return os.path.join(STATE_DIR, "%s.pin" % safe)


def load_pin(host):
    with contextlib.suppress(OSError):
        with open(pin_path(host)) as fh:
            return fh.read().strip() or None
    return None


def save_pin(host, fingerprint):
    with contextlib.suppress(OSError):
        os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
        with open(pin_path(host), "w") as fh:
            fh.write(fingerprint)


class PinMismatch(Exception):
    pass


class AuthProblem(Exception):
    """No usable API key, or one the console rejected.

    Deliberately not a PermissionError: that subclasses OSError, and the
    transport layer catches OSError to mean "this host did not answer". A key
    problem reported as an unreachable console sends people to debug their
    network instead of their key file.
    """


class Unifi:
    def __init__(self):
        self.host = ""
        self.port = 443
        self.key_file = DEFAULT_KEY_FILE
        self.site_id = ""
        self.poll = DEFAULT_POLL
        self.trust_on_first_use = True

        self.base = None
        self.running = True
        self.wake = threading.Event()

    # -- transport ---------------------------------------------------------

    def request(self, path, timeout=12):
        """One GET. Returns (status, parsed-json-or-None)."""
        key = read_key(self.key_file)
        if not key:
            raise AuthProblem(
                "No API key. Put one in %s with chmod 600, or set UNIFI_API_KEY."
                % os.path.expanduser(self.key_file or DEFAULT_KEY_FILE))

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        conn = http.client.HTTPSConnection(self.host, self.port,
                                           timeout=timeout, context=context)
        with contextlib.closing(conn):
            conn.connect()
            der = conn.sock.getpeercert(binary_form=True)
            fingerprint = hashlib.sha256(der).hexdigest() if der else None

            expected = load_pin(self.host)
            if expected and fingerprint and fingerprint != expected:
                raise PinMismatch(
                    "The certificate on %s changed. If you reinstalled the "
                    "console this is expected - clear the pin at %s. If you "
                    "did not, stop and find out why."
                    % (self.host, pin_path(self.host)))
            if not expected and fingerprint and self.trust_on_first_use:
                save_pin(self.host, fingerprint)
                emit("pinned", host=self.host, fingerprint=fingerprint)

            conn.request("GET", path, headers={
                "X-API-KEY": key,
                "Accept": "application/json",
            })
            response = conn.getresponse()
            raw = response.read()
            if response.status != 200:
                return response.status, None
            try:
                return 200, json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                return 200, None

    def resolve_base(self):
        """Find which prefix this console answers on, once."""
        if self.base:
            return self.base
        for candidate in BASE_PATHS:
            try:
                status, body = self.request(candidate + "/sites")
            except (PinMismatch, AuthProblem):
                raise
            except (OSError, ssl.SSLError, http.client.HTTPException):
                continue
            if status in (401, 403):
                raise AuthProblem("The console rejected the API key.")
            if status == 200 and body is not None:
                self.base = candidate
                return candidate
        return None

    def paged(self, path, limit=200):
        """Walk a paginated collection and return every element."""
        out = []
        offset = 0
        while True:
            joiner = "&" if "?" in path else "?"
            status, body = self.request("%s%soffset=%d&limit=%d"
                                        % (path, joiner, offset, limit))
            if status != 200 or not isinstance(body, dict):
                break
            chunk = body.get("data") or []
            out.extend(chunk)
            total = body.get("totalCount")
            offset += len(chunk)
            if not chunk or total is None or offset >= total or len(out) > 5000:
                break
        return out

    # -- shaping -----------------------------------------------------------

    def snapshot(self):
        base = self.resolve_base()
        if not base:
            emit("error", message="No UniFi API found at %s:%d. Check the host, "
                                  "the port (443 for a console, 8443 self-hosted) "
                                  "and that the Network application is running."
                                  % (self.host, self.port))
            return

        sites = self.paged(base + "/sites")
        if not sites:
            emit("error", message="The API key is valid but no sites came back.")
            return

        site = None
        if self.site_id:
            site = next((s for s in sites if s.get("id") == self.site_id), None)
        site = site or sites[0]
        site_id = site.get("id")

        devices = self.paged("%s/sites/%s/devices" % (base, site_id))
        clients = self.paged("%s/sites/%s/clients" % (base, site_id))

        rows = []
        gateway = None
        for device in devices:
            state = (device.get("state") or "").upper()
            row = {
                "id": device.get("id"),
                "name": device.get("name") or device.get("model") or "Device",
                "model": device.get("model") or "",
                "state": state,
                "online": state == "ONLINE",
                "ip": device.get("ipAddress") or "",
                "type": (device.get("features") or {}) and device.get("model") or "",
            }
            rows.append(row)
            # The gateway is the device that carries the WAN, and it is the
            # one whose statistics are worth a second request.
            roles = device.get("features") or []
            if gateway is None and (
                    "gateway" in [str(r).lower() for r in roles]
                    or str(device.get("model", "")).upper().startswith(("UDM", "UXG", "UCG", "USG"))):
                gateway = device

        uplink = {}
        if gateway and gateway.get("id"):
            status, body = self.request("%s/sites/%s/devices/%s/statistics/latest"
                                        % (base, site_id, gateway["id"]))
            if status == 200 and isinstance(body, dict):
                uplink = {
                    "cpu": body.get("cpuUtilizationPct"),
                    "memory": body.get("memoryUtilizationPct"),
                    "uptime": body.get("uptimeSec"),
                    "txRate": (body.get("uplink") or {}).get("txRateBps"),
                    "rxRate": (body.get("uplink") or {}).get("rxRateBps"),
                }

        wired = sum(1 for c in clients if (c.get("type") or "").upper() == "WIRED")
        wireless = len(clients) - wired
        online = sum(1 for r in rows if r["online"])

        rows.sort(key=lambda r: (not r["online"], r["name"].lower()))

        emit("snapshot",
             site={"id": site_id, "name": site.get("name") or "Default"},
             devices=rows,
             deviceCount=len(rows),
             devicesOnline=online,
             clientCount=len(clients),
             wired=wired,
             wireless=wireless,
             gateway=({"name": gateway.get("name"), "model": gateway.get("model")}
                      if gateway else None),
             uplink=uplink,
             at=int(time.time()))

    # -- loop --------------------------------------------------------------

    def poll_loop(self):
        while self.running:
            if self.host:
                try:
                    self.snapshot()
                except AuthProblem as exc:
                    emit("unauthorised", message=str(exc))
                except PinMismatch as exc:
                    emit("error", message=str(exc))
                except (OSError, ssl.SSLError, socket.timeout,
                        http.client.HTTPException) as exc:
                    emit("error", message="Cannot reach %s: %s" % (self.host, exc))
                except Exception as exc:                # noqa: BLE001
                    log("poll failed: %s" % exc)
                    emit("error", message=str(exc))
            self.wake.wait(max(5.0, self.poll))
            self.wake.clear()


def handle_command(unifi, msg):
    cmd = msg.get("cmd")
    if cmd == "config":
        previous = (unifi.host, unifi.port)
        unifi.host = str(msg.get("host") or "").strip()
        with contextlib.suppress(TypeError, ValueError):
            unifi.port = int(msg.get("port") or 443)
        unifi.site_id = str(msg.get("site") or "")
        unifi.key_file = str(msg.get("keyFile") or DEFAULT_KEY_FILE)
        with contextlib.suppress(TypeError, ValueError):
            unifi.poll = float(msg.get("pollSeconds") or DEFAULT_POLL)
        if (unifi.host, unifi.port) != previous:
            unifi.base = None                # re-probe against the new console
        emit("config", host=unifi.host, port=unifi.port,
             keyFile=unifi.key_file, keyPresent=read_key(unifi.key_file) is not None,
             pinned=load_pin(unifi.host) is not None if unifi.host else False)
        unifi.wake.set()
    elif cmd == "refresh":
        unifi.wake.set()
    elif cmd == "unpin":
        if unifi.host:
            with contextlib.suppress(OSError):
                os.remove(pin_path(unifi.host))
            emit("config", host=unifi.host, port=unifi.port,
                 keyFile=unifi.key_file,
                 keyPresent=read_key(unifi.key_file) is not None, pinned=False)
            unifi.wake.set()
    elif cmd == "quit":
        unifi.running = False
        unifi.wake.set()


def main():
    unifi = Unifi()
    emit("ready", keyFile=DEFAULT_KEY_FILE)
    threading.Thread(target=unifi.poll_loop, daemon=True).start()

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
            handle_command(unifi, msg)
        except Exception as exc:                        # noqa: BLE001
            log("command %r failed: %s" % (msg.get("cmd"), exc))
            emit("error", message=str(exc))
        if not unifi.running:
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
