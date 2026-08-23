# Closing the gap: an Omarchy plugin roadmap

*Assessment and plan, August 2026. Written against Omarchy 4 "Quattro" and the
Quickshell plugin API.*

---

## 1. Where the ecosystem actually is

Quattro rebuilt the entire desktop shell as a plugin host. Bar, launcher, menus,
notifications, OSDs, control panels, lock screen and polkit agent all live in one
long-running Quickshell process, and third parties get the same six plugin kinds the
first-party components use: `bar-widget`, `bar`, `panel`, `overlay`, `menu`, `service`.
That is a genuinely good foundation, and it is nine months old.

**First-party covers the desktop furniture.** Workspaces, active window, clock, weather,
media (MPRIS), system tray, battery, keyboard layout, microphone, update indicator,
Bluetooth device list, notifications, lock.

**Third-party is where the interesting number is.** The main registry (Okomart) lists
fifteen plugins:

> Blink · Bluetooth codec · Codex Notifications · Flight Radar · Omacal · Omadoro ·
> OmaHUD · OmaLED · OmaNetWatch · Omanews · Omanote · Omashot · Omastonk · Peek ·
> World Time

Read that list by category rather than by name:

| Category | Count | Examples |
|---|---:|---|
| Cosmetic / window chrome | 4 | Blink, OmaHUD, OmaLED, Peek |
| Informational tickers | 4 | Flight Radar, Omanews, Omastonk, World Time |
| Small utilities | 5 | Omacal, Omadoro, Omanote, Omashot, Codex Notifications |
| Hardware / device integration | **2** | Bluetooth codec, OmaNetWatch |

Fourteen of the fifteen are things you *look at*. Almost nothing in the ecosystem
**talks to another device.** That is not a criticism of the authors — it is a precise
description of where the frontier is, and it is exactly where the macOS and Windows gap
lives. Nobody misses Windows because it has a stock ticker.

### An ecosystem-level defect worth fixing upstream

The manifest schema has a `barWidget.schema` field: a declarative description of a
plugin's settings, with types, labels, defaults and help text. The shell stores it and
`BarWidgetRegistry.metadataFor()` exists to read it — **but nothing renders it.** No
shipped panel uses the `qs.Ui` form-control set either.

The consequence: every plugin that wants settings hand-builds a settings panel out of
`qs.Ui` primitives, re-implementing keyboard navigation, cursor state and persistence
each time. All three plugins below do exactly that, because there is no alternative.

**Recommendation: contribute the schema renderer upstream.** It is a bounded piece of
work against an API that already exists, it deletes a few hundred lines from every
plugin that has settings, and it is the single highest-leverage contribution available
to the plugin ecosystem right now. Worth doing before writing plugin number four.

---

## 2. The three questions, answered

**Is there a plugin for casting to a big-screen TV?** No. Nothing in the registry, and
nothing first-party. The Linux tooling that exists (`catt`, `mkchromecast`, Cast to TV
for GNOME) is either a Python package you must install yourself or tied to a desktop
Omarchy does not run. → **Built. See `plugins/omarchy-cast`.**

**Is there an AirDrop feature?** No. Not in the registry, not first-party, and no
Wayland desktop has one. → **Built. See `plugins/omarchy-beam`.**

**Is there a UniFi / Ubiquiti plugin?** No. OmaNetWatch does HTTP/TCP endpoint
monitoring, which is a different thing. → **Built. See `plugins/omarchy-unifi`.**

---

## 3. The gap map

Every row is a thing a Mac or Windows user has and an Omarchy user does not. Scored on
**value** (how often it bites, how loudly people complain) and **feasibility** (can it
be a plugin at all, and what does it need on the box).

### Tier 1 — Continuity: one device talking to another

This is the whole gap. It is where Apple spent fifteen years and where Linux has spent
almost none.

| Gap | Mac / Windows | Omarchy today | Recommendation | Value | Feasibility |
|---|---|---|---|:---:|:---:|
| **File transfer to phones** | AirDrop / Nearby Share | nothing | Speak **LocalSend** — real clients already on iOS, Android, macOS, Windows | ★★★★★ | ★★★★★ |
| **Cast to television** | AirPlay / Cast / Miracast | nothing | **Google Cast protocol** natively + DLNA for the rest | ★★★★★ | ★★★★☆ |
| **Phone bridge** — notifications, SMS, calls, remote input | iPhone Mirroring / Phone Link | nothing | Front-end **KDE Connect**'s D-Bus API; the daemon is mature and has iOS and Android apps. A bar widget for battery, notifications, "find my phone", send-to-phone | ★★★★★ | ★★★★☆ |
| **Universal clipboard** | Handoff | nothing | Falls out of the KDE Connect bridge for free | ★★★★☆ | ★★★★☆ |
| **Phone as webcam** | Continuity Camera | nothing | `v4l2loopback` + KDE Connect or DroidCam. Needs a **kernel module**, so it cannot be a pure plugin | ★★★☆☆ | ★★☆☆☆ |
| **Tablet as second screen** | Sidecar | nothing | Hard on Wayland. Park it | ★★☆☆☆ | ★☆☆☆☆ |

### Tier 2 — Files: finding things and not losing them

| Gap | Mac / Windows | Omarchy today | Recommendation | Value | Feasibility |
|---|---|---|---|:---:|:---:|
| **Quick Look** — spacebar preview | Quick Look | nothing | An `overlay` plugin plus `omarchy-glance <path>`, bound in the launcher and file manager. Omarchy's Qt already ships **PDF and SVG image plugins** and `qt6-multimedia`, so images, PDFs, video, audio and syntax-highlighted text are all reachable **with zero new dependencies** | ★★★★★ | ★★★★★ |
| **Content search** | Spotlight / Windows Search | launcher finds files by *name* | A panel over `ripgrep` + `fd`, both already present. Full indexing (`tracker`, `recoll`) is a second phase | ★★★★☆ | ★★★★☆ |
| **Versioned backup** | Time Machine / File History | **nothing** | `restic` to a user-owned destination — needs no sudo — plus a snapshot browser. On btrfs installs, `snapper` integration | ★★★★★ | ★★★☆☆ |
| **Cloud drives** | iCloud / OneDrive | nothing | `rclone mount` manager: mount state, sync status, a bar indicator | ★★★☆☆ | ★★★★☆ |
| **Trash and undo-delete** | Bin / Recycle Bin | `gio trash` exists, no UI | Small panel. Cheap win | ★★☆☆☆ | ★★★★★ |

### Tier 3 — Input

| Gap | Mac / Windows | Omarchy today | Recommendation | Value | Feasibility |
|---|---|---|---|:---:|:---:|
| **Dictation** | Dictation / Win+H | **nothing** | Hotkey → record → **`whisper.cpp` locally** → type via `wtype`. Entirely offline, and a genuinely better product than either incumbent because nothing leaves the machine. Needs a model download, so it must degrade honestly on first run | ★★★★★ | ★★★☆☆ |
| **Text replacement / snippets** | system-wide | nothing | Front-end `espanso` | ★★★☆☆ | ★★★★☆ |
| **Clipboard history** | Win+V | third-party (omaclip) | Covered well enough | ★★☆☆☆ | — |
| **Emoji / character picker** | Ctrl+Cmd+Space | in the launcher | Covered | ★☆☆☆☆ | — |

### Tier 4 — Hardware

| Gap | Mac / Windows | Omarchy today | Recommendation | Value | Feasibility |
|---|---|---|---|:---:|:---:|
| **Printers** | AirPrint, zero setup | CUPS, no UI | mDNS `_ipp._tcp` discovery + driverless IPP Everywhere setup. "It found my printer" is a moment that sells an OS | ★★★★☆ | ★★★☆☆ |
| **Scanners** | Image Capture | nothing | SANE front-end | ★★☆☆☆ | ★★★☆☆ |
| **Per-app audio routing** | Windows volume mixer | `pavucontrol` | Bar panel over PipeWire | ★★★☆☆ | ★★★★☆ |
| **Battery health** | detailed | basic | `upower` detail panel: cycles, design capacity, wear | ★★☆☆☆ | ★★★★★ |
| **Bluetooth file transfer** | OBEX | nothing | Beam covers the real use case better | ★☆☆☆☆ | — |

### Tier 5 — Network and home

| Gap | Mac / Windows | Omarchy today | Recommendation | Value | Feasibility |
|---|---|---|---|:---:|:---:|
| **VPN / mesh status** | native UI | nothing | **Tailscale** bar widget: connection state, exit-node picker, peer list, MagicDNS. `tailscale status --json` is a clean, stable interface. Lowest-effort high-value item on this page | ★★★★☆ | ★★★★★ |
| **Network gear** | vendor apps | nothing | UniFi — done | ★★★☆☆ | ★★★★☆ |
| **Home automation** | Home / Alexa | nothing | Home Assistant REST: scenes and lights in the bar | ★★★☆☆ | ★★★★☆ |

### Tier 6 — Attention and security

| Gap | Mac / Windows | Omarchy today | Recommendation | Value | Feasibility |
|---|---|---|---|:---:|:---:|
| **Focus modes** | scheduled, per-app | DND toggle | Scheduled profiles, per-app notification rules | ★★★☆☆ | ★★★★☆ |
| **Screen time** | usage reports | nothing | Hyprland window events → daily report | ★★★☆☆ | ★★★★☆ |
| **Credential manager** | Keychain / Hello | `gnome-keyring`, no UI | Secrets browser | ★★★☆☆ | ★★★☆☆ |

---

## 4. What to build, in what order

Ranked by value × feasibility, with the three that already exist struck through.

| # | Plugin | Closes | Effort | Status |
|---:|---|---|---|---|
| 1 | ~~**Beam**~~ | AirDrop | — | **shipped** |
| 2 | ~~**Cast**~~ | AirPlay / Cast to TV | — | **shipped** |
| 3 | ~~**UniFi**~~ | vendor network app | — | **shipped** |
| 4 | **Glance** | Quick Look | ~2 days | next |
| 5 | **Mesh** | Tailscale / VPN status | ~1 day | next |
| 6 | **Dictate** | voice typing | ~3 days | next |
| 7 | **Companion** | Phone Link / Handoff | ~4 days | phase 3 |
| 8 | **Timeline** | Time Machine | ~4 days | phase 3 |
| 9 | **Paper** | AirPrint | ~3 days | phase 3 |
| 10 | **Find** | Spotlight content search | ~2 days | phase 4 |
| — | *schema renderer* | *upstream contribution* | *~2 days* | *do this early* |

**Why Glance and Mesh come next.** Glance has the best value-to-effort ratio on the
page: Quick Look is the single most-missed macOS feature, and Omarchy's Qt already ships
every decoder it needs, so it costs nothing on the box. Mesh is a day of work for
something a developer audience touches several times daily.

**Why Dictate is the one with the highest ceiling.** Local Whisper transcription is not
a worse version of Apple's dictation — it is a better one, because nothing is uploaded.
It is also the item that fits Omarchy's stated direction as an agentic desktop most
naturally. It is third rather than first only because a model download breaks the
no-install-hooks rule and has to be handled honestly.

---

## 5. Design rules these three established

Worth keeping for the next seven.

**Join a network, do not start one.** Beam does not invent a transfer protocol. The gap
AirDrop leaves is not "there is no Linux file-transfer tool" — there are dozens. The gap
is that none of them are on the other person's phone. LocalSend already has clients
everywhere, so Beam speaks LocalSend and the phone needs nothing.

**No pip, no sudo, no install hooks.** Omarchy plugins are *cloned*, not installed. A
plugin that needs a package manager to work is a plugin most people never get working.
All three use the Python standard library and tools already on the box.

**QML for pixels, a helper for protocol.** QML cannot join a multicast group, listen on
a port, speak a binary protocol over TLS, or stream a 4 GB file without pulling it
through the shell's heap. Pushing that into a helper process is not just a workaround —
it makes the interesting half **testable without a compositor**. One hundred tests run
in this repository over real sockets and real TLS.

**One daemon, not one per monitor.** The bar instantiates a widget per screen. Anything
that binds a port sits behind `Loader { active: ownsDaemon }`.

**Be honest about what does not work.** Cast lists Apple TVs greyed out and says why,
rather than offering a button that spins forever. An honest absence beats a silent
failure every time.

**Secrets do not go in `shell.json`.** It is a dotfile; dotfiles end up in public
repositories. UniFi keeps its API key in a `0600` file and refuses a world-readable one.

---

## 6. What the tests caught

Four bugs, all of which would have shipped, none of which a compositor would have
revealed:

1. **Beam** — a transfer that failed its checksum left the session marked active, so
   *every later transfer was refused* until the shell restarted.
2. **Cast** — `stop()` revoked the media-server token *after* handing the television the
   URL, so casting any local file 404'd: a spinner on the TV and no error anywhere.
3. **Cast** — the read and heartbeat threads shared one TLS socket, which OpenSSL does
   not guarantee is safe. Sessions died at random intervals.
4. **UniFi** — `PermissionError` subclasses `OSError`, and the transport caught `OSError`
   to mean "host did not answer", so a bad key file reported *"no UniFi API found at
   192.168.1.1"* and sent people to debug their network instead of their key.

Three of the four are the kind of bug that reproduces once a week and gets filed as
"flaky". Testing the protocol rather than the pixels is what surfaced them.
