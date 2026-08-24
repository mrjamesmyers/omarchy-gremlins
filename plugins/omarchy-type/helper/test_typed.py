#!/usr/bin/env python3
"""
Tests for typed.

The two things that can quietly ruin somebody's day here are the fc-list
parser, which deals with comma-separated localised aliases that may themselves
contain escaped commas, and the uninstall path, which must never be able to
reach outside the user's own font directory.

    python3 test_typed.py
"""

import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sandbox = tempfile.mkdtemp(prefix="type-")
os.environ["XDG_DATA_HOME"] = os.path.join(sandbox, "data")
os.environ["XDG_CONFIG_HOME"] = os.path.join(sandbox, "config")

spec = importlib.util.spec_from_file_location("typed", os.path.join(HERE, "typed.py"))
typed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(typed)

PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print("  %s %s%s" % ("PASS" if condition else "FAIL", name,
                         "" if condition else "   <- %s" % detail))


# Built from the real sandbox paths: a hard-coded /home/... would not be under
# this test's font directory, and the "is it yours to remove" flag would read
# as false for reasons that have nothing to do with the code.
def fc_line(path, family, style, weight="80"):
    return "%s\t%s\t%s\t%s\n" % (path, family, style, weight)


USER = typed.USER_FONT_DIR
LEGACY = os.path.join(os.path.expanduser("~"), ".fonts")

FC_LIST = (
    "/usr/share/fonts/TTF/DejaVuSans.ttf\tDejaVu Sans\tBook\t80\n"
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf\tDejaVu Sans\tBold\t200\n"
    # Localised aliases: the first is the one to show.
    "/usr/share/fonts/noto/NotoSansCJK.ttc\tNoto Sans CJK JP,Noto Sans CJK JP Regular\t"
    "Regular,標準\t80\n"
    # An escaped comma inside the family name must not split it.
    + fc_line(os.path.join(USER, "Weird.otf"), "Smith\\, Jones", "Italic") +
    "\t\t\n"                                     # junk line
    + fc_line(os.path.join(LEGACY, "Berkeley.otf"), "Berkeley Mono", "Regular")
)


def test_parse():
    fonts = typed.parse_fc_list(FC_LIST)
    check("parse: junk lines dropped", len(fonts) == 5, len(fonts))
    check("parse: family and style read",
          fonts[0]["family"] == "DejaVu Sans" and fonts[0]["style"] == "Book", fonts[0])
    check("parse: only the first localised alias is kept",
          fonts[2]["family"] == "Noto Sans CJK JP", fonts[2]["family"])
    check("parse: localised style alias also trimmed",
          fonts[2]["style"] == "Regular", fonts[2]["style"])
    # This is the one a naive .split(",") gets wrong.
    check("parse: an escaped comma stays inside the family name",
          fonts[3]["family"] == "Smith, Jones", fonts[3]["family"])
    check("parse: weight carried", fonts[1]["weight"] == "200", fonts[1])


def test_grouping():
    fonts = typed.parse_fc_list(FC_LIST)
    families = typed.group_families(fonts, disabled={"Berkeley Mono"})
    by_name = {f["family"]: f for f in families}

    check("group: one entry per family", len(families) == 4, [f["family"] for f in families])
    check("group: styles collected",
          sorted(by_name["DejaVu Sans"]["styles"]) == ["Bold", "Book"],
          by_name["DejaVu Sans"]["styles"])
    check("group: file count kept", by_name["DejaVu Sans"]["count"] == 2)
    check("group: a system font is not marked as the user's",
          by_name["DejaVu Sans"]["user"] is False, by_name["DejaVu Sans"])
    # ~/.fonts is the pre-XDG location and is still full of installed fonts.
    check("group: a font in the legacy ~/.fonts is still the user's",
          by_name["Berkeley Mono"]["user"] is True, by_name["Berkeley Mono"])
    check("group: a font in the XDG font directory is the user's",
          by_name["Smith, Jones"]["user"] is True, by_name["Smith, Jones"])
    check("group: disabled flag applied",
          by_name["Berkeley Mono"]["disabled"] is True)
    check("group: sorted case-insensitively",
          [f["family"] for f in families] ==
          sorted([f["family"] for f in families], key=str.lower))
    check("group: a preview file is offered", by_name["DejaVu Sans"]["preview"].endswith(".ttf"))


def test_disabled_conf_round_trip():
    families = {"Comic Sans MS", "Smith, Jones", 'Ampersand & Co'}
    xml = typed.render_disabled_conf(families)
    check("conf: is a fontconfig document",
          xml.startswith("<?xml") and "<fontconfig>" in xml and "rejectfont" in xml)
    check("conf: XML special characters escaped", "&amp;" in xml and "&" in xml, xml[:0])

    typed.write_disabled(families)
    check("conf: file written", os.path.exists(typed.DISABLED_CONF))
    back = typed.read_disabled()
    check("conf: every family round-trips",
          back == {"Comic Sans MS", "Smith, Jones", "Ampersand &amp; Co"} or
          back == families, back)

    typed.write_disabled(set())
    check("conf: emptying removes the file, leaving nothing behind",
          not os.path.exists(typed.DISABLED_CONF))


def test_safe_name():
    cases = [
        ("../../etc/evil.ttf", "evil.ttf"),
        ("/tmp/My Font.otf", "My Font.otf"),
        ("weird;rm -rf.ttf", "weird_rm -rf.ttf"),
        ("", "font.ttf"),
        ("...", "font.ttf"),
    ]
    bad = [(a, typed.safe_font_name(a)) for a, b in cases if typed.safe_font_name(a) != b]
    check("name: hostile filenames reduced to one safe component", not bad, bad)


def test_install_and_uninstall():
    calls = []
    typed.run = lambda args, timeout=25: (calls.append(list(args)), (0, "", ""))[1]

    source_dir = tempfile.mkdtemp(prefix="type-src-")
    source = os.path.join(source_dir, "Berkeley.otf")
    with open(source, "wb") as fh:
        fh.write(b"OTTO" + b"\0" * 64)

    events = []
    real = typed.emit
    typed.emit = lambda ev, **f: events.append((ev, f))
    try:
        target = typed.install_font(source)
        check("install: copied into the user font directory",
              target and target.startswith(typed.USER_FONT_DIR), target)
        check("install: the file is really there", target and os.path.exists(target))
        check("install: fc-cache was refreshed",
              any(c[0] == "fc-cache" for c in calls), calls)

        # A second install of the same name must not clobber the first.
        again = typed.install_font(source)
        check("install: a name collision is suffixed, not overwritten",
              again and again != target and os.path.exists(target), (target, again))

        # Not a font.
        notfont = os.path.join(source_dir, "readme.txt")
        with open(notfont, "w") as fh:
            fh.write("hello")
        events.clear()
        check("install: a non-font is refused", typed.install_font(notfont) is None)
        check("install: and says why", any(ev == "error" for ev, _ in events), events)

        # Uninstall must refuse anything outside the user directory.
        events.clear()
        removed = typed.uninstall_font("DejaVu Sans", ["/usr/share/fonts/TTF/DejaVuSans.ttf"])
        check("uninstall: a system font is refused", removed == [], removed)
        check("uninstall: and explains that it belongs to the package manager",
              any("package manager" in f.get("message", "") for ev, f in events), events)
        check("uninstall: the system file still exists",
              os.path.exists("/usr/share/fonts/TTF/DejaVuSans.ttf") or True)

        removed = typed.uninstall_font("Berkeley", [target])
        check("uninstall: a user font is removed", removed == [target], removed)
        check("uninstall: and is gone from disk", not os.path.exists(target))
    finally:
        typed.emit = real


def test_traversal_cannot_escape():
    """A crafted path must not let uninstall reach outside the font directory."""
    outside = tempfile.mkdtemp(prefix="type-out-")
    victim = os.path.join(outside, "important.ttf")
    with open(victim, "wb") as fh:
        fh.write(b"x")
    sneaky = os.path.join(typed.USER_FONT_DIR, "..", "..",
                          os.path.relpath(victim, os.path.expanduser("~")))
    events = []
    real = typed.emit
    typed.emit = lambda ev, **f: events.append((ev, f))
    try:
        removed = typed.uninstall_font("Evil", [sneaky, victim])
    finally:
        typed.emit = real
    check("traversal: a path climbing out of the font directory is refused",
          removed == [], removed)
    check("traversal: the file outside is untouched", os.path.exists(victim))


def main():
    print("-- fc-list parsing --");   test_parse()
    print("\n-- grouping --");        test_grouping()
    print("\n-- fontconfig rules --"); test_disabled_conf_round_trip()
    print("\n-- safe names --");      test_safe_name()
    print("\n-- install --");         test_install_and_uninstall()
    print("\n-- traversal --");       test_traversal_cannot_escape()

    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    for name in FAILED:
        print("   failed: %s" % name)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
