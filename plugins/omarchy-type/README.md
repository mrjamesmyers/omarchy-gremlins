# Type

**Font Book for Omarchy.** Every family on the machine, previewed in your own words and
your own theme. No font manager existed among the 1,099 plugins in the registry — on a
distribution whose whole pitch is that it looks good.

```bash
omarchy plugin add https://github.com/mrjamesmyers/omarchy-type.git --enable
omarchy bar plugin add io.github.mrjamesmyers.type
```

---

## What it does

- **Every family, drawn in itself.** A list of names is not a font manager; the question
  people have is what it looks like.
- **Install by dropping** a font file on the bar widget or the panel.
- **Turn a family off** without uninstalling it — useful when two fonts fight over the
  same name, or when something ugly keeps winning a fallback.
- **Remove the ones you added.**
- **Search**, and a filter for "only fonts I installed", since most of what is on the
  machine came with it.

## The boundary

**Nothing here touches a system directory and nothing asks for a password.**

Installing copies into `~/.local/share/fonts` and refreshes the cache. Removing only ever
deletes from your own font directories — `~/.local/share/fonts` and the legacy `~/.fonts`
— and refuses anything under `/usr`, because those belong to the package manager and
deleting them behind pacman's back is how a system starts lying to you.

Turning a family off writes a single fontconfig file that this plugin owns entirely,
`~/.config/fontconfig/conf.d/70-omarchy-type-disabled.conf`. Nothing of yours is edited in
place, and re-enabling everything is one deletion.

## Settings

| Setting | Default | What it does |
|---|---|---|
| `sample` | a pangram | What every font spells out |
| `previewSize` | `22` | Point size for the sample line |
| `onlyMine` | `false` | Hide fonts that came with the system |

## Requirements

`python3` and `fontconfig`. Both are already present — the desktop cannot draw text
without fontconfig. No pip, no sudo, no install hooks.

## Tests

```bash
python3 helper/test_typed.py
```

Thirty-four cases. The two things that can quietly ruin a day here both get their own:

- **The `fc-list` parser.** Families and styles come back as comma-separated lists of
  localised aliases — and a name may contain an *escaped* comma. A font by `Smith\, Jones`
  becomes "Smith" under a naive `split(",")`, and then the wrong family gets disabled.
- **The uninstall path.** There is a test that hands it a path climbing out of the font
  directory with `../..` and asserts the file outside is still there afterwards.

## Known limits

- **Preview needs a loadable file.** Bitmap and exotic formats that Qt cannot load fall
  back to being drawn in the family name, which usually still resolves.
- **Disabling is fontconfig-wide**, so an application that is already running keeps the
  old set until it restarts.
- **The list caps at 60 families on screen** and tells you how many it is hiding. Search
  narrows it.

## Removing it

```bash
omarchy bar plugin remove io.github.mrjamesmyers.type
omarchy plugin disable io.github.mrjamesmyers.type
omarchy plugin remove io.github.mrjamesmyers.type
rm -f ~/.config/fontconfig/conf.d/70-omarchy-type-disabled.conf
```

That last line re-enables anything you had switched off. Fonts you installed stay
installed — they are your files, in your directory, and removing a plugin should not
delete them.

## Credits

Built by [James Myers](https://github.com/mrjamesmyers). MIT licensed.
Not affiliated with, sponsored by, or endorsed by Omarchy, the Omacom Foundation, or
37signals.
