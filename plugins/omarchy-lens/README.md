# Lens

**The accessibility layer Omarchy does not have.** Of the 1,099 plugins in the community
registry, one is an accessibility plugin and it does sticky keys. No magnifier, no
colour-vision correction, no high contrast, no cursor aids.

```bash
omarchy plugin add https://github.com/mrjamesmyers/omarchy-lens.git --enable
omarchy bar plugin add io.github.mrjamesmyers.lens
```

Plugins run unsandboxed inside your shell process. Read the source before you enable
anything, including this.

---

## What it does

- **Magnifier** — 1× to 8×, on the scroll wheel over the bar widget or on a keybind.
- **Colour-vision correction** for protanopia, deuteranopia and tritanopia — the
  colours a dichromat cannot separate are redistributed into ones they can.
- **Simulation** of all three, for checking a theme the way a designer would.
- **High contrast, invert, greyscale, dim.**
- **Reduce motion** — turns off window animations, for vestibular sensitivity.
- **Bigger cursor**, and a ring that pulses where the pointer is when you lose it.
- **A WCAG contrast check** on the current theme's bar text.

Everything persists and is re-applied at login. An accessibility setting that silently
lapses on restart is worse than one that was never offered.

## How it works, and why nothing here needs a password

All of it goes through `hyprctl`:

| Feature | Mechanism |
|---|---|
| Magnifier | `cursor:zoom_factor` |
| Colour filters | `decoration:screen_shader`, pointed at the shaders in `shaders/` |
| Reduce motion | `animations:enabled` |
| Cursor size | `hyprctl setcursor` |
| Find the pointer | `hyprctl cursorpos` plus a click-through layer surface |

**Nothing is hard-coded.** Hyprland has moved these option names between releases — the
zoom factor used to live under `misc:` — so every key is probed with `hyprctl getoption`
at startup and the working spelling is remembered. A plugin that assumes one spelling
works on the author's machine and silently does nothing on everybody else's. Where a
feature genuinely is not available, the control is shown **disabled with the reason**,
never as a button that quietly does nothing.

Worth noting: **no other plugin in the registry uses Hyprland's screen shaders at all.**
It is an entirely unused mechanism, and it is exactly what colour correction needs.

## The colour science

Daltonisation runs the standard LMS pipeline — convert to cone response, simulate the
deficiency there, take the error the viewer cannot see, and redistribute it into channels
they can. The maths lives in `shaders/generate.py`, where it is tested, and the GLSL is
emitted from the same matrices. Hand-written shaders would be nine files of magic numbers
that nothing checks.

**One place this departs from most implementations.** Nearly everything that ships
daltonisation uses a single error-redistribution matrix for all three deficiencies, and
that matrix is built for red–green: it moves red-channel error into green *and blue*. For
a tritanope, blue is precisely the channel that is lost, so the standard matrix pushes the
information into the one place they cannot see it.

Measured over confusable colour pairs — pairs that are far apart in truth and close
together once simulated — the shared matrix corrects:

| Deficiency | Shared matrix | With its own matrix |
|---|---:|---:|
| Protanopia | 97% | 97% |
| Deuteranopia | 96% | 96% |
| **Tritanopia** | **74%** | **91%** |

So tritanopia gets its own matrix, sending blue error into red and green. The coefficient
is higher too (1.0 rather than 0.7), because blue error is large and a gentler shift does
not carry enough signal. It clips more of the picture as a result — that is the honest
trade, and somebody who turns this on wants the distinction more than the fidelity.

## Keybinds

Worth putting in `hyprland.conf`:

```
bind = SUPER, equal,  exec, omarchy-shell omarchy.lens zoomIn
bind = SUPER, minus,  exec, omarchy-shell omarchy.lens zoomOut
bind = SUPER, F5,     exec, omarchy-shell omarchy.lens locate
bind = SUPER SHIFT, F5, exec, omarchy-shell omarchy.lens reset
```

`omarchy-shell omarchy.lens filter deuteranopia-correct` sets a filter by name.

## Settings

| Setting | Default | What it does |
|---|---|---|
| `zoomStep` | `0.5` | How far one scroll notch moves the magnifier |
| `showWhenInactive` | `true` | Keep the widget visible when nothing is on. On by default — a control you cannot find is not a control |
| `locateOnClick` | `true` | Middle-click pulses a ring at the pointer |
| `rigidZoom` | `false` | Magnifier follows the pointer exactly rather than drifting |

## Requirements

`python3` and `hyprctl`, both already on Omarchy. No pip, no sudo, no install hooks, and
no new packages — the shaders ship with the plugin.

## Tests

```bash
python3 helper/test_colour.py    # 47 cases - the colour maths and the emitted GLSL
python3 helper/test_lensd.py     # 37 cases - option probing, contrast, state
```

A shader cannot run here — no GPU, no compositor — so the maths is tested in Python and
the GLSL is generated from the same matrices, with a case that re-derives the emitted
matrices to catch a column-major transposition. A transposed matrix compiles, runs, and
quietly wrecks every colour.

Things those tests caught or settled:

- **`fixed` is a reserved word in GLSL ES.** A shader using it as a variable fails to
  compile on some drivers without saying why.
- **Tritanopia needed its own error matrix** — the 74% → 91% result above came out of a
  test that was failing for a real reason.
- **Pure red against pure green is the wrong test case.** Under protanopia they simulate
  to lightness 0.37 and 0.95, so a protanope tells them apart easily. Testing the
  algorithm on them nearly led to "fixing" maths that was already correct.

## Known limits

- **The magnifier is per-monitor.** Hyprland's zoom applies to the monitor the pointer is
  on; moving to another resets it. That is a compositor behaviour, not something a plugin
  can paper over.
- **Screen shaders affect everything**, including screenshots and screen shares.
- **This is not a screen reader.** Reading the interface aloud needs an accessibility bus
  that Wayland and Hyprland do not currently provide.

## Removing it

```bash
omarchy-shell omarchy.lens reset          # turn everything off first
omarchy bar plugin remove io.github.mrjamesmyers.lens
omarchy plugin disable io.github.mrjamesmyers.lens
omarchy plugin remove io.github.mrjamesmyers.lens
rm -rf ~/.local/state/omarchy-lens
```

Run the reset first: the shader and zoom are Hyprland runtime settings, and removing the
plugin does not undo them. They clear on their own at the next Hyprland restart either way.

## Credits

Built by [James Myers](https://github.com/mrjamesmyers). MIT licensed.
Daltonisation follows the standard LMS method described by Viénot, Brettel and Mollon,
with the error-redistribution approach popularised by Fidaner, Lin and Ozguven.
Not affiliated with, sponsored by, or endorsed by Omarchy, the Omacom Foundation, or
37signals.
