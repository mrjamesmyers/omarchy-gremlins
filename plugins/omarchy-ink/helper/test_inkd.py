#!/usr/bin/env python3
"""
Tests for inkd, mostly for the coordinate transform.

A viewer shows a page with the origin top-left, in pixels, already rotated by
/Rotate. A PDF wants the origin bottom-left, in points, before /Rotate is
applied. Getting the inverse wrong puts every signature on the wrong edge of
every scanned document - and scans are exactly the documents people sign.

Corners are the clearest way to pin this down: there is only one right answer
for where the top-left of the display lands in user space at each angle.

    python3 test_inkd.py
"""

import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("inkd", os.path.join(HERE, "inkd.py"))
inkd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inkd)
pdf = inkd.pdfcore

pspec = importlib.util.spec_from_file_location("tp", os.path.join(HERE, "test_pdfcore.py"))
tp = importlib.util.module_from_spec(pspec)
pspec.loader.exec_module(tp)

PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print("  %s %s%s" % ("PASS" if condition else "FAIL", name,
                         "" if condition else "   <- %s" % detail))


def page(rotate=0, w=612.0, h=792.0, x0=0.0, y0=0.0):
    return {"index": 0, "objnum": 3, "width": w, "height": h,
            "x0": x0, "y0": y0, "rotate": rotate}


def near(got, want, tol=0.01):
    return abs(got[0] - want[0]) <= tol and abs(got[1] - want[1]) <= tol


def test_visual_size():
    check("size: an upright page keeps its size",
          inkd.visual_size(page(0)) == (612.0, 792.0))
    check("size: a quarter turn swaps width and height",
          inkd.visual_size(page(90)) == (792.0, 612.0))
    check("size: 180 does not swap", inkd.visual_size(page(180)) == (612.0, 792.0))
    check("size: 270 swaps", inkd.visual_size(page(270)) == (792.0, 612.0))


def test_corners_upright():
    p = page(0)
    check("0deg: display top-left is user top-left",
          near(inkd.to_user_space(p, 0, 0), (0, 792)), inkd.to_user_space(p, 0, 0))
    check("0deg: display bottom-right is user bottom-right",
          near(inkd.to_user_space(p, 612, 792), (612, 0)),
          inkd.to_user_space(p, 612, 792))


def test_corners_rotated():
    """Rotating a page clockwise for display moves its bottom-left to the top-left."""
    p = page(90)
    check("90deg: display top-left is user bottom-left",
          near(inkd.to_user_space(p, 0, 0), (0, 0)), inkd.to_user_space(p, 0, 0))
    check("90deg: display top-right is user top-left",
          near(inkd.to_user_space(p, 792, 0), (0, 792)), inkd.to_user_space(p, 792, 0))
    check("90deg: display bottom-left is user bottom-right",
          near(inkd.to_user_space(p, 0, 612), (612, 0)), inkd.to_user_space(p, 0, 612))

    p = page(180)
    check("180deg: display top-left is user bottom-right",
          near(inkd.to_user_space(p, 0, 0), (612, 0)), inkd.to_user_space(p, 0, 0))

    p = page(270)
    check("270deg: display top-left is user top-right",
          near(inkd.to_user_space(p, 0, 0), (612, 792)), inkd.to_user_space(p, 0, 0))
    check("270deg: display bottom-right is user bottom-left",
          near(inkd.to_user_space(p, 792, 612), (0, 0)), inkd.to_user_space(p, 792, 612))


def test_everything_lands_on_the_page():
    """No angle may map a point inside the display to outside the page."""
    bad = []
    for rotate in (0, 90, 180, 270):
        p = page(rotate)
        vw, vh = inkd.visual_size(p)
        for fx in (0.0, 0.25, 0.5, 0.75, 1.0):
            for fy in (0.0, 0.25, 0.5, 0.75, 1.0):
                u, v = inkd.to_user_space(p, vw * fx, vh * fy)
                if not (-0.01 <= u <= p["width"] + 0.01 and -0.01 <= v <= p["height"] + 0.01):
                    bad.append((rotate, fx, fy, u, v))
    check("bounds: every display point maps inside the page at every angle",
          not bad, bad[:3])


def test_centre_stays_centred():
    for rotate in (0, 90, 180, 270):
        p = page(rotate)
        vw, vh = inkd.visual_size(p)
        u, v = inkd.to_user_space(p, vw / 2, vh / 2)
        if not near((u, v), (p["width"] / 2, p["height"] / 2), 0.02):
            check("centre: the middle stays the middle at %d degrees" % rotate, False, (u, v))
            return
    check("centre: the middle of the display is the middle of the page at every angle", True)


def test_scale_and_offset():
    p = page(0)
    check("scale: a 2x zoomed click halves back to points",
          near(inkd.to_user_space(p, 200, 200, scale=2.0), (100, 792 - 100)),
          inkd.to_user_space(p, 200, 200, scale=2.0))
    check("scale: zero scale is treated as 1, not a division by zero",
          near(inkd.to_user_space(p, 100, 100, scale=0), (100, 692)),
          inkd.to_user_space(p, 100, 100, scale=0))

    shifted = page(0, x0=20.0, y0=30.0)
    check("offset: a MediaBox that does not start at the origin is added back",
          near(inkd.to_user_space(shifted, 0, 0), (20, 792 + 30)),
          inkd.to_user_space(shifted, 0, 0))


def test_op_conversion():
    p = page(0)
    ops = [{"type": "ink", "points": [[10, 10], {"x": 20, "y": 20}], "width": 4},
           {"type": "text", "text": "hi", "x": 50, "y": 100, "size": 20},
           {"type": "highlight", "x": 10, "y": 700, "width": 100, "height": 20}]
    out = inkd.convert_ops(p, ops, scale=2.0)

    check("ops: ink accepts both pair and object points",
          out[0]["points"] == [[5.0, 787.0], [10.0, 782.0]], out[0]["points"])
    check("ops: line width is divided by the zoom", out[0]["width"] == 2.0, out[0]["width"])

    # Baseline sits below the top-left anchor, in interface space, before rotating.
    check("ops: text baseline drops by roughly 0.8em",
          abs(out[1]["y"] - (792 - (100 + 20 * 0.8) / 2)) < 0.01, out[1])
    check("ops: text size is divided by the zoom", out[1]["size"] == 10.0, out[1]["size"])

    check("ops: a rectangle keeps positive width and height after flipping",
          out[2]["width"] > 0 and out[2]["height"] > 0, out[2])
    check("ops: the rectangle's y is its lower edge in user space",
          out[2]["y"] < 792 - 700 / 2 + 1, out[2])


def test_rect_stays_positive_when_rotated():
    bad = []
    for rotate in (0, 90, 180, 270):
        out = inkd.convert_ops(page(rotate),
                               [{"type": "rect", "x": 40, "y": 40,
                                 "width": 120, "height": 30}])
        if out[0]["width"] <= 0 or out[0]["height"] <= 0:
            bad.append((rotate, out[0]))
    check("rect: never collapses to a negative box at any angle", not bad, bad)


def test_open_and_save_round_trip():
    workdir = tempfile.mkdtemp(prefix="inkd-")
    source = os.path.join(workdir, "contract.pdf")
    with open(source, "wb") as fh:
        fh.write(tp.classic_pdf(pages=2))

    events = []
    real = inkd.emit
    inkd.emit = lambda ev, **f: events.append((ev, f))
    try:
        ink = inkd.Ink()
        ink.open_document(source)
        opened = [f for ev, f in events if ev == "opened"]
        check("open: reported the document", len(opened) == 1, [e for e, _ in events])
        if opened:
            check("open: both pages listed", len(opened[0]["pages"]) == 2, opened[0])
            check("open: visual size reported", opened[0]["pages"][0]["width"] == 612.0,
                  opened[0]["pages"][0])

        events.clear()
        target = os.path.join(workdir, "signed.pdf")
        ink.save(target, {"0": [{"type": "ink",
                                 "points": [[100, 100], [200, 150]], "width": 3}]}, 1.0)
        saved = [f for ev, f in events if ev == "saved"]
        check("save: reported success", len(saved) == 1, events)
        check("save: bytes appended", saved and saved[0]["appended"] > 0, saved)
        check("save: the written file parses", ink.verify(target) == 2, ink.verify(target))

        with open(source, "rb") as fh:
            after = fh.read()
        check("save: the source was not modified", after == tp.classic_pdf(pages=2))

        # Saving over the source must be refused, silently redirected, not obeyed.
        events.clear()
        ink.save(source, {"0": [{"type": "ink", "points": [[1, 1], [2, 2]]}]}, 1.0)
        saved = [f for ev, f in events if ev == "saved"]
        check("save: refuses to overwrite the source",
              saved and os.path.abspath(saved[0]["path"]) != os.path.abspath(source), saved)
        with open(source, "rb") as fh:
            check("save: and the source really is still untouched",
                  fh.read() == tp.classic_pdf(pages=2))
    finally:
        inkd.emit = real


def test_bad_input():
    events = []
    real = inkd.emit
    inkd.emit = lambda ev, **f: events.append((ev, f))
    try:
        ink = inkd.Ink()
        ink.open_document("/does/not/exist.pdf")
        check("bad: a missing file is an error, not a crash",
              any(ev == "error" for ev, _ in events), events)

        workdir = tempfile.mkdtemp(prefix="inkd-bad-")
        junk = os.path.join(workdir, "junk.pdf")
        with open(junk, "wb") as fh:
            fh.write(b"this is not a pdf at all")
        events.clear()
        ink.open_document(junk)
        check("bad: a non-PDF is an error, not a crash",
              any(ev == "error" for ev, _ in events), events)

        events.clear()
        ink.save("/tmp/nope.pdf", {}, 1.0)
        check("bad: saving with nothing open is an error",
              any(ev == "error" for ev, _ in events), events)
    finally:
        inkd.emit = real


def main():
    print("-- page size --");        test_visual_size()
    print("\n-- corners --");        test_corners_upright(); test_corners_rotated()
    print("\n-- invariants --");     test_everything_lands_on_the_page(); test_centre_stays_centred()
    print("\n-- scale/offset --");   test_scale_and_offset()
    print("\n-- operations --");     test_op_conversion(); test_rect_stays_positive_when_rotated()
    print("\n-- round trip --");     test_open_and_save_round_trip()
    print("\n-- bad input --");      test_bad_input()

    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    for name in FAILED:
        print("   failed: %s" % name)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
