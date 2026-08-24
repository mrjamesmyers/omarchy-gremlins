#!/usr/bin/env python3
"""
omarchy-ink helper daemon - sign and fill a PDF without leaving the desktop.

There is no PDF plugin among the 1,099 in the Omarchy registry. "I need to sign
this" is one of the honest reasons people keep a Mac or a Windows box around.

The PDF work is in pdfcore.py, standard library only. This process is the part
that talks to the shell: it opens a document, reports the pages, converts the
coordinates the interface works in into the ones a PDF wants, and writes the
result out as an incremental update so the original is preserved inside it.

Transport contract with QML: newline-delimited JSON.
"""

import contextlib
import json
import os
import shutil
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pdfcore                                          # noqa: E402


def log(msg):
    sys.stderr.write("inkd: %s\n" % msg)
    sys.stderr.flush()


class Emitter:
    def __init__(self):
        self._lock = threading.Lock()

    def __call__(self, event, **fields):
        fields["ev"] = event
        line = json.dumps(fields, separators=(",", ":"))
        with self._lock:
            try:
                sys.stdout.write(line + "\n")
                sys.stdout.flush()
            except (BrokenPipeError, ValueError):
                os._exit(0)


emit = Emitter()


def visual_size(page):
    """Page size as displayed, which swaps for quarter turns."""
    if page["rotate"] in (90, 270):
        return page["height"], page["width"]
    return page["width"], page["height"]


def to_user_space(page, x, y, scale=1.0):
    """Convert an interface point to PDF user space.

    The interface works in display pixels with the origin at the top left. PDF
    user space has its origin at the bottom left, is measured in points, and is
    what /Rotate is applied *to* - so a rotated page needs the inverse of the
    rotation the viewer applied, not the rotation itself. Getting this wrong
    puts a signature on the wrong edge of every scanned document, which is most
    of them.
    """
    if scale <= 0:
        scale = 1.0
    px, py = float(x) / scale, float(y) / scale
    w, h = page["width"], page["height"]
    rotate = page["rotate"]

    if rotate == 90:
        u, v = py, px
    elif rotate == 180:
        u, v = w - px, py
    elif rotate == 270:
        u, v = w - py, h - px
    else:
        u, v = px, h - py

    return round(u + page["x0"], 4), round(v + page["y0"], 4)


def convert_ops(page, ops, scale=1.0):
    """Rewrite one page's operations from interface space into user space."""
    out = []
    for op in ops or []:
        kind = op.get("type")
        converted = dict(op)
        if kind == "ink":
            points = []
            for point in op.get("points") or []:
                if isinstance(point, dict):
                    px, py = point.get("x"), point.get("y")
                else:
                    px, py = point[0], point[1]
                points.append(list(to_user_space(page, px, py, scale)))
            converted["points"] = points
            # Line width is a distance, so it only scales - it does not rotate.
            converted["width"] = float(op.get("width", 2.0)) / (scale or 1.0)
        elif kind == "text":
            size_visual = float(op.get("size", 12.0))
            # The interface anchors text at its top-left; PDF places the
            # baseline. Shift in interface space, BEFORE rotating - applying it
            # afterwards is only correct on an unrotated page and puts the text
            # sideways-adjacent to where it was drawn on every other one.
            bx = float(op.get("x", 0))
            by = float(op.get("y", 0)) + size_visual * 0.8
            converted["x"], converted["y"] = to_user_space(page, bx, by, scale)
            converted["size"] = size_visual / (scale or 1.0)
        elif kind in ("rect", "highlight"):
            x0, y0 = to_user_space(page, op.get("x", 0), op.get("y", 0), scale)
            x1, y1 = to_user_space(page,
                                   float(op.get("x", 0)) + float(op.get("width", 0)),
                                   float(op.get("y", 0)) + float(op.get("height", 0)),
                                   scale)
            converted["x"], converted["y"] = min(x0, x1), min(y0, y1)
            converted["width"] = abs(x1 - x0)
            converted["height"] = abs(y1 - y0)
        out.append(converted)
    return out


class Ink:
    def __init__(self):
        self.path = None
        self.document = None
        self.page_list = []
        self.running = True

    def open_document(self, path):
        path = os.path.expanduser(str(path or ""))
        if path.startswith("file://"):
            from urllib.parse import unquote, urlparse
            path = unquote(urlparse(path).path)
        if not os.path.isfile(path):
            emit("error", message="%s is not a file." % os.path.basename(path))
            return
        try:
            with open(path, "rb") as fh:
                data = fh.read()
            document = pdfcore.Document(data)
            pages = document.pages()
        except (pdfcore.PdfError, OSError, ValueError) as exc:
            emit("error", message="Could not read that PDF: %s" % exc)
            return
        if not pages:
            emit("error", message="That PDF has no pages this can read.")
            return

        self.path, self.document, self.page_list = path, document, pages
        emit("opened",
             path=path,
             name=os.path.basename(path),
             pages=[{"index": p["index"],
                     "width": visual_size(p)[0],
                     "height": visual_size(p)[1],
                     "rotate": p["rotate"]} for p in pages],
             encrypted=bool(document.trailer.get("Encrypt")))
        if document.trailer.get("Encrypt"):
            emit("error", message="That PDF is encrypted. Annotations would not "
                                  "survive; open it in a viewer that can decrypt it first.")

    def save(self, target, annotations, scale=1.0):
        if not (self.document and self.path):
            emit("error", message="Nothing is open.")
            return
        by_index = {p["index"]: p for p in self.page_list}
        converted = {}
        for key, ops in (annotations or {}).items():
            try:
                index = int(key)
            except (TypeError, ValueError):
                continue
            page = by_index.get(index)
            if page and ops:
                converted[index] = convert_ops(page, ops, scale)

        if not converted:
            emit("error", message="There is nothing to save.")
            return

        target = os.path.expanduser(str(target or ""))
        if not target:
            stem, ext = os.path.splitext(self.path)
            target = "%s-signed%s" % (stem, ext or ".pdf")

        # Never write over the source by accident. The whole safety story here
        # is that the original survives.
        if os.path.abspath(target) == os.path.abspath(self.path):
            stem, ext = os.path.splitext(self.path)
            target = "%s-signed%s" % (stem, ext or ".pdf")

        try:
            written = pdfcore.save_annotated(self.path, target, converted)
        except (pdfcore.PdfError, OSError, ValueError) as exc:
            emit("error", message="Could not write that file: %s" % exc)
            return

        emit("saved", path=target, name=os.path.basename(target),
             appended=written, pages=sorted(converted))

    def verify(self, path):
        """Re-open a written file and confirm it still parses. Cheap insurance."""
        try:
            with open(path, "rb") as fh:
                document = pdfcore.Document(fh.read())
            return len(document.pages())
        except Exception:                               # noqa: BLE001
            return 0


def handle_command(ink, msg):
    cmd = msg.get("cmd")
    if cmd == "open":
        ink.open_document(msg.get("path"))
    elif cmd == "save":
        ink.save(msg.get("target"), msg.get("annotations"), float(msg.get("scale", 1.0)))
    elif cmd == "close":
        ink.path = ink.document = None
        ink.page_list = []
        emit("closed")
    elif cmd == "quit":
        ink.running = False


def main():
    ink = Ink()
    emit("ready", pdf=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if not isinstance(msg, dict):
            continue
        try:
            handle_command(ink, msg)
        except Exception as exc:                        # noqa: BLE001
            log("command %r failed: %s" % (msg.get("cmd"), exc))
            emit("error", message=str(exc))
        if not ink.running:
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
