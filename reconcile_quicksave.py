#!/usr/bin/env python3
"""
Prove the Desktop quick-save is fully represented before it is deleted.

The quick-save is a February-2026 point-in-time copy of Organized_Photos/
Organized_Videos. Deleting it is the one irreversible step in the backup
plan, and the backup-verified gate (archive→drive) proves nothing about
quick-save→archive. This tool classifies every media file in the quick-save
into exactly one explained class:

    present     - same filename exists in the live archive with the same size
    modified    - filename exists but every size differs (or --deep found
                  different bytes) — surfaced for human review
    removed     - absent, but its name appears in a recorded removal script —
                  a deliberate curation deletion
    unexplained - absent with no record — BLOCKS deletion until reviewed

Writes a dated report to _records/ so the deletion decision stays auditable.

Usage:
    .venv/bin/python reconcile_quicksave.py "<quicksave root>" [--deep]
"""

import argparse
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from backup_archive import md5_of_file
from media_utils import MEDIA_EXTENSIONS
from removal_history import RemovalHistory

SCRIPT_DIR = Path(__file__).parent
ARCHIVE_ROOTS = (SCRIPT_DIR / "Organized_Photos", SCRIPT_DIR / "Organized_Videos")
RESCUED_SCRIPTS_DIR = SCRIPT_DIR / "_records" / "removal-scripts"
REPORT_DIR = SCRIPT_DIR / "_records"

# Progress cadence while walking tens of thousands of files.
PROGRESS_EVERY_FILES = 2000


def build_archive_index(roots=ARCHIVE_ROOTS):
    """
    Index the live archive as {bare filename: [(relpath, size), ...]}.

    Filename (not path) is the lookup key because the event-folder pass moved
    thousands of files to new folders without renaming them; size narrows the
    match cheaply before any optional deep hash.
    """
    index = defaultdict(list)
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
                index[path.name].append(
                    (path.relative_to(SCRIPT_DIR).as_posix(), path.stat().st_size))
    return dict(index)


def classify_quicksave_file(relpath, size, archive_index, history):
    """
    Place one quick-save media file into its explained class.

    Order matters: a name+size match beats everything (the file survives);
    a name-only match is 'modified' (same asset, different bytes — review);
    a recorded removal explains absence; anything else blocks the deletion.
    """
    filename = Path(relpath).name
    candidates = archive_index.get(filename, [])

    if candidates:
        for _, candidate_size in candidates:
            if candidate_size == size:
                return "present"
        return "modified"

    if history.was_removed(filename):
        return "removed"

    return "unexplained"


def deep_compare(quicksave_file, candidates):
    """Confirm a 'present' match by content hash against its size-matched candidates."""
    source_digest = md5_of_file(quicksave_file)
    for rel, _ in candidates:
        candidate = SCRIPT_DIR / rel
        if candidate.is_file() and md5_of_file(candidate) == source_digest:
            return True
    return False


def load_history():
    """Union removal records from the archive exports and the rescued scripts."""
    primary = RemovalHistory.from_directory()
    rescued = RemovalHistory.from_directory(RESCUED_SCRIPTS_DIR)
    names = primary.names | rescued.names
    sources = {**primary.sources, **rescued.sources}
    return RemovalHistory(names=names, sources=sources)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("quicksave_root", type=Path)
    parser.add_argument("--deep", action="store_true",
                        help="md5-confirm every 'present' match (slow: reads both copies)")
    args = parser.parse_args()

    if not args.quicksave_root.is_dir():
        print(f"ERROR: {args.quicksave_root} is not a directory")
        return 2

    print("Indexing live archive...")
    archive_index = build_archive_index()
    print(f"  {sum(len(v) for v in archive_index.values())} files indexed.")

    history = load_history()
    print(history.describe())

    classes = defaultdict(list)
    count = 0

    for subdir in ("Organized_Photos", "Organized_Videos"):
        root = args.quicksave_root / subdir
        if not root.is_dir():
            print(f"  Note: quick-save has no {subdir}/ — skipping")
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in MEDIA_EXTENSIONS:
                continue
            relpath = path.relative_to(args.quicksave_root).as_posix()
            size = path.stat().st_size
            verdict = classify_quicksave_file(relpath, size, archive_index, history)

            if verdict == "present" and args.deep:
                filename = path.name
                size_matched = [c for c in archive_index.get(filename, []) if c[1] == size]
                if not deep_compare(path, size_matched):
                    verdict = "modified"

            classes[verdict].append(relpath)
            count += 1
            if count % PROGRESS_EVERY_FILES == 0:
                print(f"  Classified {count} files...")

    report_path = REPORT_DIR / f"reconcile-quicksave-{datetime.now().strftime('%Y-%m-%d')}.txt"
    lines = [
        f"Quick-save reconciliation — {datetime.now().isoformat(timespec='seconds')}",
        f"Quick-save root: {args.quicksave_root}",
        f"Mode: {'deep (md5-confirmed)' if args.deep else 'name+size'}",
        "",
        "Counts:",
    ]
    for verdict in ("present", "removed", "modified", "unexplained"):
        lines.append(f"  {verdict:12s} {len(classes[verdict])}")
    for verdict in ("modified", "unexplained"):
        if classes[verdict]:
            lines.append("")
            lines.append(f"{verdict.upper()} files:")
            lines.extend(f"  {relpath}" for relpath in classes[verdict])

    report_path.write_text("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines[4:9]))
    print(f"\nReport written to {report_path}")

    if classes["modified"] or classes["unexplained"]:
        print("\n❌ NOT CLEAR FOR DELETION — review the report.")
        return 1

    print("\n✅ Every quick-save file is present or deliberately removed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
