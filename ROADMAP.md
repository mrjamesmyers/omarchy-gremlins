# Closing the gap: an Omarchy plugin roadmap

*Second edition, August 2026. Written against Omarchy 4 "Quattro", the Quickshell
plugin API, and the full community registry.*

---

## 0. Correction to the first edition

**The first edition of this document was wrong, and wrong in a way that invalidated its
central claim.** It reported an ecosystem of fifteen third-party plugins and concluded
that "fourteen of fifteen are things you look at." That number came from Okomart
(`brianblakely/omarchy-plugins`), a small storefront — not from the community registry,
which was unreachable from the machine this was written on.

The actual registry is `HANCORE-linux/omarchy-plugin-marketplace`, published at
omarchyplugins.com. It lists **1,099 plugins across 1,097 source repositories.**

Three specific claims in the first edition were false. There *is* a cast plugin, there
*is* a LocalSend plugin, and there *is* a UniFi plugin. Section 4 gives the head-to-head.

Everything below is derived from `registry.json` in that repository, read directly.

### What the registry does and does not tell you

It carries plugin id, repository URL, category, tags, validated commit, and security
baseline status. It does **not** carry descriptions — those are fetched from each repo at
site build time. So keyword analysis here runs over ids, repository slugs and tags only.

Omarchy repos are conventionally named `omarchy-<thing>`, which makes that a good signal,
but it is not a perfect one: a plugin with an oblique name will be missed. Treat "empty"
below as *"nothing in 1,099 entries names this,"* not as proof of absence.

---

## 1. What 1,099 plugins actually cover

By the registry's own categories:

| Category | Count | Share |
|---|---:|---:|
| Widgets | 382 | 35% |
| Productivity | 210 | 19% |
| System | 141 | 13% |
| Developer Tools | 87 | 8% |
| Appearance | 84 | 8% |
| Hardware | 84 | 8% |
| Desktop | 80 | 7% |
| Other | 31 | 3% |

And by what the names actually cluster on — the most frequent meaningful tokens across
plugin ids and repository slugs:

> workspaces **29** · monitor **28** · usage **24** · wallpaper **20** · lock **20** ·
> control **19** · keyboard **18** · clock **17** · calendar **16** · theme **15** ·
> vpn **15** · window **15** · dock **14** · terminal **11** · pomodoro **10**

The shape is clear and it is not a criticism: this is a **young, enthusiastic ecosystem
building desktop furniture and system telemetry.** Sixty-seven plugins touch workspaces.
Forty-six touch usage or activity tracking. Twenty-two touch VPNs. Twenty-one touch
displays.

The first edition's instinct — that device integration is the thin part — survives the
correction, but weakly and with exceptions. Continuity is genuinely covered now: six
phone-bridge plugins, five Quick Look plugins, six dictation plugins. What is thin is
narrower and more specific, and section 3 names it.

---

## 2. Method

Forty-two capabilities that a macOS or Windows user has out of the box were each tested
against all 1,099 entries, then every "empty" result was re-validated against the raw
registry text rather than the parsed fields, to catch keywords hiding in a field the
parser skipped.

A capability is **empty** when nothing in 1,099 entries names it, and **thin** when one
or two do.

---

## 3. The gaps, after correction

### Confirmed empty — nothing in 1,099 names these

| Gap | Elsewhere | Why it matters | Recommendation |
|---|---|---|---|
| **Printing** | AirPrint | Zero printer plugins. Not one. "It found my printer" is a moment that sells an operating system, and it is the single most common reason a new Linux user goes back | mDNS `_ipp._tcp` discovery plus driverless IPP Everywhere setup via `lpadmin`, queue state via `lpstat` |
| **Per-app audio routing** | Volume Mixer | Zero. Every Windows user expects to turn one app down without turning the others down | PipeWire via `pw-dump` and `wpctl` — per-app volume, mute, and output routing |
| **Text expansion** | Text Replacement | Zero. System-wide snippets on both other platforms | Front-end `espanso`, or a small `wtype`-based expander |
| **Trash / undo delete** | Bin, Recycle Bin | Zero. `gio trash` exists and nothing surfaces it | A panel over `gio trash` with restore |
| **Disk encryption status** | FileVault, BitLocker | Zero. Most Omarchy installs are LUKS and nothing shows it | `cryptsetup status` in a panel; read-only |
| **Speed test** | — | Zero listed, and **DHH publicly demoed a personal one**. Clear demand, no listing | `librespeed-cli` or `speedtest-cli` in the bar |
| **Scanning** | Image Capture | Zero real scanner plugins (two false hits) | SANE front-end |
| **Miracast** | AirPlay mirroring | Zero. The one screen-mirroring plugin drives Chromium, not Miracast | `gnome-network-displays` front-end, or park it |

### Thin — one or two exist, room for a better one

| Gap | Exists | Assessment |
|---|---|---|
| Versioned backup | 2 | `restic` and `snapshots` plugins exist. A Time-Machine-grade browser is still open |
| Wi-Fi picker | 1 | Surprisingly thin for something used daily |
| Firewall | 1 | `ufw` control is barely represented |
| Bluetooth file send | 1 | OBEX largely unaddressed, though Beam covers the real use case better |
| Screenshot + annotate | 2 | Annotation specifically is weak |
| Mic / camera privacy indicator | 1 | A genuine security affordance both other platforms ship |

### Well covered — do not build these

Workspaces (67), display management (21), VPN (22), screen-time and usage (46), focus
and DND (10), credential managers (9), phone bridges (6), Quick Look (5), dictation (6),
cloud drives (5), content search (5), night light (5), window overview (6).

**The first edition recommended Quick Look, Tailscale and dictation as the next three
builds. All three are already occupied** — five, twenty-two and six plugins respectively.
That recommendation is withdrawn.

---

## 4. Head to head: the three already built

Honest assessment against what the registry actually contains.

### Cast vs `hackxit.chromecast` — complementary

| | `hackxit.chromecast` | **Cast** |
|---|---|---|
| Approach | Headless Chromium driven over CDP | Cast protocol implemented directly |
| Casts | The desktop, mirrored | Files, URLs, DLNA |
| Needs | Node.js, Chromium, portal stack, PipeWire | `python3` |
| Transport controls | — | Play, pause, seek, volume |

**These do not overlap.** Theirs does the one thing Cast explicitly cannot — mirror the
screen. Cast does the things theirs explicitly cannot. Both should exist, and Cast's
README should say so and point at it.

### Beam vs `oma.nearby` — substantially duplicated

Both speak LocalSend. `oma.nearby` shipped first and does **more**: clipboard text
sharing, file-picker integration, PIN, cancellation. Beam's honest remaining edges are
that it ships no compiled binary — pure standard library, so it runs on ARM where
`oma.nearby`'s prebuilt x86_64 Rust binary does not — and that it accepts drag-and-drop
onto the bar.

**That is thin differentiation.** Beam is good work aimed at an occupied position.

### UniFi vs `hegjon.unifi` — redundant, and mine is worse

| | `hegjon.unifi` | **UniFi** |
|---|---|---|
| API key | **System keyring** | `0600` file |
| Data | Integration API **plus** WAN graph endpoints | Integration API only |
| History | 12-hour WAN rate graphs | Current values only |
| Notifications | Device state changes | — |
| TLS | Prompted, permissive default | **TOFU certificate pinning** |

Better on four axes out of five. **The correct move is not to publish a second one** — it
is to offer the pinning work to that project as a pull request, which is the one place
this implementation is genuinely ahead.

---

## 5. Revised build order

| # | Plugin | Closes | Registry status | Effort |
|---:|---|---|---|---|
| 1 | **Paper** | AirPrint | **empty** | ~1 day |
| 2 | **Mixer** | Volume Mixer | **empty** | ~1 day |
| 3 | **Cast** | media casting | complementary to 1 existing | done |
| 4 | Vault | FileVault status | **empty** | ~half day |
| 5 | Bin | Recycle Bin | **empty** | ~half day |
| 6 | Expand | Text Replacement | **empty** | ~1 day |
| — | *pinning PR to `hegjon.unifi`* | — | — | ~2 hours |

Printing and per-app audio lead because they are the only two entries that are
simultaneously **empty in 1,099 plugins**, **present on both other platforms**, and
**things people hit weekly**.

---

## 5b. When the answer is not a plugin

Sharing one keyboard and mouse across machines — macOS Universal Control, Windows Mouse
Without Borders — is the largest remaining parity gap, and it **cannot be a plugin.**

Capturing the pointer at a screen edge needs `wlr-layer-shell`. Injecting it on the other
machine needs `wlr-virtual-pointer-unstable-v1` and `virtual-keyboard-unstable-v1`. None
is reachable from QML, none is reachable from Python without a compiled binding, and
`uinput` needs privileges a cloned plugin has no business asking for. The helper-daemon
pattern that carried the other nine plugins runs out of road here.

So it went upstream instead, as a contribution to `basecamp/omarchy`: see
[`upstream/omarchy/`](upstream/omarchy/). It wires up [Lan Mouse](https://github.com/feschber/lan-mouse),
which already speaks all three protocols, is written in Rust, and is in Arch's `extra`
repository — one `omarchy-pkg-add` away, no AUR detour.

The shape follows Omarchy's own conventions rather than inventing any:
`omarchy install service lan-mouse` next to `omarchy-install-service-sunshine`,
`omarchy setup input sharing` next to `omarchy-setup-security-*`, menu rows under
_Install > Service_ and _Setup_, a manual section, and 18 tests in Omarchy's own
`test/shell.d/` harness. No new command group was needed.

Two rough edges in lan-mouse's CLI are wrapped, both squarely on a first-time user's
path: `add-client` cannot set a position, and nothing reports your own certificate
fingerprint — which is exactly the value pairing needs on the *other* machine.

**The rule this earned:** *check whether the gap is a plugin-shaped gap before assuming
the plugin API is where it closes.* Four of the ten plugins here could have been Omarchy
patches; this one could only be.

---

## 6. Design rules

Unchanged by the correction, and now with a sixth earned the hard way.

**Join a network, do not start one.** Beam speaks LocalSend rather than inventing a
protocol — the right instinct, applied to a position someone had already taken.

**No pip, no sudo, no install hooks.** Omarchy plugins are cloned, not installed.

**QML for pixels, a helper for protocol.** QML cannot join a multicast group or speak a
binary protocol over TLS. Moving that to a helper makes the interesting half testable
without a compositor — a hundred tests run here, and they caught four real bugs.

**One daemon, not one per monitor.** The bar instantiates a widget per screen.

**Be honest about what does not work.** Cast lists Apple TVs greyed out and says why.

**Survey before you build.** Two hours reading the registry would have redirected two of
the three plugins in the first edition. The cost of not checking was not a wasted
afternoon — it was a recommendation set that pointed at five occupied positions.
