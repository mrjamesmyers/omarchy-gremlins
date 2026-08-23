# Ink

**Sign and fill a PDF without leaving the desktop.** Drop a document on the bar, draw
your signature, type into the blanks, save. There was no PDF plugin at all among the
1,099 in the Omarchy registry when this was written.

```bash
omarchy plugin add https://github.com/mrjamesmyers/omarchy-ink.git --enable
omarchy bar plugin add io.github.mrjamesmyers.ink
```

Plugins run unsandboxed inside your shell process. Read the source before you enable
anything, including this.

---

## Why this one

"I need to sign this PDF" is one of the honest reasons people keep a Mac or a Windows
machine around. macOS Preview has done it since 2010 and it takes about fifteen seconds.
On Linux the answer has been a web service you upload your contract to, or an office
suite that reflows the document while you look at it.

## The safety property

**The original file is never rewritten.** Ink writes an *incremental update*: the source
document is copied out byte for byte, and the annotations are appended after it as new
objects with a cross-reference section pointing back at the original one.

That means the file you started with is still in there, intact, inside the file you end
up with. A bad annotation costs you an undo, not a contract. Ink also refuses to write
over the source even if you ask it to — it redirects to `name-signed.pdf` instead.

There is a test that asserts the output starts with the input, byte for byte. It is the
most important test in the repository.

## What it does

- **Sign** — drag to draw, in ink that looks like a pen rather than pure black.
- **Type** — click where a form field is and type. Uses Helvetica from the standard 14,
  so nothing is embedded and the file stays small.
- **Undo and clear**, per page.
- **Highlight and box** are in the core and not yet on the toolbar.

## How the PDF work is done

`helper/pdfcore.py` is a small PDF reader and incremental-update writer in **pure
standard library**. Omarchy plugins are cloned rather than installed, so pypdf is not
available, and asking somebody to run `pip` before they can sign a form is the same as
not shipping the feature.

It handles what real files actually contain:

| | |
|---|---|
| Classic cross-reference tables | PDF 1.4 and hand-written files |
| **Cross-reference streams** | everything since PDF 1.5 — most of what you will meet |
| **Object streams** | where modern files hide the catalog and page tree, compressed |
| Inherited attributes | `MediaBox` and `Resources` living on the `Pages` node |
| Wrong `/Length` | commoner than it should be; the stream is recovered by scanning |
| Damaged cross-references | rebuilt by scanning the file for objects |
| `/Rotate` | scans are usually rotated, and that is where signatures go wrong |

It deliberately does **not** do encryption, font embedding, or image XObjects.

## Requirements

`python3`. That is all for reading and writing.

**For rendering pages on screen**, Ink uses `QtQuick.Pdf` where the Qt build provides it,
which is what allows page two and beyond. Where it is missing, Qt's PDF *image* plugin
still renders the first page and the editor says so rather than showing an empty
rectangle — a one-page fallback covers most of what people sign.

## Tests

```bash
python3 helper/test_pdfcore.py   # 63 cases - parsing, writing, byte preservation
python3 helper/test_inkd.py      # 36 cases - coordinates, rotation, save safety
```

Fixtures are generated rather than checked in, so both cross-reference flavours are
covered — including a fixture whose catalog and page tree live compressed inside an
object stream, because a parser that only reads classic tables works on almost nothing
modern.

Two bugs those tests caught:

- **The recovery path was unreachable.** `_startxref()` raised before the
  rebuild-by-scanning fallback could run — so a file with a damaged cross-reference,
  precisely the case the fallback exists for, failed instead of being repaired.
- **Tokens glued across a stream join.** Content streams in a `/Contents` array are
  concatenated by the reader, and the spec makes it the *producer's* job to ensure the
  division lands on a token boundary. Page content commonly ends `ET` with no trailing
  whitespace; the appended stream started `Q`; together they formed `ETQ`, which is not a
  token. One leading newline fixes it, and nothing but reading the joined output would
  have shown it.

Rotation is pinned by corner mappings — there is exactly one right answer for where the
top-left of the display lands in user space at each of 0°, 90°, 180° and 270°, and an
inverted transform puts every signature on the wrong edge of every scanned document.

## Known limits

- **No encrypted PDFs.** Ink detects them and says so; annotations would not survive.
- **No image stamping yet** — a signature is drawn, not pasted from a photo.
- **Typed text is drawn, not an AcroForm field.** It is flattened into the page, which is
  what you want for a form you are returning and not what you want for a form somebody
  else must fill in afterwards.
- **Multi-page editing needs `QtQuick.Pdf`.** See Requirements.

## Removing it

```bash
omarchy bar plugin remove io.github.mrjamesmyers.ink
omarchy plugin disable io.github.mrjamesmyers.ink
omarchy plugin remove io.github.mrjamesmyers.ink
```

Ink keeps no state outside its own plugin directory and never modified any document you
opened, so there is nothing else to clean up.

## Credits

Built by [James Myers](https://github.com/mrjamesmyers). MIT licensed.
Not affiliated with, sponsored by, or endorsed by Adobe, Omarchy, the Omacom Foundation,
or 37signals.
