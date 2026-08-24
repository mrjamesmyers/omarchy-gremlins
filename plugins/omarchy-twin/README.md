# Twin

**Find the same file twice.** Nothing in the 1,099-plugin Omarchy registry looked for
duplicates. macOS surfaces them in Storage Management, Windows leans on third parties,
and on Linux the answer has been `fdupes` — which is excellent, and is a command line.

```bash
omarchy plugin add https://github.com/mrjamesmyers/omarchy-twin.git --enable
omarchy bar plugin add io.github.mrjamesmyers.twin
```

---

## How the scan works

Three passes, cheapest first, because hashing an entire disk to find a handful of pairs
is the wrong shape:

1. **Group by size.** A file with a unique size cannot have a twin. This eliminates most
   of the disk without reading a single byte of content.
2. **Hash the first 64 KiB.** Cheap, and it kills almost every group that survived.
3. **Hash in full** — only for what is still standing.

A disk full of unique files therefore costs almost nothing to check.

## The safety rules

Duplicate finders are easy to get *almost* right, and "almost" is how people lose files.

- **The last copy can never be deleted.** Every group keeps its first file; the helper
  refuses to remove the kept copy even when it is explicitly in the delete list. There is
  no sequence of clicks that leaves you with nothing.
- **Nothing outside the folders you scanned can be touched**, including a path dressed up
  with `../..` to look like it is inside. There is a test for exactly that.
- **Hard links are not duplicates.** Two names for one inode already share their storage
  — deleting one frees nothing. They are reported as links and never offered for removal.
- **Symlinks are never followed.** A link pointing at a parent turns a scan into an
  infinite one, and a link is not a copy.

## Settings

| Setting | Default | What it does |
|---|---|---|
| `roots` | your home | Colon-separated folders to scan |
| `skipHidden` | `true` | Leave dotfiles and caches alone, where most false positives live |
| `minSizeKb` | `4` | Ignore files below this; tiny files duplicate constantly |
| `hideWhenIdle` | `true` | The widget appears while scanning or when there is something to see |

## Requirements

`python3`. Nothing else.

## Tests

```bash
python3 helper/test_twind.py
```

Twenty-three cases against a real directory tree, including the ones that separate a
correct finder from a plausible one:

- **Same first 64 KiB, different tail.** Two files that agree for exactly the length of
  the cheap pass and then diverge. A finder that stops after pass two calls them
  identical and offers to delete one.
- **A hard link**, asserted to be reported as a link and absent from every duplicate group.
- **Overlapping roots** — scanning a folder *and* its parent must count each file once.
- **A `../..` delete path**, asserted to leave the file outside untouched.

## Known limits

- **Content only.** Two photographs that differ by one pixel are different files, and a
  re-encoded copy of a song is a different file. This finds byte-identical duplicates,
  which is the safe definition.
- **Results cap at 40 groups on screen** and 400 in the helper, ordered by wasted space,
  so the worst offenders are always the ones you see.
- **No trash.** Deletion is deletion. That is why the last copy is protected.

## Removing it

```bash
omarchy bar plugin remove io.github.mrjamesmyers.twin
omarchy plugin disable io.github.mrjamesmyers.twin
omarchy plugin remove io.github.mrjamesmyers.twin
```

Twin keeps no state outside its own plugin directory.

## Credits

Built by [James Myers](https://github.com/mrjamesmyers). MIT licensed.
Not affiliated with, sponsored by, or endorsed by Omarchy, the Omacom Foundation, or
37signals.
