# Share one keyboard and mouse across machines

A contribution prepared for [basecamp/omarchy](https://github.com/basecamp/omarchy), not a plugin. Input capture and injection need Wayland protocols no Quickshell plugin can reach, so this belongs in Omarchy itself.

- **Patch:** [`input-sharing.patch`](input-sharing.patch) — applies to `quattro`, 7 files, +621
- **Readable copies:** [`files/`](files/) — the four new files, so you can read them without applying anything
- **Checks:** `./verify.sh` (drift), `./verify.sh --full` (applies to upstream and runs the tests there)

## The gap

Omarchy's own manual has a translation table for people arriving from macOS or Windows. It has a row for AirDrop. It has nothing for Universal Control or Mouse Without Borders — put a second machine on the desk and you need a second keyboard for it.

The patch adds that row, and the feature behind it.

## Why not a plugin

Capturing the pointer at a screen edge needs `wlr-layer-shell`; replaying it on the other machine needs `wlr-virtual-pointer-unstable-v1` and `virtual-keyboard-unstable-v1`. None is reachable from a QML plugin or from Python without a compiled binding, and `uinput` needs privileges Omarchy does not hand out. [Lan Mouse](https://github.com/feschber/lan-mouse) already speaks all three, is written in Rust, and is **in Arch's `extra` repository** — so `omarchy-pkg-add` installs it with no AUR detour.

## What it adds

| | |
| --- | --- |
| `omarchy install service lan-mouse` | Installs Lan Mouse, starts it with the graphical session, opens UDP 4242 for private LANs and Tailscale |
| `omarchy setup input sharing` | Pairs a machine — wizard, or `add` / `authorize` / `list` / `remove` / `status` / `fingerprint` |
| _Install > Service > Lan Mouse_ | Menu row, greyed out once installed |
| _Setup > Input Sharing_ | Menu submenu, hidden until Lan Mouse is installed |
| `default/systemd/user/lan-mouse.service` | Only installed when the system has no unit of its own |
| `manual/34-keyboard-mouse-trackpad.md` | New section |
| `manual/03-coming-from-mac-or-windows.md` | The missing translation row |

## The two rough edges it smooths

Both sit directly on the path a first-time user walks, which is why they are worth wrapping rather than documenting around.

**`add-client` takes no position.** A new client lands wherever lan-mouse defaults and has to be moved afterwards, so `add` does both. Working out *which* client is new is the fiddly part: `add-client` prints nothing, and ids are neither sequential nor sorted, so neither the highest nor the last is reliable. The command diffs the id list around the call. The test pins this with an id of `2` added among `3` and `11` — a value that is neither the highest nor the one that sorts last, so both shortcuts fail it.

**There is no command to read your own fingerprint.** Pairing needs it on the *other* machine, and the GTK frontend is the only thing that shows it. `fingerprint` derives it from the certificate the daemon writes on first run:

```sh
openssl x509 -in ~/.config/lan-mouse/lan-mouse.pem -noout -fingerprint -sha256
```

That is the same SHA-256 over the DER certificate that `generate_fingerprint()` in `src/crypto.rs` computes, lowercased. openssl skips the private key sharing the PEM. Checked against a real certificate, not assumed.

## Verified against source, not guessed

Every fact the patch depends on was read out of `feschber/lan-mouse@392af44` or `basecamp/omarchy@43bfe9b`:

| Claim | Where |
| --- | --- |
| In Arch `extra`, so `pacman -S lan-mouse` works | lan-mouse `README.md` |
| `lan-mouse daemon`, `lan-mouse cli <cmd>` | `src/main.rs`, `lan-mouse-cli/src/lib.rs` |
| Subcommands `add-client` `set-position` `authorize-key` `save-config` `list` `remove-client` | `lan-mouse-cli/src/lib.rs` |
| `--ips` appends, so one flag per address | clap `Vec<IpAddr>` with `#[arg(long)]` |
| `list` prints `id N: host:port (pos) …` | `lan-mouse-cli/src/lib.rs` |
| Positions are `left` `right` `top` `bottom` | `lan-mouse-ipc/src/lib.rs` |
| UDP 4242 by default, DTLS encrypted | `README.md`, `config.toml` |
| Certificate at `$XDG_CONFIG_HOME/lan-mouse/lan-mouse.pem` | `src/config.rs` |
| Fingerprint is SHA-256 of DER, lowercase, colon-separated | `src/crypto.rs` |
| Release bind defaults to Ctrl + Shift + Super + Alt | `src/config.rs` `DEFAULT_RELEASE_KEYS` |
| Modifiers drop when a non-`layer-shell` sender drives a wlroots receiver | `README.md` caveats — documented in the manual section |
| Sunshine is the closest existing installer to copy | `bin/omarchy-install-service-sunshine` |
| Every `bin/omarchy-*` needs `# omarchy:summary=` | `test/cli` enforces it |

**Not verified:** whether Arch's `lan-mouse` package ships its own systemd user unit. The installer handles both cases — it lays down Omarchy's copy only when `systemctl --user cat lan-mouse.service` finds nothing, so a packaged unit is never shadowed.

**Not run against real hardware.** The daemon has not been exercised on two machines; that needs two boxes and a compositor. What *is* tested is every decision the two commands make, against a stubbed lan-mouse.

## Testing

18 tests in Omarchy's own `test/shell.d/` harness, hermetic — they stub `lan-mouse`, `systemctl` and `hostname`, so they need neither the package nor a compositor.

```
$ bash test/shell.d/input-sharing-test.sh
ok - every command says so when Lan Mouse is not installed
ok - status fails when Lan Mouse is not installed
ok - fingerprint fails before the daemon has written a certificate
ok - fingerprint matches the SHA-256 of the DER certificate
ok - fingerprint is lowercase and colon-separated
ok - add rejects a position that is not an edge, before touching lan-mouse
ok - add without a hostname fails
ok - add passes the hostname to add-client
ok - add finds the new id among existing clients and positions it
ok - add persists the configuration
ok - add prints the pairing command for the other machine
ok - add passes each address as its own --ips flag
ok - authorize forwards the name and key, and persists it
ok - remove rejects anything that is not an id
ok - remove forwards the id
ok - a stopped daemon is reported as a stopped daemon, not a connection failure
ok - status reports a stopped daemon and still shows this machine's key
ok - status reports a running daemon and this machine's name
```

Against upstream `quattro`:

- `test/cli` — passes, including the metadata scan over every `bin/omarchy-*`
- `test/shell` — 191 files, the same 21 environmental failures as the unmodified tree (they need Hyprland, snapper, or real hardware). Confirmed by running the suite on a pristine `quattro` worktree and diffing the failure lists; they are identical.
