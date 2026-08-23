# Gremlins

**A boot bumper for Omarchy Quattro.** Gremlins haul pixel crumbs out of the dark,
one of them screams **OMACHEE**, and then they're gone — three seconds, once, and your
desktop is yours.

> The R is silent. That's the joke, and also the point.

```bash
omarchy plugin add https://github.com/mrjamesmyers/omarchy-gremlins.git --enable
```

---

## What it does

- **Plays once on login.** Not a loop, not a screensaver. Three seconds, then nothing.
- **Hands off to a wallpaper.** The bumper flashes out into a companion background from the
  same world — gremlins wandering off with your pixels — so the desktop reads as the
  continuation of the animation rather than a cut to something unrelated.
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

## Cost

The whole argument for this design is that it's cheap. On this machine, playback costs
`<measured>` for three seconds and returns to baseline immediately after. Nothing runs once
the bumper is done. If you turn loop mode on, that's on you — and it's why it's off by
default.

## Settings

Inline on the plugin entry in `~/.config/omarchy/shell.json`:

| Setting | Default | What it does |
|---|---|---|
| `source` | shipped bumper | Path to your own video or animated WebP |
| `playOnLogin` | `true` | Play once when the shell starts |
| `loop` | `false` | Keep playing forever. Costs GPU. Off for a reason. |
| `sound` | `true` | The scream |

**Bring your own bumper.** Point `source` at anything. The gremlins are the default, not
the product — the product is the shape.

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
