# Beam

**AirDrop for Omarchy.** Beam speaks the [LocalSend](https://localsend.org) protocol,
so your Linux desktop appears in the device list of the iPhones, Android phones, Macs
and Windows machines already running LocalSend — and they appear in yours.

```bash
omarchy plugin add https://github.com/mrjamesmyers/omarchy-beam.git --enable
omarchy bar plugin add io.github.mrjamesmyers.beam
```

Plugins run unsandboxed inside your shell process. Read the source before you enable
anything, including this.

---

## Why this shape

The gap AirDrop leaves on Linux is not "there is no file transfer tool." There are
dozens. The gap is that **none of them are on the other person's phone.** A transfer
protocol is only worth what its client coverage is worth.

So Beam does not invent one. LocalSend already ships a polished, audited, open-source
client for iOS, Android, macOS, Windows, and Linux, with millions of installs and a
[published protocol](https://github.com/localsend/protocol). Beam implements that
protocol natively inside the Omarchy shell. The phone in your pocket needs no plugin,
no pairing, and no account — it needs the app it very likely already has.

- **Peer to peer over your own LAN.** No cloud, no relay, no server, no account.
- **Encrypted by default.** TLS with a self-signed certificate generated on first run;
  the certificate's SHA-256 is the device fingerprint, exactly as the protocol specifies.
- **Nothing is written to your disk without a prompt** unless you turn that off yourself.

## Sending

Three ways in, because people reach for different ones:

- **Drag files onto the bar widget** — or onto the open panel — then click a device.
- **From a terminal:** `omarchy-shell omarchy.beam send ~/report.pdf`
- **From a keybind** — bind that same command in `hyprland.conf`.

## Receiving

Incoming transfers raise a prompt in the panel naming the sender, the files, and the
total size. Accept and they land in `~/Downloads`; decline and the sender is told.

Filenames coming off the network are treated as hostile: directory separators, parent
references and control characters are stripped before anything touches the filesystem,
and a name that collides is renamed rather than overwriting what is already there.
If the sender supplied a SHA-256, a mismatch means the file is deleted, not kept.

## Settings

| Setting | Default | What it does |
|---|---|---|
| `alias` | a generated two-word name | What other devices call this machine |
| `downloadDir` | `~/Downloads` | Where accepted files land |
| `autoAccept` | `false` | Take every file with no prompt. Fine at home; reckless on a shared network |
| `pin` | none | Senders must supply this PIN before you even see a prompt |
| `quiet` | `false` | Stop announcing. You can still send; nobody can send to you |
| `notifyOnReceive` | `true` | Desktop notification when files finish arriving |

## Requirements

`python3` and `openssl`, both already present on Omarchy. No pip, no sudo, no install
hooks, no third-party repos — the plugin is QML and one standard-library Python file.

If `openssl` is somehow missing, Beam falls back to plaintext HTTP and says so in the
panel. LocalSend clients configured for encryption will not talk to it in that state,
which is the correct outcome rather than a silent downgrade.

## Ports

- **UDP 53317** — multicast discovery on 224.0.0.167
- **TCP 53317** — the transfer API

Both are LocalSend defaults. Set `BEAM_PORT` in the environment to move them; a
LocalSend app already running on the same machine will coexist where the kernel
supports `SO_REUSEPORT`.

## Tests

```bash
python3 helper/test_beamd.py
```

Twenty-seven cases driving the daemon over real TLS on real sockets — discovery,
registration, accept, decline, checksum enforcement, path-traversal filenames, and a
full send round-trip against a mock peer. They test the wire, not the internals,
because a test that reaches past the socket proves nothing about whether a phone can
talk to it.

## Known limits

- **Folders are not sent.** LocalSend transfers files; zip a directory first.
- **Discovery needs multicast.** Guest and enterprise wifi frequently block it. Beam
  reports what it can see and stays silent rather than pretending.
- **One inbound transfer at a time.** A second sender is told to wait, per the protocol.

## Non-goals

Not a sync tool, not a cloud drive, not a chat app. It moves files between two devices
on one network and then gets out of the way.

## Removing it

```bash
omarchy bar plugin remove io.github.mrjamesmyers.beam
omarchy plugin disable io.github.mrjamesmyers.beam
omarchy plugin remove io.github.mrjamesmyers.beam
```

That takes the widget off the bar, stops the helper, and deletes the clone. Beam
also keeps a device name and a TLS certificate of its own; remove those too if you
are done with it:

```bash
rm -rf ~/.local/state/omarchy-beam
```

Nothing else on the system is touched. Beam never wrote outside its own plugin
directory, that state directory, and the folder you told it to save files into.

## Credits

Built by [James Myers](https://github.com/mrjamesmyers). MIT licensed.
Implements the LocalSend protocol; not affiliated with or endorsed by the LocalSend project.
Not affiliated with, sponsored by, or endorsed by Omarchy, the Omacom Foundation, or 37signals.
