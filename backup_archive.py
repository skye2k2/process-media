#!/usr/bin/env python3
"""
Versioned external-drive backup with full-manifest hash verification.

Mirrors the non-git-protected data (archive trees, rescue output, staging,
records, caches — see BACKUP_SOURCE_DIRS/FILES) to the external backup drive
as plain browsable folders; code and docs are the GitHub remote's job. Prior
states survive via rsync --link-dest hard-link rotation: each sync writes a
new dated tree in snapshots/ that hard-links every unchanged file from the
previous one, so old versions cost almost no space while staying directly
browsable. A `current` symlink always points at the latest tree. (APFS
snapshots were ruled out 2026-10-22: tmutil cannot snapshot a non-boot
volume — see docs/superpowers/specs/2026-10-21-*.md.)

Verification builds a full md5 manifest of both sides and compares — never
spot checks — because this backup gates the deletion of the only other copy.

Usage:
    .venv/bin/python backup_archive.py sync [--dest /Volumes/MEDIA_BACKUP] [--dry-run]
    .venv/bin/python backup_archive.py verify [--dest /Volumes/MEDIA_BACKUP]
"""

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DEFAULT_DEST = Path("/Volumes/MEDIA_BACKUP")
BACKUP_SUBDIR = "process-media"

# The backup set is the NON-GIT-PROTECTED data: the archive trees, rescue
# output, staging, the irreplaceable records, and the expensive caches. Code,
# docs, and other git-tracked content are the GitHub remote's job — backing
# them up here would just shadow version control (decided 2026-10-23).
BACKUP_SOURCE_DIRS = (
    "Organized_Photos",
    "Organized_Videos",
    "TO_PROCESS",
    "_RESCUED",
    "_records",
)
BACKUP_SOURCE_FILES = (
    ".analysis_cache.json",
    ".duration_cache.json",
    ".source_hash_cache.json",
    ".ssim_cache.json",
)

# Directory names pruned anywhere in the tree; patterns matched on basenames.
# .venv is machine-local, __pycache__ is regenerable, .TMP_* is disposable by
# convention, .DS_Store is Finder noise, .superpowers is plan scratch.
EXCLUDED_DIR_NAMES = {".venv", "__pycache__", ".superpowers", ".git"}
EXCLUDED_NAME_PREFIXES = (".TMP_",)
EXCLUDED_BASENAMES = {".DS_Store"}

# Progress cadence for manifest builds over ~200 GB trees.
PROGRESS_EVERY_FILES = 500

# Read size for hashing; 1 MiB balances syscall count against memory.
HASH_CHUNK_BYTES = 1024 * 1024


@dataclass
class ManifestDiff:
    """Outcome of comparing a source manifest against a destination manifest."""

    missing: list = field(default_factory=list)
    extra: list = field(default_factory=list)
    mismatched: list = field(default_factory=list)

    @property
    def ok(self):
        """True only when the destination is a faithful copy of the source."""
        return not (self.missing or self.extra or self.mismatched)


def is_excluded(relpath):
    """Report whether a relative path falls under the backup exclusion rules."""
    parts = Path(relpath).parts
    for part in parts:
        if part in EXCLUDED_DIR_NAMES or part in EXCLUDED_BASENAMES:
            return True
        if part.startswith(EXCLUDED_NAME_PREFIXES):
            return True
    return False


def md5_of_file(path):
    """Hash one file's full contents; integrity against accident, not attack."""
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(HASH_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(root, progress=False):
    """
    Walk a tree into {relpath: (size, md5)} applying the exclusion rules.

    Exists so sync and verify agree byte-for-byte on what "the backup set" is:
    the same function defines membership on both sides of the comparison.
    """
    root = Path(root)
    manifest = {}
    count = 0

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relpath = path.relative_to(root).as_posix()
        if is_excluded(relpath):
            continue
        manifest[relpath] = (path.stat().st_size, md5_of_file(path))
        count += 1
        if progress and count % PROGRESS_EVERY_FILES == 0:
            print(f"  Hashed {count} files...")

    return manifest


def build_backup_manifest(root, progress=False):
    """
    Manifest of exactly the backup set: source dirs, cache files, excludes.

    Sync and verify both define membership through this function, so what
    gets copied and what gets checked can never drift apart.
    """
    root = Path(root)
    manifest = {}
    for dirname in BACKUP_SOURCE_DIRS:
        source = root / dirname
        if source.is_dir():
            for relpath, entry in build_manifest(source, progress=progress).items():
                manifest[f"{dirname}/{relpath}"] = entry
    for filename in BACKUP_SOURCE_FILES:
        source = root / filename
        if source.is_file():
            manifest[filename] = (source.stat().st_size, md5_of_file(source))
    return manifest


def compare_manifests(src, dst):
    """
    Diff two manifests; any difference at all fails verification.

    Separates missing/extra/mismatched so the report says what KIND of damage
    occurred, not merely that something differs.
    """
    diff = ManifestDiff()

    for relpath in sorted(src):
        if relpath not in dst:
            diff.missing.append(relpath)
        elif src[relpath] != dst[relpath]:
            diff.mismatched.append(relpath)

    for relpath in sorted(dst):
        if relpath not in src:
            diff.extra.append(relpath)

    return diff


def rsync_excludes():
    """Build the rsync --exclude flags equivalent to the manifest exclusions."""
    flags = []
    for name in sorted(EXCLUDED_DIR_NAMES | EXCLUDED_BASENAMES):
        flags.extend(["--exclude", name])
    for prefix in EXCLUDED_NAME_PREFIXES:
        flags.extend(["--exclude", f"{prefix}*"])
    return flags


def find_previous_snapshot(snapshots_dir):
    """Return the newest dated snapshot tree, or None on the first sync."""
    if not snapshots_dir.is_dir():
        return None
    candidates = sorted(d for d in snapshots_dir.iterdir() if d.is_dir())
    if candidates:
        return candidates[-1]
    return None


def run_sync(dest, dry_run=False):
    """
    Mirror the repo into a new dated --link-dest tree and repoint `current`.

    The previous tree is named BEFORE rsync runs, so a bad sync can never
    damage history: every prior version remains a complete browsable tree.
    """
    if not dest.is_dir():
        print(f"ERROR: destination {dest} is not mounted")
        return 1

    backup_root = dest / BACKUP_SUBDIR
    snapshots_dir = backup_root / "snapshots"
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    new_tree = snapshots_dir / stamp
    previous = find_previous_snapshot(snapshots_dir)

    print(f"Sync source:      {SCRIPT_DIR} (backup set only: {', '.join(BACKUP_SOURCE_DIRS)} + caches)")
    print(f"Sync destination: {new_tree}")
    print(f"Link-dest base:   {previous if previous else '(first sync)'}\n")

    if not dry_run:
        snapshots_dir.mkdir(parents=True, exist_ok=True)

    for dirname in BACKUP_SOURCE_DIRS:
        source = SCRIPT_DIR / dirname
        if not source.is_dir():
            continue
        cmd = ["rsync", "-a", "--delete"]
        if dry_run:
            cmd.extend(["--dry-run", "--verbose"])
        if previous and (previous / dirname).is_dir():
            cmd.extend(["--link-dest", str(previous / dirname)])
        cmd.extend(rsync_excludes())
        cmd.extend([f"{source}/", str(new_tree / dirname)])
        print(f"Syncing {dirname}/ ...")
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"\nERROR: rsync exited {result.returncode} on {dirname}")
            return result.returncode

    cache_files = [str(SCRIPT_DIR / f) for f in BACKUP_SOURCE_FILES
                   if (SCRIPT_DIR / f).is_file()]
    if cache_files:
        cmd = ["rsync", "-a"]
        if dry_run:
            cmd.extend(["--dry-run", "--verbose"])
        cmd.extend(cache_files + [str(new_tree) + "/"])
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"\nERROR: rsync exited {result.returncode} on cache files")
            return result.returncode

    if not dry_run:
        current_link = backup_root / "current"
        if current_link.is_symlink() or current_link.exists():
            current_link.unlink()
        current_link.symlink_to(new_tree)
        print(f"\ncurrent -> {new_tree}")

    print("\nSync complete." if not dry_run else "\nDry run complete — nothing written.")
    return 0


def run_verify(dest):
    """Full-manifest comparison of the repo against the drive's current tree."""
    current = dest / BACKUP_SUBDIR / "current"
    if not current.exists():
        print(f"ERROR: no current backup tree at {current}")
        return 1

    print(f"Building source manifest from {SCRIPT_DIR} (backup set only) ...")
    src_manifest = build_backup_manifest(SCRIPT_DIR, progress=True)
    print(f"  {len(src_manifest)} files hashed.")

    print(f"Building destination manifest from {current.resolve()} ...")
    dst_manifest = build_backup_manifest(current.resolve(), progress=True)
    print(f"  {len(dst_manifest)} files hashed.")

    diff = compare_manifests(src_manifest, dst_manifest)

    manifests_dir = dest / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifests_dir / f"{datetime.now().strftime('%Y-%m-%d-%H%M')}.json"
    manifest_path.write_text(json.dumps(src_manifest, indent=0, sort_keys=True))
    print(f"Source manifest written to {manifest_path}")

    for label, entries in (("MISSING on drive", diff.missing),
                           ("EXTRA on drive", diff.extra),
                           ("MISMATCHED content", diff.mismatched)):
        if entries:
            print(f"\n{label} ({len(entries)}):")
            for relpath in entries:
                print(f"  {relpath}")

    if diff.ok:
        print("\n✅ VERIFIED: destination matches source exactly.")
        return 0

    print("\n❌ VERIFICATION FAILED — do not delete any source copies.")
    return 1


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["sync", "verify"])
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.mode == "sync":
        return run_sync(args.dest, dry_run=args.dry_run)
    return run_verify(args.dest)


if __name__ == "__main__":
    sys.exit(main())
