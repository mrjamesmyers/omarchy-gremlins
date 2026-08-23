# Gremlins

**A boot bumper for Omarchy Quattro.** Gremlins haul pixel crumbs out of the dark,
one of them screams **OMACHEE**, and then they're gone — three seconds, once, and your
desktop is yours.

> The R is silent. That's the joke, and also the point.

![Gremlins](preview.gif)

```bash
omarchy plugin add https://github.com/mrjamesmyers/omarchy-gremlins.git --enable
```

Omarchy will show you the repo and ask you to confirm — plugins run unsandboxed inside the
shell process, so read the source before you enable anything, including this.

---

## What it does

- **Plays once on login.** Not a loop, not a screensaver. Three seconds, then nothing.
- **Comes with matching wallpapers.** The bumper flashes to white and hands you back your
  desktop. Two companion backgrounds from the same world ship alongside it — gremlins
  wandering off with your pixels — so the desktop can read as the continuation of the
  animation. **You install them; the plugin never touches your wallpaper on its own.**
- **Puts a gremlin in your bar.** Click it to replay. It's drawn in your theme's foreground
  colour, so it follows every Omarchy theme, including ones that don't exist yet.
- **Loops only if you ask.** There's a setting. It's off by default, and it should be.

## Why it's shaped like this

DHH, on the 19th, thinking out loud about putting video into Omarchy:

> "I'm thinking one-off on boot by default. Then if you want something that runs all the
> time, you select that yourself."

And Jason Fried, in the same thread:

> "Constraint should be 3 seconds max, something like that. Like a Netflix bumper."

So: three seconds, one-off on boot, looping is opt-in. This plugin is an attempt at the
shape they were describing. The last-frame-becomes-the-background idea came from
[@rootkid](https://x.com/rootkid) and [@mehieltwit](https://x.com/mehieltwit) in the same
replies.

## Requirements

`qt6-multimedia` with the FFmpeg backend — both already present on Omarchy Quattro, so
there is nothing to install. No sudo, no install hooks, no third-party repos.

The bumper ships as **H.264 mp4**, not animated WebP. Omarchy's Qt has no WebP image
plugin at all (`/usr/lib/qt6/plugins/imageformats/` is gif/ico/jpeg/pdf/svg), so
`AnimatedImage` cannot decode WebP here — but `qt6-multimedia-ffmpeg` plays mp4 happily,
and mp4 carries its own audio track, so the scream needs no separate player.

## Cost

The whole argument for this design is that it's cheap: three seconds of decode, then
nothing. The overlay tears its own layer surface down when playback ends, so once the
bumper is over there is no surface, no decoder, and no process doing work. If you turn
loop mode on, that's on you — and it's why it's off by default.

## Settings

Inline on the plugin entry in `~/.config/omarchy/shell.json`:

| Setting | Default | What it does |
|---|---|---|
| `source` | shipped bumper | Path to your own video file |
| `playOnLogin` | `true` | Play once when the shell starts |
| `loop` | `false` | Keep playing forever. Costs GPU. Off for a reason. |
| `sound` | `true` | The scream |

**Bring your own bumper.** Point `source` at any video file. The gremlins are the default,
not the product — the product is the shape.

## The wallpapers

Two backgrounds ship in `assets/`, built to stay out of your way: near-black, wide open
through the centre, with the gremlins small in one corner.

```bash
omarchy-theme-bg-set ~/.config/omarchy/plugins/io.github.mrjamesmyers.gremlins/assets/wallpaper-cool.jpg
```

Swap `cool` for `warm` if you prefer the warmer grade. To keep them in your theme's
rotation instead, drop them in `~/.config/omarchy/backgrounds/<your-theme>/`.

## Known limits

- **Single monitor.** The overlay creates one `PanelWindow`, so on a multi-head setup the
  bumper plays on one screen rather than all of them. Fixing that means a player per output;
  it's on the list, it isn't in 0.1.
- Tested on Omarchy 4.0.0 with a 1920x1080 + 3840x2160 pair.

## Non-goals

- Not a screensaver, not a video player, not a wallpaper manager.
- No sudo, no install hooks, no system modification. It's QML and two asset files.
- It will not make your laptop battery happy if you turn loop mode on. Don't.

## Made with AI

The gremlins, the bumper, and the wallpaper are AI-generated and hand-cut. Saying so up
front because DHH labels his own that way and you deserve to know what you're installing.
The QML is hand-written.

## Credits

Built by [James Myers](https://github.com/mrjamesmyers). MIT licensed.

Not affiliated with, sponsored by, or endorsed by Omarchy, the Omacom Foundation, or
37signals.
