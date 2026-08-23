# UniFi

**Your Ubiquiti network in the bar.** A health dot, a client count, and a panel with
the gateway, every adopted device, and who is connected.

```bash
omarchy plugin add https://github.com/mrjamesmyers/omarchy-unifi.git --enable
omarchy bar plugin add io.github.mrjamesmyers.unifi
```

Plugins run unsandboxed inside your shell process. Read the source before you enable
anything, including this.

---

## Setup

**1. Make an API key.** In the UniFi console: Settings → Control Plane → Integrations →
Create API Key. Copy it once; it is not shown again.

**2. Put it in a file, not in your dotfiles.**

```bash
install -m600 /dev/null ~/.config/omarchy/unifi.key
printf %s 'YOUR_KEY_HERE' > ~/.config/omarchy/unifi.key
```

**3. Point the widget at your console** — set `host` in the widget's entry in
`~/.config/omarchy/shell.json`:

```json
{ "id": "io.github.mrjamesmyers.unifi", "host": "192.168.1.1", "port": 443 }
```

| Console | Port |
|---|---|
| UniFi OS — UDM, UDM Pro, UCG, UDR, Cloud Key | `443` |
| Self-hosted Network Application | `8443` |
| UniFi OS Server | `11443` |

## Two deliberate security choices

Most UniFi integrations get both of these wrong, so they are worth stating.

**The API key is never stored in `shell.json`.** That file is a dotfile, and dotfiles
end up in public GitHub repositories. A UniFi API key grants full read access to every
device and every client on your network. It lives in its own file at mode `0600`, or in
`UNIFI_API_KEY`. If the key file is readable by anyone else, the plugin refuses to use
it and tells you to `chmod 600` rather than quietly carrying on.

**The certificate is pinned on first use.** UniFi consoles ship a self-signed
certificate, so every guide on the internet tells you to disable TLS verification — and
then leaves it disabled forever, which means anything on your network can impersonate
your console indefinitely. This records the certificate's SHA-256 the first time it
connects and refuses to talk to anything else afterwards. Same bargain SSH makes.

If you reinstall the console the certificate changes and the plugin will say so loudly.
Clear the pin in `~/.local/state/omarchy-unifi/` to accept the new one.

**It is read-only.** The plugin issues `GET` requests and nothing else. It cannot
restart an access point, change a setting, or block a client, and it never will —
a status widget with write access to your network is a bad trade.

## What it shows

- **A health dot in the bar** — green when every adopted device is online, amber when
  one is not, red when the console is unreachable or the key was rejected. Amber and
  red pulse; green is silent, because steady state should be.
- **Gateway** — download and upload rate, CPU, memory, uptime.
- **Devices** — every adopted device with its state and address, offline ones last.
- **Clients** — total, wired, wireless.

## Settings

| Setting | Default | What it does |
|---|---|---|
| `host` | — | Console IP or hostname. No scheme, no path |
| `port` | `443` | See the table above |
| `site` | first site | Which site to show |
| `keyFile` | `~/.config/omarchy/unifi.key` | Where the key lives |
| `pollSeconds` | `20` | How often to ask |
| `showClientCount` | `true` | Off shows only the dot |

## Compatibility

Built against the UniFi Network **Integration API v1**. The base path moved between
releases and the plural spelling still appears in third-party documentation, so the
plugin probes `/proxy/network/integration/v1`, then `/proxy/network/integrations/v1`,
then bare `/v1`, and remembers which one answered.

Requires UniFi Network 9.x or later, which is the release that introduced API keys.

## Requirements

`python3`, already present on Omarchy. No pip, no sudo, no install hooks.

The helper exists rather than using QML's `XMLHttpRequest` for one reason: QML has no
way to make a certificate exception for a single host, and "disable verification
globally" is not an exception.

## Tests

```bash
python3 helper/test_unifid.py
```

Twenty-four cases against a mock console over real TLS: base-path probing, pagination
across a 250-client site, gateway identification, key-file permission enforcement, and
certificate pinning — including that a swapped certificate on the same address is
rejected.

One bug those tests caught: `PermissionError` subclasses `OSError`, and the transport
layer catches `OSError` to mean "this host did not answer" — so a missing or
badly-permissioned key file was being reported as *"no UniFi API found at
192.168.1.1"*, sending people to debug their network instead of their key.

## Credits

Built by [James Myers](https://github.com/mrjamesmyers). MIT licensed.
Not affiliated with, sponsored by, or endorsed by Ubiquiti, Omarchy, the Omacom
Foundation, or 37signals.
