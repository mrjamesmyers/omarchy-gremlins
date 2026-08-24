# Gremlins

**A boot bumper and nine animated wallpapers for Omarchy Quattro.** Gremlins haul pixel
crumbs out of the dark, one of them screams **OMACHEE**, and then they're gone — three
seconds, once, and your desktop is yours.

> The R is silent. That's the joke, and also the point.

![Gremlins](preview.gif)

```bash
omarchy plugin add https://github.com/mrjamesmyers/omarchy-gremlins.git --enable
```

Omarchy will show you the repo and ask you to confirm — plugins run unsandboxed inside the
shell process, so read the source before you enable anything, including this.

---

## What it does

- **Plays once on login, on every screen.** Not a loop, not a screensaver. Three seconds,
  then nothing.
- **Something climbs down out of your bar.** Every minute or two a gremlin lowers itself
  into view below the bar and hangs there over your wallpaper, watching, then climbs back
  up. Left-click replays the bumper, **right-click opens settings**. It reserves no screen
  space and is click-through everywhere except the creature.
- **Nine animated wallpapers, opt-in.** A still holds your desktop; every so often it comes
  alive for ten seconds and then hands the still straight back. Off by default.

## The wallpapers

| | Scene | | Scene |
|---|---|---|---|
| `tv` | Gremlins watching an Omarchy ad on a CRT | `highlands` | Cloud shadow sweeping a Scottish glen |
| `nineteen84` | The 1984 homage, with camera angles | `ycombinator` | A startup garage at 2am |
| `runners` | The pack running past in the dark | `seventies` | Sunken living room, lava lamp |
| `viking` | Longship under an aurora | `pumpkin` | Autumn café table, steam curling |
| `raptor` | A feathered velociraptor, breathing | | |

Set one from the settings panel, or from a script:

```bash
omarchy-shell -q omarchy.gremlins setWallpaper viking
```

`playScene` plays it immediately instead of waiting for the interval, and
`currentWallpaper` reports which is active.

## Seamless, and measured

The desktop rests on a still almost all the time, so two joins have to be invisible:
`still → first frame` when the scene starts, and `last frame → still` when it ends.

Both are free by construction. Every clip was generated with its own still passed as
**both** `start_image` and `end_image`, so it is born opening and closing on the identical
frame, and each still is exported from **frame 0 of the final encode** so even the codec
noise matches. No boomerangs, no cross-dissolves, no fade to black — those are repairs for
footage that doesn't close, and they all show.

CI measures all three joins on every push, on a real Omarchy machine, and fails the build
if any drifts. The thresholds weight the 99th percentile and the single worst pixel rather
than the mean, because a small object left in the last frame — a tail, a hand — barely
moves the mean while popping hard on screen. An earlier velociraptor whose tail was still
in shot scored a mean of 3.02, inside any mean-only limit; p99 caught it at 29 and the clip
was rebuilt.

Worst case across the shipped nine is `pumpkin` at p99 11.

## Settings

Right-click the bar widget — or the hanging gremlin, which in `hang` style is the bigger
target. Style, scene, how often it plays, fill-vs-letterbox, and a preview of the still so
you can see a scene before committing to it.

Everything is also inline on the plugin entry in `~/.config/omarchy/shell.json`:

| Setting | Default | What it does |
|---|---|---|
| `style` | `"hang"` | `"hang"` — big, below the bar, over the wallpaper. `"descend"` — small, inside the bar cell. `"peek"` — eyes over the bar's edge |
| `wallpaper` | `""` | One of the nine names above. Empty is off, and gives your theme's background back |
| `wallpaperEverySeconds` | `60` | How long the still rests between plays |
| `wallpaperFill` | `true` | Crop to fill. Off letterboxes instead |
| `hangHeight` | `190` | How tall the creature is, in px, in `hang` mode |
| `hangX` | `0.74` | Where along the screen it hangs. 0 = left, 1 = right |
| `hangDrop` | `18` | Pixels below the bar, so the whole grin clears it |
| `barPixels` | `43` | Bar height used for placement |
| `spriteTopY` | `-4` | Fine vertical alignment of the sprite |
| `holdFrame` | `74` | Which frame it holds the grin on |
| `holdMs` | `1800` | How long it holds it |
| `peekMinSeconds` / `peekMaxSeconds` | `45` / `120` | Shortest and longest gap between appearances |

The last seven are calibration. The panel deliberately doesn't expose them, and it merges
rather than replaces when it writes, so tuning them by hand survives using the UI.

## Requirements

`qt6-multimedia` with the FFmpeg backend — already present on Omarchy Quattro, so there is
nothing to install. No sudo, no install hooks, no third-party repos.

Everything ships as **H.264 mp4**, not animated WebP. Omarchy's Qt has no WebP image plugin
at all (`/usr/lib/qt6/plugins/imageformats/` is gif/ico/jpeg/pdf/svg), so `AnimatedImage`
cannot decode WebP here — but `qt6-multimedia-ffmpeg` plays mp4 happily, and mp4 carries
its own audio track, so the scream needs no separate player.

## Cost

Nothing decodes at rest. The wallpaper surface draws a still; the `MediaPlayer` is
constructed when the scene starts and torn down at `EndOfMedia`, so between plays there is
no decoder and nothing doing work. The bar widget replaced Qt's `AnimatedSprite` with a
clipped `Image` for the same reason — `QQuickSpriteEngine` ticks even when stopped, which
cost 3.25% against 0.08% for a static image.

Every output gets its own decoder, so playback cost scales with monitor count.

## A matching theme

There's a **Retro 1970s** Omarchy theme built from the same palette as the `seventies`
scene — avocado, harvest gold, burnt orange, walnut:

```bash
omarchy theme install https://github.com/mrjamesmyers/omarchy-retro-1970s-theme.git
```

Note that selecting any animated wallpaper here covers your theme's background. Setting
`wallpaper` back to empty gives it back.

## Non-goals

- Not a screensaver, not a video player, not a wallpaper manager.
- No sudo, no install hooks, no system modification. It's QML and a folder of assets.
- It does not touch your theme, your background, or anything outside its own settings.

## Made with AI

The gremlins, the bumper, and all nine wallpapers are AI-generated and hand-cut. Saying so
up front because DHH labels his own that way and you deserve to know what you're
installing. The QML is hand-written.

## Credits

Built by [James Myers](https://github.com/mrjamesmyers). MIT licensed.

Not affiliated with, sponsored by, or endorsed by Omarchy, the Omacom Foundation, or
37signals.
