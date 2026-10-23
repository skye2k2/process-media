#!/usr/bin/env python3
"""
Unit tests for the external-drive backup and quick-save reconciliation tools.

These tools gate the plan's only irreversible step (deleting the 158 GB
Desktop quick-save), so every decision function here gets a planted-defect
test proving the check can fail before any live run is trusted.

Usage:
    .venv/bin/python test_backup_tools.py -v
"""

import tempfile
import unittest
from pathlib import Path

from backup_archive import build_backup_manifest, build_manifest, compare_manifests
from reconcile_quicksave import classify_quicksave_file
from removal_history import RemovalHistory, normalize_media_name, parse_removal_script


def write_tree(root, files):
    """Create a directory tree from a {relpath: bytes} mapping for fixtures."""
    for relpath, content in files.items():
        target = Path(root) / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


class TestBuildManifest(unittest.TestCase):
    """build_manifest walks a tree into {relpath: (size, md5)} with excludes."""

    def test_manifest_maps_relpath_to_size_and_md5(self):
        with tempfile.TemporaryDirectory() as root:
            write_tree(root, {"a/photo.jpg": b"hello"})
            manifest = build_manifest(Path(root))

            self.assertIn("a/photo.jpg", manifest)
            size, digest = manifest["a/photo.jpg"]
            self.assertEqual(size, 5)
            # md5("hello")
            self.assertEqual(digest, "5d41402abc4b2a76b9719d911017c592")

    def test_manifest_honors_excludes(self):
        with tempfile.TemporaryDirectory() as root:
            write_tree(root, {
                ".venv/lib/thing.py": b"x",
                "__pycache__/mod.pyc": b"x",
                ".TMP_scratch.log": b"x",
                ".DS_Store": b"x",
                "keeper.jpg": b"x",
                "sub/__pycache__/nested.pyc": b"x",
            })
            manifest = build_manifest(Path(root))

            self.assertEqual(set(manifest), {"keeper.jpg"})


class TestBuildBackupManifest(unittest.TestCase):
    """
    The backup set is the non-git-protected data, not the whole repo: the
    archive trees, rescue output, staging, caches, and _records. Code, docs,
    and other git-tracked content are the remote's job, not the drive's.
    """

    def test_backup_set_is_data_not_code(self):
        with tempfile.TemporaryDirectory() as root:
            write_tree(root, {
                "Organized_Photos/2014/02 February/a.jpg": b"a",
                "Organized_Videos/_PRODUCED/_README.md": b"p",
                "_RESCUED/2009/clip_DAMAGED.mp4": b"r",
                "TO_PROCESS/takeout/x.jpg": b"t",
                "_records/reconcile.txt": b"e",
                ".duration_cache.json": b"{}",
                # Git-protected content that must NOT be in the backup set:
                "organize_media.py": b"code",
                "docs/superpowers/specs/spec.md": b"doc",
                "README.md": b"readme",
                "_Timeline/2026-01-01 note.png": b"img",
                # Still excluded inside included trees:
                "Organized_Photos/.TMP_scratch.log": b"x",
            })
            manifest = build_backup_manifest(Path(root))

            self.assertEqual(set(manifest), {
                "Organized_Photos/2014/02 February/a.jpg",
                "Organized_Videos/_PRODUCED/_README.md",
                "_RESCUED/2009/clip_DAMAGED.mp4",
                "TO_PROCESS/takeout/x.jpg",
                "_records/reconcile.txt",
                ".duration_cache.json",
            })


class TestCompareManifests(unittest.TestCase):
    """compare_manifests must catch every planted defect class."""

    def setUp(self):
        self.src = {
            "a.jpg": (5, "aaaa"),
            "b.jpg": (7, "bbbb"),
        }

    def test_identical_manifests_are_ok(self):
        diff = compare_manifests(self.src, dict(self.src))
        self.assertTrue(diff.ok)
        self.assertEqual(diff.missing, [])
        self.assertEqual(diff.extra, [])
        self.assertEqual(diff.mismatched, [])

    def test_missing_destination_file_is_caught(self):
        dst = {"a.jpg": (5, "aaaa")}
        diff = compare_manifests(self.src, dst)
        self.assertFalse(diff.ok)
        self.assertEqual(diff.missing, ["b.jpg"])

    def test_extra_destination_file_is_caught(self):
        dst = dict(self.src)
        dst["stray.jpg"] = (1, "ffff")
        diff = compare_manifests(self.src, dst)
        self.assertFalse(diff.ok)
        self.assertEqual(diff.extra, ["stray.jpg"])

    def test_size_mismatch_is_caught(self):
        dst = dict(self.src)
        dst["a.jpg"] = (6, "aaaa")
        diff = compare_manifests(self.src, dst)
        self.assertFalse(diff.ok)
        self.assertEqual(diff.mismatched, ["a.jpg"])

    def test_content_mismatch_with_same_size_is_caught(self):
        # Same size, different bytes — the case that justifies hashing at all.
        dst = dict(self.src)
        dst["a.jpg"] = (5, "cccc")
        diff = compare_manifests(self.src, dst)
        self.assertFalse(diff.ok)
        self.assertEqual(diff.mismatched, ["a.jpg"])


class TestClassifyQuicksaveFile(unittest.TestCase):
    """
    Every quick-save file must land in exactly one explained class before the
    deletion gate opens; 'unexplained' is the class that blocks it.
    """

    def setUp(self):
        self.archive_index = {
            "20140210_171604.jpg": [("2014/02 February/20140210_171604.jpg", 5000)],
        }

    def make_history(self, removed_filenames):
        """Build a RemovalHistory through the real script parser, not a mock."""
        with tempfile.TemporaryDirectory() as root:
            script = Path(root) / "2026-02-19 remove_photos.sh"
            lines = [f'rm "Organized_Photos/2013/05 May/{name}"' for name in removed_filenames]
            script.write_text("#!/bin/bash\n" + "\n".join(lines) + "\n")
            names = {normalize_media_name(Path(p).name) for p in parse_removal_script(script)}
            return RemovalHistory(names=names, sources={script.name: len(names)})

    def test_name_and_size_match_is_present(self):
        result = classify_quicksave_file(
            "2014/02 February/20140210_171604.jpg", 5000,
            self.archive_index, RemovalHistory())
        self.assertEqual(result, "present")

    def test_name_match_with_wrong_size_is_modified(self):
        result = classify_quicksave_file(
            "2014/02 February/20140210_171604.jpg", 4000,
            self.archive_index, RemovalHistory())
        self.assertEqual(result, "modified")

    def test_recorded_removal_is_removed(self):
        history = self.make_history(["20130501_101010.jpg"])
        result = classify_quicksave_file(
            "2013/05 May/20130501_101010.jpg", 1234,
            self.archive_index, history)
        self.assertEqual(result, "removed")

    def test_unknown_absence_is_unexplained(self):
        # The planted-defect case: a file nobody deleted and nobody has.
        result = classify_quicksave_file(
            "2013/05 May/never_seen_before.jpg", 1234,
            self.archive_index, RemovalHistory())
        self.assertEqual(result, "unexplained")


if __name__ == "__main__":
    unittest.main()
