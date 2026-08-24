"""Measure whether an animated wallpaper actually closes its loop.

The wallpaper shows a still almost all the time and plays the clip occasionally,
so two joins have to be invisible:

    still -> first frame      (start of the event)
    last frame -> still       (end of the event)

Passing the same image as start_image and end_image to the generator is meant to
make both joins free, but generators drift. This measures the drift instead of
trusting it, in three ways, because mean absolute difference alone hides a small
bright artefact in a dark frame:

    mad      mean absolute difference over all pixels, 0-255
    p99      99th percentile absolute difference - catches localised popping
    shift    best-matching integer pixel offset, which catches a whole-frame
             drift that MAD would report as "slightly different everywhere"
"""
import subprocess, sys, json
import numpy as np
from PIL import Image
import io


def frame(path, when):
    """Decode one frame as RGB. when='first' or 'last'."""
    if when == "first":
        cmd = ["ffmpeg", "-v", "error", "-i", path, "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"]
    else:
        cmd = ["ffmpeg", "-v", "error", "-sseof", "-0.08", "-i", path, "-frames:v", "1",
               "-update", "1", "-f", "image2pipe", "-vcodec", "png", "-"]
    out = subprocess.run(cmd, capture_output=True).stdout
    return np.asarray(Image.open(io.BytesIO(out)).convert("RGB")).astype(np.float32)


def load(path):
    return np.asarray(Image.open(path).convert("RGB")).astype(np.float32)


def compare(a, b, label):
    if a.shape != b.shape:
        return {"label": label, "error": f"shape {a.shape} vs {b.shape}"}
    d = np.abs(a - b)
    # best integer shift within +/-3 px - a pure translation is a drifting camera,
    # not a content mismatch, and reads very differently on screen
    best, bestmad = (0, 0), d.mean()
    for dy in range(-3, 4):
        for dx in range(-3, 4):
            if dy == 0 and dx == 0:
                continue
            m = np.abs(np.roll(np.roll(a, dy, 0), dx, 1) - b)[4:-4, 4:-4].mean()
            if m < bestmad:
                bestmad, best = m, (dy, dx)
    return {
        "label": label,
        "mad": round(float(d.mean()), 2),
        "p99": round(float(np.percentile(d, 99)), 1),
        "shift": best,
        "shift_mad": round(float(bestmad), 2),
        "max": round(float(d.max()), 0),
    }


if __name__ == "__main__":
    clip = sys.argv[1]
    still = sys.argv[2] if len(sys.argv) > 2 else None
    f, l = frame(clip, "first"), frame(clip, "last")
    rows = [compare(l, f, "last->first (the loop)")]
    if still:
        s = load(still)
        rows.append(compare(s, f, "still->first"))
        rows.append(compare(l, s, "last->still"))
    for r in rows:
        if "error" in r:
            print(f"  {r['label']:24s} ERROR {r['error']}")
        else:
            # p99 and max are the load-bearing tests. A small object left in the
            # last frame - a tail, a hand, a bird - barely moves the mean but pops
            # hard on screen, which is exactly the failure a mean-only threshold
            # waves through.
            ok = r["mad"] < 4 and r["p99"] < 20 and r["max"] < 130
            verdict = "seamless" if ok else ("drift" if r["shift"] != (0, 0) and r["shift_mad"] < r["mad"] * 0.7 else "POPS")
            print(f"  {r['label']:24s} mad={r['mad']:6.2f}  p99={r['p99']:5.1f}  max={r['max']:5.0f}  -> {verdict}")
