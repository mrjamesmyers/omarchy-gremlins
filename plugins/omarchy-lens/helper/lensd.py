#!/usr/bin/env python3
"""
omarchy-lens helper daemon - the accessibility layer Omarchy does not have.

There is one accessibility plugin among the 1,099 in the registry, and it does
sticky keys. No magnifier, no colour-vision correction, no high contrast, no
cursor aids. This is that layer.

Everything here is driven through `hyprctl`, which means no new dependencies
and nothing that needs privileges:

  magnifier            cursor:zoom_factor
  colour filters       decoration:screen_shader, pointed at ../shaders/*.frag
  reduce motion        animations:enabled
  cursor size          hyprctl setcursor

Option names have moved between Hyprland releases - the zoom factor used to
live under misc: and the screen shader has been reorganised more than once - so
nothing here assumes a name. Every key is probed with `hyprctl getoption` at
startup and the working spelling is remembered. A plugin that hard-codes one
spelling works on the author's machine and silently does nothing on everybody
else's.

Transport contract with QML: newline-delimited JSON.
"""

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SHADER_DIR = os.path.join(os.path.dirname(HERE), "shaders")

STATE_DIR = os.path.join(
    os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
    "omarchy-lens",
)
STATE_FILE = os.path.join(STATE_DIR, "state.json")

# Candidate spellings, most current first.
ZOOM_KEYS = ["cursor:zoom_factor", "misc:cursor_zoom_factor"]
ZOOM_RIGID_KEYS = ["cursor:zoom_rigid", "misc:cursor_zoom_rigid"]
SHADER_KEYS = ["decoration:screen_shader", "decoration:screen_shader_path"]
ANIMATION_KEYS = ["animations:enabled"]

FILTERS = [
    "protanopia-correct", "deuteranopia-correct", "tritanopia-correct",
    "protanopia-simulate", "deuteranopia-simulate", "tritanopia-simulate",
    "high-contrast", "invert", "greyscale", "dim",
]


def log(msg):
    sys.stderr.write("lensd: %s\n" % msg)
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


def run(args, timeout=6):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (subprocess.SubprocessError, OSError) as exc:
        return 1, "", str(exc)


# --------------------------------------------------------------------------
# contrast
# --------------------------------------------------------------------------

def _channel(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb):
    r, g, b = (_channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def parse_colour(text):
    """Accept #rgb, #rrggbb, #aarrggbb, 0xRRGGBB, or 'r,g,b'."""
    if not text:
        return None
    s = str(text).strip().lower().lstrip("#")
    if s.startswith("0x"):
        s = s[2:]
    if re.fullmatch(r"[0-9a-f]{3}", s):
        return tuple(int(ch * 2, 16) for ch in s)
    if re.fullmatch(r"[0-9a-f]{6}", s):
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    if re.fullmatch(r"[0-9a-f]{8}", s):
        # Hyprland writes AARRGGBB; the alpha is not part of the contrast.
        return tuple(int(s[i:i + 2], 16) for i in (2, 4, 6))
    m = re.fullmatch(r"\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*", s)
    if m:
        vals = tuple(min(255, int(g)) for g in m.groups())
        return vals
    return None


def contrast_ratio(fg, bg):
    a, b = relative_luminance(fg), relative_luminance(bg)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def wcag_verdict(ratio, large_text=False):
    """WCAG 2.2: 4.5 for body text, 3.0 for large text; AAA is 7.0 / 4.5."""
    aa = 3.0 if large_text else 4.5
    aaa = 4.5 if large_text else 7.0
    if ratio >= aaa:
        return "AAA"
    if ratio >= aa:
        return "AA"
    if ratio >= 3.0:
        return "AA large only"
    return "fail"


# --------------------------------------------------------------------------
# the daemon
# --------------------------------------------------------------------------

class Lens:
    def __init__(self):
        self.zoom_key = None
        self.zoom_rigid_key = None
        self.shader_key = None
        self.animation_key = None
        self.hypr = shutil.which("hyprctl") is not None

        self.zoom = 1.0
        self.filter = ""
        self.animations = True
        self.cursor_size = 0
        self.running = True

    # -- capability probing -------------------------------------------------

    def option_exists(self, key):
        """`hyprctl getoption` answers for a key it knows and errors otherwise."""
        code, out, _ = run(["hyprctl", "getoption", key])
        if code != 0:
            return False
        low = out.lower()
        if "invalid" in low or "no such" in low or "unknown" in low:
            return False
        return bool(out.strip())

    def probe(self):
        if not self.hypr:
            return
        for attr, candidates in (("zoom_key", ZOOM_KEYS),
                                 ("zoom_rigid_key", ZOOM_RIGID_KEYS),
                                 ("shader_key", SHADER_KEYS),
                                 ("animation_key", ANIMATION_KEYS)):
            for key in candidates:
                if self.option_exists(key):
                    setattr(self, attr, key)
                    break

    def capabilities(self):
        return {
            "hyprctl": self.hypr,
            "magnifier": bool(self.zoom_key),
            "filters": bool(self.shader_key),
            "reduceMotion": bool(self.animation_key),
            "cursorSize": self.hypr,
            "zoomKey": self.zoom_key,
            "shaderKey": self.shader_key,
        }

    def keyword(self, key, value):
        if not (self.hypr and key):
            return False
        code, _, err = run(["hyprctl", "keyword", key, str(value)])
        if code != 0:
            log("hyprctl keyword %s %s failed: %s" % (key, value, err.strip()))
            return False
        return True

    # -- features -----------------------------------------------------------

    def shader_path(self, name):
        if not name:
            return ""
        if name not in FILTERS:
            return None
        path = os.path.join(SHADER_DIR, name + ".frag")
        return path if os.path.exists(path) else None

    def set_filter(self, name):
        name = (name or "").strip()
        path = self.shader_path(name)
        if path is None:
            emit("error", message="No such filter: %s" % name)
            return
        if not self.shader_key:
            emit("error", message="This Hyprland has no screen-shader option, "
                                  "so colour filters are unavailable.")
            return
        # Clearing takes an empty string, which hyprctl needs quoted through.
        ok = self.keyword(self.shader_key, path if path else '""')
        if ok:
            self.filter = name
            self.save()
            self.report()

    def set_zoom(self, factor):
        try:
            factor = float(factor)
        except (TypeError, ValueError):
            return
        # Below 1.0 Hyprland shrinks the screen, which is never what an
        # accessibility control means; 8x is past the point of usefulness.
        factor = max(1.0, min(8.0, factor))
        if not self.zoom_key:
            emit("error", message="This Hyprland has no cursor zoom option.")
            return
        if self.keyword(self.zoom_key, "%.3f" % factor):
            self.zoom = factor
            self.save()
            self.report()

    def set_rigid(self, rigid):
        if self.zoom_rigid_key:
            self.keyword(self.zoom_rigid_key, 1 if rigid else 0)

    def set_animations(self, enabled):
        if not self.animation_key:
            return
        if self.keyword(self.animation_key, 1 if enabled else 0):
            self.animations = bool(enabled)
            self.save()
            self.report()

    def set_cursor_size(self, size):
        try:
            size = int(size)
        except (TypeError, ValueError):
            return
        size = max(8, min(128, size))
        theme = os.environ.get("XCURSOR_THEME", "default")
        code, _, err = run(["hyprctl", "setcursor", theme, str(size)])
        if code != 0:
            emit("error", message="Could not resize the cursor: %s" % err.strip()[:120])
            return
        self.cursor_size = size
        self.save()
        self.report()

    def cursor_position(self):
        code, out, _ = run(["hyprctl", "cursorpos"])
        if code != 0:
            return None
        m = re.match(r"\s*(-?\d+)\s*,\s*(-?\d+)", out)
        return (int(m.group(1)), int(m.group(2))) if m else None

    def locate_cursor(self):
        pos = self.cursor_position()
        if pos:
            emit("cursor", x=pos[0], y=pos[1])

    def check_contrast(self, foreground, background, large=False):
        fg, bg = parse_colour(foreground), parse_colour(background)
        if not fg or not bg:
            emit("error", message="Could not read those colours.")
            return
        ratio = contrast_ratio(fg, bg)
        emit("contrast", ratio=round(ratio, 2), verdict=wcag_verdict(ratio, large),
             foreground="#%02x%02x%02x" % fg, background="#%02x%02x%02x" % bg,
             large=bool(large))

    def reset(self):
        if self.shader_key:
            self.keyword(self.shader_key, '""')
        if self.zoom_key:
            self.keyword(self.zoom_key, "1.0")
        if self.animation_key:
            self.keyword(self.animation_key, 1)
        self.zoom, self.filter, self.animations = 1.0, "", True
        self.save()
        self.report()

    # -- persistence --------------------------------------------------------

    def save(self):
        with contextlib.suppress(OSError):
            os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
            with open(STATE_FILE, "w") as fh:
                json.dump({"zoom": self.zoom, "filter": self.filter,
                           "animations": self.animations,
                           "cursorSize": self.cursor_size}, fh)

    def load(self):
        with contextlib.suppress(OSError, ValueError):
            with open(STATE_FILE) as fh:
                s = json.load(fh)
            self.zoom = float(s.get("zoom", 1.0))
            self.filter = str(s.get("filter", ""))
            self.animations = bool(s.get("animations", True))
            self.cursor_size = int(s.get("cursorSize", 0))

    def restore(self):
        """Re-apply on start. Hyprland forgets these across a restart, and an
        accessibility setting that silently lapses is worse than one that was
        never offered."""
        if self.filter:
            self.set_filter(self.filter)
        if self.zoom > 1.0:
            self.set_zoom(self.zoom)
        if not self.animations:
            self.set_animations(False)
        if self.cursor_size:
            self.set_cursor_size(self.cursor_size)

    def report(self):
        emit("state", zoom=self.zoom, filter=self.filter,
             animations=self.animations, cursorSize=self.cursor_size,
             filters=FILTERS)


def handle_command(lens, msg):
    cmd = msg.get("cmd")
    if cmd == "filter":
        lens.set_filter(msg.get("name", ""))
    elif cmd == "zoom":
        lens.set_zoom(msg.get("value", 1.0))
    elif cmd == "zoomBy":
        lens.set_zoom(lens.zoom + float(msg.get("value", 0.25)))
    elif cmd == "rigid":
        lens.set_rigid(bool(msg.get("value", True)))
    elif cmd == "animations":
        lens.set_animations(bool(msg.get("value", True)))
    elif cmd == "cursorSize":
        lens.set_cursor_size(msg.get("value", 24))
    elif cmd == "locate":
        lens.locate_cursor()
    elif cmd == "contrast":
        lens.check_contrast(msg.get("foreground"), msg.get("background"),
                            msg.get("large", False))
    elif cmd == "reset":
        lens.reset()
    elif cmd == "refresh":
        lens.report()
    elif cmd == "quit":
        lens.running = False


def main():
    lens = Lens()
    lens.probe()
    lens.load()

    caps = lens.capabilities()
    emit("ready", **caps)
    if not caps["hyprctl"]:
        emit("error", message="hyprctl is not on PATH, so nothing here can be applied.")
    lens.restore()
    lens.report()

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
            handle_command(lens, msg)
        except Exception as exc:                        # noqa: BLE001
            log("command %r failed: %s" % (msg.get("cmd"), exc))
            emit("error", message=str(exc))
        if not lens.running:
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
