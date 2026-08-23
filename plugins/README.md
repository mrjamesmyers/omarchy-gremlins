# Plugins

Three Omarchy plugins built in this repository, each self-contained in its own
directory.

| Plugin | What it closes | Registry status | Requires |
|---|---|---|---|
| [`omarchy-paper`](omarchy-paper/) | Printing — AirPrint | **nothing in 1,099 names this** | `python3`, CUPS |
| [`omarchy-mixer`](omarchy-mixer/) | Per-app volume — Volume Mixer | **nothing in 1,099 names this** | `python3`, `pactl` |
| [`omarchy-cast`](omarchy-cast/) | Cast media to TV | complements `hackxit.chromecast`, which mirrors instead | `python3` |
| [`omarchy-beam`](omarchy-beam/) | AirDrop — file transfer | overlaps `oma.nearby` | `python3`, `openssl` |
| [`omarchy-unifi`](omarchy-unifi/) | Ubiquiti network status | overlaps `hegjon.unifi`, which is better | `python3` |

The registry column matters. It was checked against the real community registry —
1,099 plugins — *after* the first three were written, which is the wrong order and is
recorded as such in `../ROADMAP.md`. Paper and Mixer were chosen from that data
rather than from a guess.

## They live here for now, but they cannot ship from here

`omarchy plugin add <git-url>` clones a repository and expects `manifest.json` at
its **root**. A plugin in a subdirectory of a repository about something else
cannot be installed. So before publishing, split each one out:

```bash
tools/split-plugin.sh omarchy-beam ../omarchy-beam
```

That preserves the plugin's own commit history rather than flattening it into a
single import commit, leaves the new repository on disk with no remote, and
prints the two commands to publish it.

## Shape

All three follow the same structure, and it is not an accident.

```
manifest.json      identity, kinds, and the bar-widget settings schema
BarWidget.qml      the bar cell - status, and the click target
Panel.qml          the panel, built from the qs.Ui primitives Omarchy's own panels use
*Core.qml          owns the helper process and holds all plugin state
helper/*.py        the protocol work, standard library only
helper/test_*.py   tests that drive the helper over real sockets
```

**Why a helper process at all.** QML cannot join a multicast group, cannot
listen on a TCP port, cannot speak a length-prefixed binary protocol over TLS,
and cannot stream a four-gigabyte file off disk without pulling it through the
shell's heap. Beam needs the first two, Cast needs the third, and both need the
fourth. So the protocol lives in Python — standard library only, no pip, no
sudo, no install hooks — and QML starts it, reads newline-delimited JSON events,
and writes newline-delimited JSON commands back.

The upside beyond capability: the interesting half of each plugin is testable
without a compositor. A hundred tests run in this repository, over real sockets
and real TLS, and between them they caught four bugs that would otherwise have
shipped — each written up in the plugin's own README.

**Why the core is a separate file.** The bar instantiates a widget per monitor.
A network daemon that binds a port does not want three of itself, so the core
sits behind `Loader { active: ownsDaemon }` and only the first screen's copy
runs it. Same guard the Gremlins widget uses for its hanging window.

## Testing on real hardware

The helper suites run anywhere. What they cannot do is meet a real printer, a
real sound card or a real Chromecast, because a CI container has none of those.

On an actual Omarchy machine:

```bash
tools/smoke-test.sh              # all five
tools/smoke-test.sh paper        # just one
```

It starts each helper, watches its event stream for a few seconds, prints what
came back, and stops it. Read-only throughout: nothing is printed, cast, sent
or changed. It is the half of the testing a cloud container cannot do.
