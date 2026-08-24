# Mixer

**Turn one application down without turning the rest down.** A per-application volume
mixer in the Omarchy bar, with output routing: send the browser to the headphones and
leave the music on the speakers.

```bash
omarchy plugin add https://github.com/mrjamesmyers/omarchy-mixer.git --enable
omarchy bar plugin add io.github.mrjamesmyers.mixer
```

Plugins run unsandboxed inside your shell process. Read the source before you enable
anything, including this.

---

## Why this exists

Windows has shipped a per-application volume mixer since Vista, and everybody who has
used one expects it. Nothing among the 1,099 plugins in the Omarchy registry did this
when Mixer was written.

`pavucontrol` exists and is good, but it is a separate window you have to go and find,
which is not the same thing as a slider in the bar. The difference between "open an app,
find the tab, drag the slider" and "scroll on the bar" is the difference between a thing
you do and a thing you do not bother doing.

## What it does

- **A slider per application**, live while you drag it.
- **Mute one app** without touching anything else.
- **Route an app to a different output** — click the device name under a stream to send
  it to the next one. With two devices, which is the usual case, that is one click.
- **Scroll on the bar widget** to change the current output's volume. Middle-click mutes.
- **Switch output properly.** Picking new headphones moves what is *already playing* to
  them, not just whatever starts next. PulseAudio's own behaviour is the latter, and it
  is almost never what anyone means.

## How it works

Talks to PipeWire through `pactl`, which ships with `pipewire-pulse` and speaks JSON.

Not `pw-dump`: that exposes the raw graph, which is more powerful and considerably more
work — routing a stream to another sink means finding its link objects and rebuilding
them, where `pactl` calls it `move-sink-input` and does it in one command.

**Updates are event-driven.** `pactl subscribe` emits a line whenever anything in the
audio graph changes, so the helper re-reads on change rather than polling a slider
position sixty times a minute. Identical reads are dropped, so an idle machine emits
nothing at all.

## Settings

| Setting | Default | What it does |
|---|---|---|
| `showStreamCount` | `true` | A count of apps actually making noise, next to the icon |
| `moveStreamsOnSwitch` | `true` | Move playing audio when you pick a new output |
| `scrollStep` | `5` | Percent per notch of the scroll wheel |
| `allowOverdrive` | `false` | Let sliders past 100%. Useful for quiet recordings, unkind to speakers |

## Requirements

`python3` and `pactl`. Both are already on Omarchy — `pactl` comes with
`pipewire-pulse`, which is how Omarchy does audio. If it is somehow missing, the widget
says so plainly rather than showing an empty box.

No pip, no sudo, no install hooks.

## Tests

```bash
python3 helper/test_mixerd.py
```

Thirty-eight cases, driven by real-shaped `pactl -f json` output and by capturing the
exact argv the daemon would run — because the whole plugin is a translation layer
between PulseAudio's JSON and a slider, and a wrong argv means somebody's volume changes
on the wrong application.

Three things those tests pinned down:

- **A hard-panned stream must read by its loudest channel, not the mean.** Averaging
  makes a stream panned fully left show as 50%, and the moment anyone touches the slider
  it snaps to centre and destroys their panning.
- **Only the binary name gets capitalised.** `application.name` is a display string the
  app chose, and plenty are deliberately lowercase — `mpv`, `qutebrowser`, `yt-dlp`.
  Title-casing those is not a tidy-up, it is getting the name wrong.
- **The binary name outranks `media.name`.** `media.name` is usually a generic stream
  label, so preferring it turns Spotify into "Playback" in the list.

## Known limits

- **Output streams only.** Microphones and recording streams are not shown yet.
- **Volume is per-stream, not per-application.** An app with several streams gets
  several rows, because that is what PulseAudio exposes.
- **Above 100% is real gain**, not a trick. It will distort, and it can damage speakers.

## Removing it

```bash
omarchy bar plugin remove io.github.mrjamesmyers.mixer
omarchy plugin disable io.github.mrjamesmyers.mixer
omarchy plugin remove io.github.mrjamesmyers.mixer
```

Mixer keeps no state outside its own plugin directory. Volumes it changed stay where you
left them, because those belong to PipeWire, not to this plugin.

## Credits

Built by [James Myers](https://github.com/mrjamesmyers). MIT licensed.
Not affiliated with, sponsored by, or endorsed by Omarchy, the Omacom Foundation, or
37signals.
