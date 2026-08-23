# Cast

**Put it on the big screen.** Cast finds the Chromecasts, Google TVs, Nest displays and
DLNA televisions on your network and plays local files or URLs on them, with transport
controls in the bar.

```bash
omarchy plugin add https://github.com/mrjamesmyers/omarchy-cast.git --enable
omarchy bar plugin add io.github.mrjamesmyers.cast
```

Plugins run unsandboxed inside your shell process. Read the source before you enable
anything, including this.

---

## What it talks to

| Family | What that covers | Status |
|---|---|---|
| **Google Cast** | Chromecast, Chromecast with Google TV, Nest Hub, and the "Chromecast built-in" badge on most Sony, TCL, Hisense and Philips sets | Full — discover, play, pause, seek, volume, stop |
| **DLNA / UPnP** | The MediaRenderer nearly every smart TV still answers to, including Samsung and LG | Play, pause, seek, stop |
| **AirPlay** | Apple TV, AirPlay 2 televisions | **Discovered and listed, not driveable** — see below |

### About AirPlay

Cast will find your Apple TV and show it in the list, greyed out. It cannot play to it,
and says so rather than spinning. Apple's modern AirPlay video path requires a pairing
and key-exchange handshake that Apple has never published; every Linux implementation
that claims otherwise either targets pre-2018 hardware or reimplements a leaked key.
Listing the device and being honest about it beats a button that silently fails.

## How it works

There is no browser involved and nothing to install on the television.

- **Discovery** is mDNS for `_googlecast._tcp` and `_airplay._tcp`, plus SSDP for UPnP
  MediaRenderers — implemented directly, because Omarchy does not ship Avahi and a
  plugin that needs `sudo pacman -S` to find your TV is a plugin most people never get
  working.
- **Google Cast** is the real CASTV2 protocol: protobuf frames over TLS on port 8009,
  with the connection, heartbeat, receiver and media namespaces. There is a protobuf
  encoder in `helper/castd.py` — all seven fields of `CastMessage`, which is what the
  protocol needs and a great deal less than a dependency.
- **Local files** are served to the television over HTTP from a short-lived server bound
  to the address that specific receiver can reach, at a URL guarded by a random token.
  Byte ranges are supported, because without them the receiver cannot seek and some
  firmwares refuse to start at all.

## Using it

- **Drag a file onto the bar widget** — or onto the open panel — then click a screen.
- **From a terminal:** `omarchy-shell omarchy.cast play ~/film.mkv`, or pass a URL.
- **While casting**, the bar cell is the transport: left-click toggles play/pause,
  middle-click stops, the scroll wheel changes the television's volume, right-click
  opens the panel.

## Settings

| Setting | Default | What it does |
|---|---|---|
| `hideWhenIdle` | `false` | Remove the cell from the bar when nothing is casting |
| `rescanSeconds` | `300` | How often to look for new devices in the background |
| `lastTarget` | — | The device used last. Managed automatically |

## Requirements

`python3`, already present on Omarchy. No pip, no sudo, no install hooks, no
third-party repos — the plugin is QML and one standard-library Python file.

## Tests

```bash
python3 helper/test_castd.py
```

Forty-nine cases. The Cast tests run against a fake receiver that speaks genuine CASTV2
framing over TLS, so an encoder that is wrong by one byte fails all of them. The rest
cover the mDNS parser (including a compression-pointer loop, which must raise rather
than hang), and the media server's range handling against real HTTP requests.

Two bugs those tests caught, both of which would have shipped:

- `stop()` revoked the media server's token *after* the URL was handed to the
  television, so casting any local file 404'd — a spinner on the TV and no error
  anywhere.
- The read and heartbeat threads used one TLS socket concurrently. OpenSSL does not
  guarantee that, so sessions died at random intervals. All socket I/O is now on a
  single thread with a write queue.

## Known limits

- **No screen mirroring.** Cast sends a file or a URL to a television. Mirroring your
  desktop to a Chromecast needs Google's proprietary mirroring protocol, which is not
  the same thing as the Cast media protocol and is not published.
- **The television does the decoding.** Cast hands over a URL; if the receiver cannot
  play that codec, it will not play. H.264 in MP4 works everywhere; MKV depends on
  the device.
- **Discovery needs multicast.** Guest and enterprise wifi frequently block it.

## Non-goals

Not a media player, not a transcoder, not a library manager. It finds screens and puts
things on them.

## Credits

Built by [James Myers](https://github.com/mrjamesmyers). MIT licensed.
Not affiliated with, sponsored by, or endorsed by Google, Ubiquiti, Apple, Omarchy,
the Omacom Foundation, or 37signals.
