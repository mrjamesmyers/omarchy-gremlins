#!/usr/bin/env python3
"""Gate every shipped wallpaper on the two things that actually break it.

1. ASSETS EXIST AND MATCH THE MANIFEST.
   BarWidget.qml builds the asset URL by string concatenation:

       "assets/wallpapers/" + settings.wallpaper + "-still.jpg"

   so a name that is in the manifest but not on disk does not raise - it
   silently yields a broken Image and a transparent desktop. Nothing in the
   running shell will tell you. This is the check that turns that into a red
   build.

2. THE LOOP ACTUALLY CLOSES.
   The wallpaper rests on a still and plays the clip occasionally, so two
   joins have to be invisible: still -> first frame, and last frame -> still.
   Both are supposed to be free because each clip is generated with its still
   as start_image AND end_image, and each still is exported from frame 0 of
   the final encode. "Supposed to be" is why this measures it.

   The thresholds weight p99 and max, not the mean. A velociraptor whose tail
   was still in the last frame scored a mean of 3.02 - comfortably inside any
   mean-only limit - while popping hard on screen. p99 caught it at 29.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from seamcheck import frame, load, compare  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WALLPAPERS = os.path.join(ROOT, "assets", "wallpapers")

# Tuned from the shipped set, whose worst case is pumpkin at mad 2.06 / p99 10
# / max 92. Anything materially worse than the fleet is a regression.
MAX_MAD = 4.0
MAX_P99 = 20.0
MAX_MAX = 130.0


def manifest_wallpapers():
    with open(os.path.join(ROOT, "manifest.json")) as fh:
        m = json.load(fh)
    for field in m["barWidget"].get("schema", []):
        if field["key"] == "wallpaper":
            return [o for o in field["options"] if o != ""]
    raise SystemExit("manifest.json declares no `wallpaper` enum")


def main():
    names = manifest_wallpapers()
    print(f"manifest declares {len(names)} wallpapers: {', '.join(names)}\n")

    failures = []

    for name in names:
        clip = os.path.join(WALLPAPERS, f"{name}.mp4")
        still = os.path.join(WALLPAPERS, f"{name}-still.jpg")

        missing = [p for p in (clip, still) if not os.path.exists(p)]
        if missing:
            for p in missing:
                failures.append(f"{name}: missing {os.path.relpath(p, ROOT)}")
                print(f"  {name:<14} MISSING {os.path.relpath(p, ROOT)}")
            continue

        first, last, s = frame(clip, "first"), frame(clip, "last"), load(still)

        for label, a, b in (
            ("last->first", last, first),
            ("still->first", s, first),
            ("last->still", last, s),
        ):
            r = compare(a, b, label)
            if "error" in r:
                failures.append(f"{name}/{label}: {r['error']}")
                print(f"  {name:<14} {label:<13} ERROR {r['error']}")
                continue
            bad = r["mad"] > MAX_MAD or r["p99"] > MAX_P99 or r["max"] > MAX_MAX
            print(f"  {name:<14} {label:<13} mad={r['mad']:6.2f} "
                  f"p99={r['p99']:5.1f} max={r['max']:5.0f} "
                  f"{'FAIL' if bad else 'ok'}")
            if bad:
                failures.append(
                    f"{name}/{label}: mad={r['mad']} p99={r['p99']} max={r['max']}")

    # Assets on disk that nothing in the manifest offers are dead weight in a
    # repo people clone, and usually mean a rename went half-finished.
    on_disk = {f[:-4] for f in os.listdir(WALLPAPERS) if f.endswith(".mp4")}
    orphans = sorted(on_disk - set(names))
    if orphans:
        print(f"\n  orphaned clips not offered by the manifest: {', '.join(orphans)}")
        failures.append(f"orphaned clips: {', '.join(orphans)}")

    print()
    if failures:
        print(f"FAILED ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"all {len(names)} wallpapers pass: assets present, both joins invisible")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
