#!/usr/bin/env python3
"""
omarchy-type helper daemon - Font Book for Omarchy.

No font manager exists among the 1,099 plugins in the registry, on a
distribution whose entire pitch is that it looks good. Installing a font here
means knowing that ~/.local/share/fonts exists and that fc-cache has to be run
afterwards; turning one off means writing fontconfig XML by hand.

Everything goes through fontconfig, which is already installed because the
desktop cannot render text without it:

  list      fc-list, one record per style, grouped into families here
  install   copy into ~/.local/share/fonts, then fc-cache
  disable   a rejectfont rule in ~/.config/fontconfig/conf.d
  remove    delete from the user font directory - never from /usr

Nothing here touches a system directory or asks for a password. A font manager
that needs root to preview a typeface is not a font manager.
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

USER_FONT_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "fonts")
CONF_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
    "fontconfig", "conf.d")
DISABLED_CONF = os.path.join(CONF_DIR, "70-omarchy-type-disabled.conf")

FONT_SUFFIXES = (".ttf", ".otf", ".ttc", ".otc", ".pfb", ".pcf", ".bdf", ".woff2")


def log(msg):
    sys.stderr.write("typed: %s\n" % msg)
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


def run(args, timeout=25):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (subprocess.SubprocessError, OSError) as exc:
        return 1, "", str(exc)


# --------------------------------------------------------------------------
# reading what is installed
# --------------------------------------------------------------------------

def parse_fc_list(output):
    """Parse `fc-list -f '%{file}\\t%{family}\\t%{style}\\t%{weight}\\n'`.

    Families and styles are comma-separated lists of localised aliases; the
    first entry is the one to show. Escaped commas inside a name are real and
    must not split the list, which is why this does not just call .split(",").
    """
    fonts = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        path, family, style = parts[0].strip(), parts[1], parts[2]
        weight = parts[3].strip() if len(parts) > 3 else ""
        if not path:
            continue
        fonts.append({
            "file": path,
            "family": _first_alias(family),
            "style": _first_alias(style) or "Regular",
            "weight": weight,
        })
    return fonts


def _first_alias(value):
    out, escaped = [], False
    for ch in value or "":
        if escaped:
            out.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == ",":
            break
        else:
            out.append(ch)
    return "".join(out).strip()


def list_fonts():
    if not shutil.which("fc-list"):
        return None
    code, out, _ = run(["fc-list", "-f", "%{file}\t%{family}\t%{style}\t%{weight}\n"])
    if code != 0:
        return None
    return parse_fc_list(out)


# Where a font can live and still be the user's to remove. ~/.fonts is the
# location fontconfig used before XDG and plenty of installed fonts are still
# sitting in it.
def user_font_roots():
    home = os.path.expanduser("~")
    return [os.path.realpath(USER_FONT_DIR),
            os.path.realpath(os.path.join(home, ".fonts"))]


def is_user_font(path):
    real = os.path.realpath(path)
    return any(real == root or real.startswith(root + os.sep)
               for root in user_font_roots())


def group_families(fonts, disabled):
    """One entry per family, with its styles and where it lives."""
    families = {}
    for font in fonts:
        name = font["family"]
        if not name:
            continue
        entry = families.setdefault(name, {
            "family": name, "styles": [], "files": [],
            "user": False, "disabled": name in disabled,
        })
        if font["style"] not in entry["styles"]:
            entry["styles"].append(font["style"])
        entry["files"].append(font["file"])
        if is_user_font(font["file"]):
            entry["user"] = True

    out = []
    for entry in families.values():
        entry["styles"].sort()
        entry["count"] = len(entry["files"])
        # One representative file is all a preview needs; sending every path
        # for a family with forty styles is noise.
        entry["preview"] = sorted(entry["files"])[0]
        entry.pop("files", None)
        out.append(entry)
    out.sort(key=lambda e: e["family"].lower())
    return out


# --------------------------------------------------------------------------
# turning families off
# --------------------------------------------------------------------------

def _escape_xml(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def render_disabled_conf(families):
    """A fontconfig file that rejects the named families.

    Written as one file this plugin owns entirely, so removing the plugin is
    one deletion and nothing of the user's is edited in place.
    """
    lines = ['<?xml version="1.0"?>',
             '<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">',
             "<!-- Managed by omarchy-type. Delete this file to re-enable"
             " everything. -->",
             "<fontconfig>"]
    for family in sorted(set(families)):
        lines.append("  <selectfont>")
        lines.append("    <rejectfont>")
        lines.append("      <pattern>")
        lines.append('        <patelt name="family">'
                     "<string>%s</string></patelt>" % _escape_xml(family))
        lines.append("      </pattern>")
        lines.append("    </rejectfont>")
        lines.append("  </selectfont>")
    lines.append("</fontconfig>")
    return "\n".join(lines) + "\n"


def read_disabled():
    if not os.path.exists(DISABLED_CONF):
        return set()
    try:
        with open(DISABLED_CONF) as fh:
            body = fh.read()
    except OSError:
        return set()
    return set(re.findall(r'<patelt name="family"><string>(.*?)</string></patelt>', body))


def write_disabled(families):
    try:
        os.makedirs(CONF_DIR, exist_ok=True)
        if families:
            with open(DISABLED_CONF, "w") as fh:
                fh.write(render_disabled_conf(families))
        elif os.path.exists(DISABLED_CONF):
            os.remove(DISABLED_CONF)
        return True
    except OSError as exc:
        emit("error", message="Could not write the fontconfig rule: %s" % exc)
        return False


# --------------------------------------------------------------------------
# installing
# --------------------------------------------------------------------------

def safe_font_name(path):
    name = os.path.basename(str(path or "").replace("\\", "/"))
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(". ")
    return name or "font.ttf"


def install_font(path):
    path = os.path.expanduser(str(path or ""))
    if path.startswith("file://"):
        from urllib.parse import unquote, urlparse
        path = unquote(urlparse(path).path)
    if not os.path.isfile(path):
        emit("error", message="%s is not a file." % os.path.basename(path))
        return None
    if not path.lower().endswith(FONT_SUFFIXES):
        emit("error", message="%s is not a font file." % os.path.basename(path))
        return None

    try:
        os.makedirs(USER_FONT_DIR, exist_ok=True)
        target = os.path.join(USER_FONT_DIR, safe_font_name(path))
        if os.path.abspath(target) == os.path.abspath(path):
            emit("error", message="That font is already installed.")
            return None
        stem, ext = os.path.splitext(target)
        n = 2
        while os.path.exists(target):
            target = "%s-%d%s" % (stem, n, ext)
            n += 1
        shutil.copy2(path, target)
    except OSError as exc:
        emit("error", message="Could not install that font: %s" % exc)
        return None

    refresh_cache()
    return target


def uninstall_font(family, files):
    """Delete a family's files, but only ones inside the user font directory."""
    removed, refused = [], []
    for path in files or []:
        if not is_user_font(path):
            refused.append(path)
            continue
        real = os.path.realpath(path)
        with contextlib.suppress(OSError):
            os.remove(real)
            removed.append(real)
    if refused:
        emit("error", message="%d file(s) live outside your font directory and were "
                              "left alone. System fonts belong to the package "
                              "manager." % len(refused))
    if removed:
        refresh_cache()
    return removed


def refresh_cache():
    if shutil.which("fc-cache"):
        run(["fc-cache", "-f", USER_FONT_DIR], timeout=90)


# --------------------------------------------------------------------------
# the daemon
# --------------------------------------------------------------------------

class Type:
    def __init__(self):
        self.running = True
        self.families = []

    def refresh(self):
        fonts = list_fonts()
        if fonts is None:
            emit("error", message="fontconfig is not available, so no fonts can be "
                                  "listed. Install fontconfig.")
            emit("fonts", families=[], total=0, available=False)
            return
        disabled = read_disabled()
        self.families = group_families(fonts, disabled)
        emit("fonts", families=self.families, total=len(fonts), available=True,
             userDir=USER_FONT_DIR, disabled=sorted(disabled))

    def set_enabled(self, family, enabled):
        disabled = read_disabled()
        if enabled:
            disabled.discard(family)
        else:
            disabled.add(family)
        if write_disabled(disabled):
            emit("changed", family=family, enabled=bool(enabled))
            self.refresh()

    def install(self, path):
        target = install_font(path)
        if target:
            emit("installed", path=target, name=os.path.basename(target))
            self.refresh()

    def uninstall(self, family):
        fonts = list_fonts() or []
        files = [f["file"] for f in fonts if f["family"] == family]
        removed = uninstall_font(family, files)
        if removed:
            emit("uninstalled", family=family, files=removed)
        self.refresh()


def handle_command(state, msg):
    cmd = msg.get("cmd")
    if cmd == "refresh":
        state.refresh()
    elif cmd == "enable":
        state.set_enabled(msg.get("family", ""), True)
    elif cmd == "disable":
        state.set_enabled(msg.get("family", ""), False)
    elif cmd == "install":
        threading.Thread(target=state.install, args=(msg.get("path"),), daemon=True).start()
    elif cmd == "uninstall":
        threading.Thread(target=state.uninstall, args=(msg.get("family"),), daemon=True).start()
    elif cmd == "quit":
        state.running = False


def main():
    state = Type()
    emit("ready", fontconfig=shutil.which("fc-list") is not None,
         userDir=USER_FONT_DIR)
    state.refresh()

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
            handle_command(state, msg)
        except Exception as exc:                        # noqa: BLE001
            log("command %r failed: %s" % (msg.get("cmd"), exc))
            emit("error", message=str(exc))
        if not state.running:
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
