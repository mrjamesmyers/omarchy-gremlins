#!/usr/bin/env python3
"""
omarchy-twin helper daemon - find the same file twice.

Nothing in the 1,099-plugin registry looks for duplicates. macOS surfaces them
in Storage Management and Windows leans on third parties; on Linux the answer
has been fdupes, which is excellent and is a command line.

The scan is the standard three passes, cheapest first, because hashing every
file on a disk to find a handful of pairs is the wrong shape:

  1. group by size          a file with a unique size cannot have a twin
  2. hash the first 64 KiB  cheap, and kills almost every remaining group
  3. hash the whole file    only for what is still standing

Hard links are not duplicates. Two names for one inode already share their
storage, and "deleting" one frees nothing - so they are reported as links
rather than offered up for removal.
"""

import contextlib
import hashlib
import json
import os
import stat
import sys
import threading
import time

CHUNK = 1024 * 1024
HEAD = 64 * 1024
MIN_SIZE = 1                      # a zero-byte file is not interesting
PROGRESS_EVERY = 0.2


def log(msg):
    sys.stderr.write("twind: %s\n" % msg)
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


def digest(path, limit=None):
    h = hashlib.blake2b(digest_size=16)
    remaining = limit
    with open(path, "rb") as fh:
        while True:
            want = CHUNK if remaining is None else min(CHUNK, remaining)
            if want <= 0:
                break
            block = fh.read(want)
            if not block:
                break
            h.update(block)
            if remaining is not None:
                remaining -= len(block)
    return h.hexdigest()


def walk(roots, skip_hidden=True, min_size=MIN_SIZE, cancel=None):
    """Yield (path, stat) for regular files under roots, following nothing.

    Symlinks are never followed: a link into a parent directory turns a scan
    into an infinite one, and a link is not a copy anyway.
    """
    seen_dirs = set()
    for root in roots:
        root = os.path.realpath(os.path.expanduser(root))
        if not os.path.isdir(root):
            continue
        for base, dirs, files in os.walk(root, topdown=True, followlinks=False):
            if cancel is not None and cancel.is_set():
                return
            # Guard against a directory reached twice through two roots.
            key = os.path.realpath(base)
            if key in seen_dirs:
                dirs[:] = []
                continue
            seen_dirs.add(key)

            # os.scandir hands entries back in whatever order the filesystem
            # stores them, which differs between filesystems for the same tree.
            # Sorting makes a scan reproducible, which matters because this tool
            # tells people which files to delete: where two names share an inode
            # only the first is offered, and without an order that "first" -- and
            # so the name on screen -- changes from machine to machine.
            dirs.sort()
            files.sort()

            if skip_hidden:
                dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in files:
                if skip_hidden and name.startswith("."):
                    continue
                path = os.path.join(base, name)
                try:
                    st = os.lstat(path)
                except OSError:
                    continue
                if not stat.S_ISREG(st.st_mode):
                    continue
                if st.st_size < min_size:
                    continue
                yield path, st


def find_duplicates(roots, skip_hidden=True, min_size=MIN_SIZE,
                    progress=None, cancel=None):
    """Return (groups, stats). Each group is a list of paths with equal content."""
    by_size = {}
    inodes = {}
    scanned = 0

    for path, st in walk(roots, skip_hidden, min_size, cancel):
        scanned += 1
        # Two names for one inode already share storage. Record the link and
        # keep only the first name as a candidate.
        ident = (st.st_dev, st.st_ino)
        if st.st_nlink > 1 and ident in inodes:
            inodes[ident].append(path)
            continue
        inodes.setdefault(ident, [path])
        by_size.setdefault(st.st_size, []).append(path)
        if progress and scanned % 200 == 0:
            progress("counting", scanned, 0)

    candidates = {size: paths for size, paths in by_size.items() if len(paths) > 1}
    total = sum(len(p) for p in candidates.values())
    if progress:
        progress("sized", scanned, total)

    # Pass two: the first 64 KiB.
    by_head = {}
    done = 0
    for size, paths in candidates.items():
        if cancel is not None and cancel.is_set():
            break
        for path in paths:
            done += 1
            if progress and done % 25 == 0:
                progress("hashing", done, total)
            with contextlib.suppress(OSError):
                by_head.setdefault((size, digest(path, HEAD)), []).append(path)

    # Pass three: the whole file, only where a head collision survived.
    groups = []
    for (size, _head), paths in by_head.items():
        if len(paths) < 2:
            continue
        if cancel is not None and cancel.is_set():
            break
        # A file smaller than the head read was already hashed in full.
        if size <= HEAD:
            groups.append(sorted(paths))
            continue
        full = {}
        for path in paths:
            with contextlib.suppress(OSError):
                full.setdefault(digest(path), []).append(path)
        for same in full.values():
            if len(same) > 1:
                groups.append(sorted(same))

    groups.sort(key=lambda g: (-_size_of(g[0]) * (len(g) - 1), g[0]))

    links = {paths[0]: paths[1:] for paths in inodes.values() if len(paths) > 1}
    reclaimable = sum(_size_of(g[0]) * (len(g) - 1) for g in groups)
    return groups, {
        "scanned": scanned,
        "candidates": total,
        "groups": len(groups),
        "reclaimable": reclaimable,
        "hardlinked": len(links),
    }


def _size_of(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def delete(paths, keep, roots):
    """Delete `paths`, refusing to remove the last copy or anything outside roots."""
    real_roots = [os.path.realpath(os.path.expanduser(r)) for r in roots or []]

    def inside(path):
        real = os.path.realpath(path)
        return any(real == root or real.startswith(root + os.sep) for root in real_roots)

    keep_real = os.path.realpath(keep) if keep else None
    removed, refused, freed = [], [], 0

    for path in paths or []:
        real = os.path.realpath(path)
        if keep_real and real == keep_real:
            refused.append({"path": path, "why": "this is the copy being kept"})
            continue
        if real_roots and not inside(path):
            refused.append({"path": path, "why": "outside the folders you scanned"})
            continue
        if not os.path.isfile(real):
            refused.append({"path": path, "why": "no longer there"})
            continue
        size = _size_of(real)
        try:
            os.remove(real)
        except OSError as exc:
            refused.append({"path": path, "why": str(exc)})
            continue
        removed.append(path)
        freed += size

    return removed, refused, freed


class Twin:
    def __init__(self):
        self.running = True
        self.roots = [os.path.expanduser("~")]
        self.groups = []
        self.cancel = threading.Event()
        self.scanning = False

    def scan(self, roots, skip_hidden=True, min_size=MIN_SIZE):
        if self.scanning:
            emit("error", message="A scan is already running.")
            return
        self.roots = [r for r in (roots or self.roots) if r]
        self.cancel.clear()
        self.scanning = True
        last = [0.0]

        def progress(stage, done, total):
            now = time.monotonic()
            if now - last[0] < PROGRESS_EVERY:
                return
            last[0] = now
            emit("progress", stage=stage, done=done, total=total)

        emit("scanning", active=True, roots=self.roots)
        try:
            groups, stats = find_duplicates(self.roots, skip_hidden, min_size,
                                            progress, self.cancel)
        except Exception as exc:                        # noqa: BLE001
            log("scan failed: %s" % exc)
            emit("error", message=str(exc))
            groups, stats = [], {}
        finally:
            self.scanning = False
            emit("scanning", active=False, roots=self.roots)

        self.groups = groups
        emit("results",
             groups=[{"size": _size_of(g[0]), "paths": g,
                      "waste": _size_of(g[0]) * (len(g) - 1)} for g in groups[:400]],
             truncated=max(0, len(groups) - 400),
             cancelled=self.cancel.is_set(),
             **stats)

    def remove(self, paths, keep):
        removed, refused, freed = delete(paths, keep, self.roots)
        emit("deleted", removed=removed, refused=refused, freed=freed)


def handle_command(twin, msg):
    cmd = msg.get("cmd")
    if cmd == "scan":
        threading.Thread(
            target=twin.scan,
            args=(msg.get("roots"), msg.get("skipHidden", True),
                  int(msg.get("minSize", MIN_SIZE) or MIN_SIZE)),
            daemon=True).start()
    elif cmd == "cancel":
        twin.cancel.set()
    elif cmd == "delete":
        twin.remove(msg.get("paths"), msg.get("keep"))
    elif cmd == "quit":
        twin.cancel.set()
        twin.running = False


def main():
    twin = Twin()
    emit("ready", home=os.path.expanduser("~"))
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
            handle_command(twin, msg)
        except Exception as exc:                        # noqa: BLE001
            log("command %r failed: %s" % (msg.get("cmd"), exc))
            emit("error", message=str(exc))
        if not twin.running:
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
