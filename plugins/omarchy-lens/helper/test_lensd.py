#!/usr/bin/env python3
"""
Tests for lensd.

Two things matter here and both are testable without a compositor: whether the
daemon finds the right hyprctl option name on a given Hyprland, and whether the
WCAG contrast maths is right. Everything else is one subprocess call.

    python3 test_lensd.py
"""

import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp(prefix="lens-state-")
spec = importlib.util.spec_from_file_location("lensd", os.path.join(HERE, "lensd.py"))
lensd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lensd)

PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print("  %s %s%s" % ("PASS" if condition else "FAIL", name,
                         "" if condition else "   <- %s" % detail))


class FakeHyprland:
    """Answers `getoption` only for the keys a given Hyprland version knows."""

    def __init__(self, known):
        self.known = set(known)
        self.calls = []

    def __call__(self, args, timeout=6):
        self.calls.append(list(args))
        if args[:2] == ["hyprctl", "getoption"]:
            key = args[2]
            if key in self.known:
                return 0, "int: 1\nset: false\n", ""
            # This is what Hyprland actually says for a key it does not have.
            return 0, "Invalid option\n", ""
        if args[:2] == ["hyprctl", "keyword"]:
            return 0, "ok\n", ""
        if args[:2] == ["hyprctl", "cursorpos"]:
            return 0, "960, 540\n", ""
        if args[:2] == ["hyprctl", "setcursor"]:
            return 0, "ok\n", ""
        return 1, "", "unexpected"


def with_hypr(fake, fn):
    real_run, real_which = lensd.run, lensd.shutil.which
    lensd.run = fake
    lensd.shutil.which = lambda n: "/usr/bin/" + n
    try:
        return fn()
    finally:
        lensd.run, lensd.shutil.which = real_run, real_which


def make_lens(fake):
    """Build and probe inside the patched context.

    Lens.__init__ resolves hyprctl once, at construction, and probe() returns
    immediately when it is absent. Constructing outside the patch produces a
    daemon that believes it is on a machine with no Hyprland - which is exactly
    what this container is.
    """
    def build():
        lens = lensd.Lens()
        lens.probe()
        return lens
    return with_hypr(fake, build)


def quiet(fn):
    real = lensd.emit
    seen = []
    lensd.emit = lambda ev, **f: seen.append((ev, f))
    try:
        fn()
    finally:
        lensd.emit = real
    return seen


# --------------------------------------------------------------------------

def test_probe_current_hyprland():
    fake = FakeHyprland(["cursor:zoom_factor", "cursor:zoom_rigid",
                         "decoration:screen_shader", "animations:enabled"])
    lens = make_lens(fake)
    check("probe: finds the current zoom key", lens.zoom_key == "cursor:zoom_factor",
          lens.zoom_key)
    check("probe: finds the shader key", lens.shader_key == "decoration:screen_shader",
          lens.shader_key)
    caps = lens.capabilities()
    check("probe: reports magnifier available", caps["magnifier"] is True)
    check("probe: reports filters available", caps["filters"] is True)


def test_probe_older_hyprland():
    """The zoom factor used to live under misc:. That machine must still work."""
    fake = FakeHyprland(["misc:cursor_zoom_factor", "misc:cursor_zoom_rigid",
                         "decoration:screen_shader", "animations:enabled"])
    lens = make_lens(fake)
    check("probe: falls back to the older misc: zoom key",
          lens.zoom_key == "misc:cursor_zoom_factor", lens.zoom_key)
    check("probe: still reports the magnifier as available",
          lens.capabilities()["magnifier"] is True)


def test_probe_missing_features():
    """A Hyprland with no screen shader must say so, not silently no-op."""
    fake = FakeHyprland(["cursor:zoom_factor", "animations:enabled"])
    lens = make_lens(fake)
    check("probe: shader key stays unset when absent", lens.shader_key is None,
          lens.shader_key)
    caps = lens.capabilities()
    check("probe: filters reported unavailable", caps["filters"] is False)

    seen = quiet(lambda: with_hypr(fake, lambda: lens.set_filter("invert")))
    check("probe: setting a filter without support raises a clear error",
          any(ev == "error" and "screen-shader" in f.get("message", "")
              for ev, f in seen), seen)


def test_filter_paths():
    fake = FakeHyprland(["cursor:zoom_factor", "decoration:screen_shader",
                         "animations:enabled"])
    lens = make_lens(fake)

    quiet(lambda: with_hypr(fake, lambda: lens.set_filter("deuteranopia-correct")))
    applied = [c for c in fake.calls if c[:3] == ["hyprctl", "keyword", "decoration:screen_shader"]]
    check("filter: a shader path was applied", len(applied) == 1, applied)
    if applied:
        path = applied[0][3]
        check("filter: the path exists on disk", os.path.exists(path), path)
        check("filter: the right shader was chosen",
              path.endswith("deuteranopia-correct.frag"), path)

    seen = quiet(lambda: with_hypr(fake, lambda: lens.set_filter("not-a-filter")))
    check("filter: an unknown name is refused",
          any(ev == "error" for ev, _ in seen), seen)
    check("filter: and the refused name was not applied",
          not any("not-a-filter" in " ".join(c) for c in fake.calls))

    fake.calls.clear()
    quiet(lambda: with_hypr(fake, lambda: lens.set_filter("")))
    cleared = [c for c in fake.calls if c[:3] == ["hyprctl", "keyword", "decoration:screen_shader"]]
    check("filter: clearing passes an empty value", cleared and cleared[0][3] == '""',
          cleared)


def test_zoom_clamping():
    fake = FakeHyprland(["cursor:zoom_factor", "animations:enabled"])
    lens = make_lens(fake)

    for asked, expect in ((0.2, 1.0), (1.0, 1.0), (2.5, 2.5), (99.0, 8.0), (-4, 1.0)):
        fake.calls.clear()
        quiet(lambda: with_hypr(fake, lambda: lens.set_zoom(asked)))
        got = float([c for c in fake.calls if c[1] == "keyword"][0][3])
        if abs(got - expect) > 1e-6:
            check("zoom: %s clamps to %s" % (asked, expect), False, got)
            return
    # Below 1.0 Hyprland shrinks the screen, which no accessibility control means.
    check("zoom: clamped to 1.0-8.0, never below 1.0", True)


def test_contrast_maths():
    """Known WCAG values. Black on white is exactly 21:1."""
    black, white = (0, 0, 0), (255, 255, 255)
    check("contrast: black on white is 21:1",
          abs(lensd.contrast_ratio(black, white) - 21.0) < 0.01,
          lensd.contrast_ratio(black, white))
    check("contrast: a colour against itself is 1:1",
          abs(lensd.contrast_ratio((18, 52, 86), (18, 52, 86)) - 1.0) < 1e-9)
    check("contrast: order does not matter",
          abs(lensd.contrast_ratio(black, white) - lensd.contrast_ratio(white, black)) < 1e-9)

    # #767676 on white is the canonical WCAG AA boundary case, 4.54:1.
    ratio = lensd.contrast_ratio((0x76, 0x76, 0x76), white)
    check("contrast: #767676 on white lands just over 4.5",
          4.5 <= ratio <= 4.6, round(ratio, 3))

    check("verdict: 21 is AAA", lensd.wcag_verdict(21.0) == "AAA")
    check("verdict: 4.6 is AA", lensd.wcag_verdict(4.6) == "AA")
    check("verdict: 3.2 is large-text only", lensd.wcag_verdict(3.2) == "AA large only")
    check("verdict: 2.0 fails", lensd.wcag_verdict(2.0) == "fail")
    check("verdict: large text passes AA at 3.0", lensd.wcag_verdict(3.2, True) == "AA")


def test_colour_parsing():
    cases = [
        ("#ffffff", (255, 255, 255)),
        ("ffffff", (255, 255, 255)),
        ("#fff", (255, 255, 255)),
        ("#1a2b3c", (0x1a, 0x2b, 0x3c)),
        ("0x1a2b3c", (0x1a, 0x2b, 0x3c)),
        ("rgba(1,2,3)", None),
        ("12,34,56", (12, 34, 56)),
        ("", None),
        (None, None),
        ("nonsense", None),
    ]
    bad = [(t, lensd.parse_colour(t)) for t, want in cases
           if lensd.parse_colour(t) != want]
    check("colour: every accepted form parses, junk returns None", not bad, bad)

    # Hyprland writes AARRGGBB. Reading it as RRGGBBAA shifts every channel.
    check("colour: 8-digit values are read as AARRGGBB, not RRGGBBAA",
          lensd.parse_colour("ff1a2b3c") == (0x1a, 0x2b, 0x3c),
          lensd.parse_colour("ff1a2b3c"))


def test_state_round_trip():
    fake = FakeHyprland(["cursor:zoom_factor", "decoration:screen_shader",
                         "animations:enabled"])
    lens = make_lens(fake)
    quiet(lambda: with_hypr(fake, lambda: lens.set_zoom(2.0)))
    quiet(lambda: with_hypr(fake, lambda: lens.set_filter("greyscale")))
    quiet(lambda: with_hypr(fake, lambda: lens.set_animations(False)))

    fresh = make_lens(fake)
    fresh.load()
    check("state: zoom survives a restart", fresh.zoom == 2.0, fresh.zoom)
    check("state: filter survives a restart", fresh.filter == "greyscale", fresh.filter)
    check("state: reduce-motion survives a restart", fresh.animations is False)

    # An accessibility setting that silently lapses on restart is worse than
    # one that was never offered, so restore must actually re-apply it.
    fake.calls.clear()
    quiet(lambda: with_hypr(fake, fresh.restore))
    applied = " ".join(" ".join(c) for c in fake.calls)
    check("state: restore re-applies the filter", "greyscale.frag" in applied, applied[:120])
    check("state: restore re-applies the zoom", "cursor:zoom_factor 2.000" in applied,
          applied[:160])


def test_reset_clears_everything():
    fake = FakeHyprland(["cursor:zoom_factor", "decoration:screen_shader",
                         "animations:enabled"])
    lens = make_lens(fake)
    quiet(lambda: with_hypr(fake, lambda: lens.set_zoom(3.0)))
    quiet(lambda: with_hypr(fake, lambda: lens.set_filter("invert")))
    fake.calls.clear()
    quiet(lambda: with_hypr(fake, lens.reset))
    applied = " ".join(" ".join(c) for c in fake.calls)
    check("reset: clears the shader", 'decoration:screen_shader ""' in applied, applied)
    check("reset: returns zoom to 1.0", "cursor:zoom_factor 1.0" in applied, applied)
    check("reset: re-enables animations", "animations:enabled 1" in applied, applied)
    check("reset: state reflects it", lens.zoom == 1.0 and lens.filter == "")


def test_cursor_position():
    fake = FakeHyprland(["cursor:zoom_factor"])
    lens = make_lens(fake)
    pos = with_hypr(fake, lens.cursor_position)
    check("cursor: position parsed from hyprctl", pos == (960, 540), pos)


def main():
    print("-- probing --");        test_probe_current_hyprland(); test_probe_older_hyprland()
    print("\n-- missing features --"); test_probe_missing_features()
    print("\n-- filters --");      test_filter_paths()
    print("\n-- zoom --");         test_zoom_clamping()
    print("\n-- contrast --");     test_contrast_maths()
    print("\n-- colour parsing --"); test_colour_parsing()
    print("\n-- state --");        test_state_round_trip()
    print("\n-- reset --");        test_reset_clears_everything()
    print("\n-- cursor --");       test_cursor_position()

    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    for name in FAILED:
        print("   failed: %s" % name)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
