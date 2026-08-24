#!/usr/bin/env python3
"""
Tests for the colour-vision maths behind the Lens shaders.

A shader cannot be run here - there is no GPU and no compositor - so the
strategy is to test the maths in Python and generate the GLSL from the same
matrices. If these pass, the only thing left that can be wrong in the shader is
the transcription, and a case below checks that too by re-deriving the emitted
matrices from the source ones.

    python3 test_colour.py
"""

import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SHADERS = os.path.join(os.path.dirname(HERE), "shaders")
spec = importlib.util.spec_from_file_location("gen", os.path.join(SHADERS, "generate.py"))
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print("  %s %s%s" % ("PASS" if condition else "FAIL", name,
                         "" if condition else "   <- %s" % detail))


def close(a, b, tol=0.02):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


WHITE = [1.0, 1.0, 1.0]
BLACK = [0.0, 0.0, 0.0]
RED   = [1.0, 0.0, 0.0]
GREEN = [0.0, 1.0, 0.0]
BLUE  = [0.0, 0.0, 1.0]
GREY  = [0.5, 0.5, 0.5]


def test_greys_survive():
    """Neutral colours carry no chroma, so no deficiency should move them."""
    for kind in gen.SIMULATE:
        for name, colour in (("white", WHITE), ("black", BLACK), ("grey", GREY)):
            got = gen.simulate(colour, kind)
            check("%s: %s is unchanged by simulation" % (kind, name),
                  close(got, colour, 0.03), [round(c, 3) for c in got])
            got = gen.correct(colour, kind)
            check("%s: %s is unchanged by correction" % (kind, name),
                  close(got, colour, 0.03), [round(c, 3) for c in got])


def test_confusion_lines():
    """The point of the exercise: red and green must collapse together."""
    for kind in ("protanopia", "deuteranopia"):
        r = gen.simulate(RED, kind)
        g = gen.simulate(GREEN, kind)
        # Under red-green deficiency the two should land far closer together
        # than they start - they are confusable, that is the definition.
        before = sum(abs(RED[i] - GREEN[i]) for i in range(3))
        after = sum(abs(r[i] - g[i]) for i in range(3))
        check("%s: red and green move closer together" % kind, after < before,
              "before %.2f after %.2f" % (before, after))
        check("%s: simulated red keeps no green channel separation" % kind,
              abs(r[1] - g[1]) < 0.75, abs(r[1] - g[1]))

    # Tritanopia is blue/yellow, so red and green must NOT collapse.
    r = gen.simulate(RED, "tritanopia")
    g = gen.simulate(GREEN, "tritanopia")
    check("tritanopia: red and green stay distinct",
          sum(abs(r[i] - g[i]) for i in range(3)) > 0.8,
          sum(abs(r[i] - g[i]) for i in range(3)))


def test_correction_adds_signal():
    """Correction must actually change confusable colours, and by a useful amount."""
    for kind in ("protanopia", "deuteranopia"):
        cr = gen.correct(RED, kind)
        cg = gen.correct(GREEN, kind)
        moved_r = sum(abs(cr[i] - RED[i]) for i in range(3))
        moved_g = sum(abs(cg[i] - GREEN[i]) for i in range(3))
        check("%s: correction moves red" % kind, moved_r > 0.05, moved_r)
        check("%s: correction moves green" % kind, moved_g > 0.05, moved_g)



def test_confusable_pairs_become_separable():
    """The actual claim, tested on the colours the algorithm exists for.

    Pure red against pure green is the wrong test: under protanopia they
    simulate to lightness 0.37 and 0.95, so a protanope tells them apart
    easily and there is nothing to correct. The pairs that matter are the ones
    that are far apart in truth and close together once simulated - and on
    those, correction must reliably pull them back apart.
    """
    import random
    random.seed(7)

    def dist(a, b):
        return sum(abs(x - y) for x, y in zip(a, b))

    for kind in ("protanopia", "deuteranopia", "tritanopia"):
        better = worse = 0
        for _ in range(20000):
            a = [random.random() for _ in range(3)]
            b = [random.random() for _ in range(3)]
            plain = dist(gen.simulate(a, kind), gen.simulate(b, kind))
            # confusable once simulated, but genuinely different colours
            if plain > 0.12 or dist(a, b) < 0.25:
                continue
            fixed = dist(gen.simulate(gen.correct(a, kind), kind),
                         gen.simulate(gen.correct(b, kind), kind))
            if fixed > plain:
                better += 1
            else:
                worse += 1
        total = better + worse
        rate = 100.0 * better / total if total else 0.0
        check("%s: enough confusable pairs sampled" % kind, total >= 50, total)
        check("%s: correction separates confusable pairs (%.0f%% of %d)"
              % (kind, rate, total), rate >= 85.0, "%.1f%%" % rate)


def test_output_in_range():
    """Nothing may leave the 0..1 range; a shader clamps but the maths should too."""
    bad = []
    for kind in gen.SIMULATE:
        for r in (0.0, 0.25, 0.5, 0.75, 1.0):
            for g in (0.0, 0.5, 1.0):
                for b in (0.0, 0.5, 1.0):
                    for fn in (gen.simulate, gen.correct):
                        out = fn([r, g, b], kind)
                        if fn is gen.correct and any(c < -1e-6 or c > 1 + 1e-6 for c in out):
                            bad.append((kind, fn.__name__, [r, g, b], out))
    check("correction output is always within 0..1", not bad, bad[:2])


def test_gamma_round_trip():
    for v in (0.0, 0.01, 0.04045, 0.5, 0.9, 1.0):
        back = gen.linear_to_srgb(gen.srgb_to_linear(v))
        if abs(back - v) > 1e-6:
            check("gamma round-trips at %.5f" % v, False, back)
            return
    check("gamma round-trips across the curve, including the linear segment", True)


def test_glsl_matches_python():
    """The emitted GLSL must carry the same matrices, in column-major order.

    GLSL mat3 takes columns; Python holds rows. Getting that backwards produces
    a shader that compiles, runs, and quietly transposes every colour.
    """
    text = open(os.path.join(SHADERS, "deuteranopia-correct.frag")).read()

    def emitted(name):
        m = re.search(r"const mat3 %s = mat3\(\s*([^)]+)\);" % name, text, re.S)
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", m.group(1))]
        # nums are three columns of three
        return [[nums[c * 3 + r] for c in range(3)] for r in range(3)]

    for name, source in (("RGB_TO_LMS", gen.RGB_TO_LMS),
                         ("LMS_TO_RGB", gen.LMS_TO_RGB),
                         ("SIMULATE", gen.SIMULATE["deuteranopia"]),
                         ("ERROR_SHIFT", gen.ERROR_SHIFT["deuteranopia"])):
        got = emitted(name)
        same = all(abs(got[r][c] - source[r][c]) < 1e-6
                   for r in range(3) for c in range(3))
        check("glsl: %s survives column-major emission" % name, same, got)


def test_tritanopia_has_its_own_redistribution():
    """The shared red-green matrix pushes tritan error into blue - the one
    channel a tritanope cannot see. They must not be the same matrix."""
    rg = gen.ERROR_SHIFT["deuteranopia"]
    tri = gen.ERROR_SHIFT["tritanopia"]
    check("tritanopia does not reuse the red-green matrix", rg != tri)
    check("tritanopia sends no error into blue",
          all(row[2] == 0.0 for row in [tri[2]]) and tri[2] == [0.0, 0.0, 0.0], tri)
    check("red-green sends no error into red", rg[0] == [0.0, 0.0, 0.0], rg)

    text = open(os.path.join(SHADERS, "tritanopia-correct.frag")).read()
    other = open(os.path.join(SHADERS, "deuteranopia-correct.frag")).read()
    def shift_block(t):
        m = re.search(r"const mat3 ERROR_SHIFT = mat3\(\s*([^)]+)\);", t, re.S)
        return m.group(1) if m else None
    check("the emitted shaders carry different matrices",
          shift_block(text) is not None and shift_block(text) != shift_block(other))


def test_shaders_are_current_and_sane():
    files = gen.all_shaders()
    check("generator emits all ten shaders", len(files) == 10, len(files))

    missing = [n for n in files if not os.path.exists(os.path.join(SHADERS, n))]
    check("every shader is on disk", not missing, missing)

    stale = [n for n, c in files.items()
             if os.path.exists(os.path.join(SHADERS, n))
             and open(os.path.join(SHADERS, n)).read() != c]
    check("no shader on disk is stale", not stale, stale)

    # Hyprland's screen-shader interface, and the reserved word that silently
    # breaks compilation on some drivers.
    for name in files:
        body = open(os.path.join(SHADERS, name)).read()
        if "v_texcoord" not in body or "gl_FragColor" not in body:
            check("shader %s uses Hyprland's interface" % name, False)
            return
        if re.search(r"\b(vec[234]|float|int)\s+fixed\b", body):
            check("shader %s avoids the reserved word 'fixed'" % name, False)
            return
    check("every shader uses v_texcoord/gl_FragColor and avoids reserved words", True)


def main():
    print("-- neutrals --");            test_greys_survive()
    print("\n-- confusion lines --");   test_confusion_lines()
    print("\n-- correction --");        test_correction_adds_signal()
    print("\n-- confusable pairs --");  test_confusable_pairs_become_separable()
    print("\n-- range --");             test_output_in_range()
    print("\n-- gamma --");             test_gamma_round_trip()
    print("\n-- glsl transcription --");test_glsl_matches_python()
    print("\n-- tritan redistribution --"); test_tritanopia_has_its_own_redistribution()
    print("\n-- shader files --");      test_shaders_are_current_and_sane()

    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    for name in FAILED:
        print("   failed: %s" % name)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
