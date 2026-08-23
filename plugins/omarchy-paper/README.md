# Paper

**Printing, finally.** There was not one printer plugin among the 1,099 in the Omarchy
registry when this was written. Paper finds the printers on your network, asks each one
directly what it is doing, and lets you print by dropping a file on the bar.

```bash
omarchy plugin add https://github.com/mrjamesmyers/omarchy-paper.git --enable
omarchy bar plugin add io.github.mrjamesmyers.paper
```

Plugins run unsandboxed inside your shell process. Read the source before you enable
anything, including this.

---

## Why this is the gap worth closing

"It found my printer" is a moment that sells an operating system, and its absence is one
of the most common reasons somebody trying Linux goes back. CUPS has been able to do
driverless printing for years — the machinery is there and it works. What is missing is
anything on the desktop that surfaces it.

## What it does

- **Finds printers over DNS-SD** — `_ipp._tcp` and `_ipps._tcp` — whether or not CUPS has
  ever heard of them.
- **Asks each printer directly, over IPP**, what it is actually doing: idle, printing,
  stopped, out of paper, low toner, and how much is left in each cartridge. CUPS cannot
  tell you that about a printer it has not been configured for. The printer can.
- **Shows the CUPS queue** and lets you cancel a job.
- **Prints by drag and drop.** Drop a document on the bar widget or the panel.
- **Stays out of the way.** The widget is hidden while every printer is idle and nothing
  is queued, and appears when a job is in flight or a printer wants attention.

## The privilege boundary

**Paper never asks for a root password, because it never needs one.**

Adding a print queue requires `lpadmin`, which requires privileges. A bar widget that
pops a password prompt is a bar widget people are right to distrust, and a plugin that
quietly holds root is worse. So when Paper finds a printer CUPS does not know about, it
shows you the exact command that would set it up — and you run it:

```
sudo lpadmin -p Brother_HL_L2350DW -E \
  -v "ipp://192.168.1.9:631/ipp/print" -m everywhere
```

The plugin itself only ever runs `lpstat`, `lp` and `cancel`, none of which need
privileges for what is done here. There is a test that walks the AST and fails the build
if a privileged command ever appears in an executed call.

Printer names arrive from the network and are treated as hostile: the queue name in that
suggested command is reduced to `[A-Za-z0-9_-]` before it is ever shown, so a printer
advertising itself as `Printer"; rm -rf ~; echo "` cannot smuggle shell syntax into
something you might paste.

## Using it

- **Drop a document** on the bar widget or the open panel.
- **Click a printer** in the panel to make it the one drops go to.
- **From a terminal:** `omarchy-shell omarchy.paper print ~/invoice.pdf`

## Settings

| Setting | Default | What it does |
|---|---|---|
| `hideWhenIdle` | `true` | Hide the cell when nothing is printing and nothing needs attention |
| `pollSeconds` | `20` | How often to ask CUPS and the printers. Discovery runs on its own slower cycle |
| `defaultQueue` | CUPS default | Which queue dropped files go to |
| `duplex` | `false` | Send jobs two-sided where supported |

## Requirements

`python3`, already on Omarchy. CUPS for printing itself — without it, Paper still
discovers and reports printers, and says plainly that there is nothing to print with.

No pip, no sudo, no install hooks. IPP is implemented in the helper rather than shelling
out to `ipptool`, because `ipptool` lives in `cups-devel` and a plugin that needs a
package manager to see your printer is a plugin most people never get working.

## Tests

```bash
python3 helper/test_paperd.py
```

Forty-six cases. IPP request bytes are checked field by field against RFC 8011 —
including that `attributes-charset` precedes `attributes-natural-language`, and that
additional values use a zero-length name, which is the single easiest thing to get wrong
in IPP and makes a printer silently ignore every requested attribute but the first.
Responses are parsed from realistic multi-value bytes, and the whole thing round-trips
over a real HTTP socket against a mock printer.

Two bugs those tests caught:

- CUPS writes `printer X is idle.` for enabled queues but `printer X disabled since …`
  for paused ones — no `is`. The parser matched only the first shape, so **every paused
  printer vanished from the list**, which is the one state you most need shown.
- Booleans are one byte per the spec and four in some firmware. Reading only the first
  byte turned a four-byte `true` into `false`.

## Known limits

- **It will not add a queue.** By design. See the privilege boundary above.
- **Discovery needs multicast.** Guest and enterprise wifi frequently block it. USB
  printers do not advertise at all and appear only once CUPS knows them.
- **Ink levels are whatever the printer reports.** Some report nothing; many lie.

## Removing it

```bash
omarchy bar plugin remove io.github.mrjamesmyers.paper
omarchy plugin disable io.github.mrjamesmyers.paper
omarchy plugin remove io.github.mrjamesmyers.paper
```

Paper keeps no state outside its own plugin directory and never modified your CUPS
configuration, so there is nothing else to clean up.

## Credits

Built by [James Myers](https://github.com/mrjamesmyers). MIT licensed.
Not affiliated with, sponsored by, or endorsed by Omarchy, the Omacom Foundation, or
37signals.
