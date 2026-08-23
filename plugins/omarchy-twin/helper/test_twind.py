#!/usr/bin/env python3
"""
Tests for twind, against a real directory tree on disk.

Duplicate finding is easy to get almost right. The cases that matter are the
ones where "almost" deletes something: two names for one inode are not two
copies, a symlink is not a copy, and no amount of clicking should be able to
remove the last remaining file.

    python3 test_twind.py
"""

import importlib.util
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("twind", os.path.join(HERE, "twind.py"))
twind = importlib.util.module_from_spec(spec)
spec.loader.exec_module(twind)

PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print("  %s %s%s" % ("PASS" if condition else "FAIL", name,
                         "" if condition else "   <- %s" % detail))


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def build_tree():
    root = tempfile.mkdtemp(prefix="twin-")
    a = b"the same content, twice over" * 40
    b = b"different content entirely" * 40
    big_a = b"A" * (twind.HEAD + 5000)
    big_b = b"A" * twind.HEAD + b"B" * 5000        # same head, different tail

    paths = {
        "one": write(os.path.join(root, "docs", "one.txt"), a),
        "copy": write(os.path.join(root, "docs", "copy.txt"), a),
        "third": write(os.path.join(root, "elsewhere", "third.txt"), a),
        "other": write(os.path.join(root, "docs", "other.txt"), b),
        "unique": write(os.path.join(root, "unique.txt"), b + b"tail"),
        "biga": write(os.path.join(root, "big", "a.bin"), big_a),
        "bigb": write(os.path.join(root, "big", "b.bin"), big_b),
        "biga2": write(os.path.join(root, "big", "a2.bin"), big_a),
        "hidden": write(os.path.join(root, ".cache", "hidden.txt"), a),
        "empty": write(os.path.join(root, "empty.txt"), b""),
    }
    # A hard link: one inode, two names. Not a duplicate.
    link = os.path.join(root, "docs", "linked.txt")
    os.link(paths["one"], link)
    paths["link"] = link
    # A symlink must never be followed or counted.
    sym = os.path.join(root, "docs", "sym.txt")
    os.symlink(paths["one"], sym)
    paths["sym"] = sym
    return root, paths


def test_walk_skips_the_right_things():
    root, paths = build_tree()
    try:
        found = [p for p, _ in twind.walk([root])]
        check("walk: symlinks are not returned", paths["sym"] not in found, paths["sym"])
        check("walk: zero-byte files are skipped", paths["empty"] not in found)
        check("walk: hidden directories skipped by default",
              paths["hidden"] not in found, paths["hidden"])
        found_all = [p for p, _ in twind.walk([root], skip_hidden=False)]
        check("walk: hidden files included when asked",
              paths["hidden"] in found_all, len(found_all))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_finds_real_duplicates():
    root, paths = build_tree()
    try:
        groups, stats = twind.find_duplicates([root])
        flat = {tuple(sorted(g)) for g in groups}

        triple = tuple(sorted([paths["one"], paths["copy"], paths["third"]]))
        check("find: the three identical files are one group", triple in flat,
              [sorted(g) for g in groups])

        # Same first 64 KiB, different tail. The head pass groups them; only
        # the full hash separates them. This is the case that catches a
        # finder that stops after the cheap pass.
        merged = tuple(sorted([paths["biga"], paths["bigb"]]))
        check("find: same head with a different tail is NOT a duplicate",
              merged not in flat, [sorted(g) for g in groups])
        pair = tuple(sorted([paths["biga"], paths["biga2"]]))
        check("find: genuinely identical large files are a group", pair in flat,
              [sorted(g) for g in groups])

        check("find: a unique file is in no group",
              not any(paths["unique"] in g for g in groups))
        check("find: waste is counted per extra copy, not per file",
              stats["reclaimable"] ==
              os.path.getsize(paths["one"]) * 2 + os.path.getsize(paths["biga"]),
              stats)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_hardlinks_are_not_duplicates():
    root, paths = build_tree()
    try:
        groups, stats = twind.find_duplicates([root])
        in_group = any(paths["link"] in g for g in groups)
        check("hardlink: the second name is not offered as a duplicate",
              not in_group, [g for g in groups if paths["link"] in g])
        check("hardlink: it is reported separately", stats["hardlinked"] >= 1, stats)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_overlapping_roots_do_not_double_count():
    root, paths = build_tree()
    try:
        once, _ = twind.find_duplicates([root])
        twice, _ = twind.find_duplicates([root, os.path.join(root, "docs")])
        check("roots: scanning a folder and its parent counts each file once",
              [sorted(g) for g in once] == [sorted(g) for g in twice],
              ([sorted(g) for g in once], [sorted(g) for g in twice]))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_delete_safety():
    root, paths = build_tree()
    try:
        keep = paths["one"]
        others = [paths["copy"], paths["third"]]

        # The kept copy must survive even when it is in the delete list.
        removed, refused, freed = twind.delete(others + [keep], keep, [root])
        check("delete: the kept copy is refused",
              keep not in removed and any(r["path"] == keep for r in refused), refused)
        check("delete: it still exists", os.path.exists(keep))
        check("delete: the others went", sorted(removed) == sorted(others), removed)
        check("delete: freed bytes reported", freed > 0, freed)

        # Nothing outside the scanned roots may be touched, whatever is asked.
        outside_dir = tempfile.mkdtemp(prefix="twin-out-")
        victim = write(os.path.join(outside_dir, "precious.txt"), b"do not delete")
        removed, refused, _ = twind.delete([victim], keep, [root])
        check("delete: a path outside the scanned folders is refused",
              removed == [] and refused and "outside" in refused[0]["why"], refused)
        check("delete: and the file is still there", os.path.exists(victim))

        # A traversal dressed up to look inside.
        sneaky = os.path.join(root, "docs", "..", "..",
                              os.path.relpath(victim, os.path.dirname(root)))
        removed, _, _ = twind.delete([sneaky], keep, [root])
        check("delete: a ../.. path cannot reach outside", removed == [], removed)
        check("delete: the file outside is still there", os.path.exists(victim))
        shutil.rmtree(outside_dir, ignore_errors=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_min_size_filter():
    root = tempfile.mkdtemp(prefix="twin-min-")
    try:
        write(os.path.join(root, "a.txt"), b"tiny")
        write(os.path.join(root, "b.txt"), b"tiny")
        groups, _ = twind.find_duplicates([root], min_size=1)
        check("minsize: small duplicates found when the floor is low", len(groups) == 1)
        groups, _ = twind.find_duplicates([root], min_size=1024)
        check("minsize: and skipped when the floor is above them", groups == [], groups)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_cancel_stops_early():
    import threading
    root, _ = build_tree()
    try:
        cancel = threading.Event()
        cancel.set()
        groups, stats = twind.find_duplicates([root], cancel=cancel)
        check("cancel: a pre-set cancel yields nothing rather than hanging",
              groups == [], groups)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    print("-- walking --");        test_walk_skips_the_right_things()
    print("\n-- finding --");      test_finds_real_duplicates()
    print("\n-- hard links --");   test_hardlinks_are_not_duplicates()
    print("\n-- roots --");        test_overlapping_roots_do_not_double_count()
    print("\n-- deleting --");     test_delete_safety()
    print("\n-- filters --");      test_min_size_filter()
    print("\n-- cancel --");       test_cancel_stops_early()

    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    for name in FAILED:
        print("   failed: %s" % name)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
