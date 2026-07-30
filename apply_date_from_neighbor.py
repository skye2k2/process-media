#!/usr/bin/env python3
"""
apply_date_from_neighbor.py — Stamp NO_EXIF files with a date borrowed from
their nearest-preceding sibling in the same DCIM bucket.

Background
----------
The NAS Nikon archive contains a cluster of files with no EXIF date, most
likely edited copies (rotated, cropped) whose originals were subsequently
deleted before the EXIF metadata could be propagated. Because the cluster is
localized and files are numbered sequentially (DSCN_XXXX), the shot date of
the immediately-preceding file by number is a reliable proxy.

The script does NOT modify any EXIF tags. It sets the macOS filesystem
modification timestamp (and optionally the creation timestamp) via
`touch -t` so that organize_archive.py — which falls back to mtime when EXIF
is absent — will place these files in the correct year/month folder.

This is intentionally a SEPARATE step from ingestion. Run reconcile first,
collect the NO_EXIF list, review it, then run this script with --dry-run
before committing.

Usage
-----
    python3 apply_date_from_neighbor.py --reconcile-cache reconcile_cache.json
    python3 apply_date_from_neighbor.py --reconcile-cache reconcile_cache.json --dry-run
    python3 apply_date_from_neighbor.py --reconcile-cache reconcile_cache.json --set-created

Arguments
---------
--reconcile-cache PATH  Path to the JSON cache produced by reconcile_nikon_archive.py.
                        The script reads NO_EXIF entries from this cache.
--dry-run               Print what would be done without touching any file.
--set-created           Also set the filesystem creation date (macOS only;
                        uses SetFile from Xcode command line tools). If the
                        tool is unavailable the flag is silently ignored.
--verbose               Print neighbor-lookup details for every file.
"""

# node scripts use the console
# pylint: disable=no-console

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


# Matches DSCN2542, DSC_0001, DSCN_2542, etc. — captures the 4-digit counter.
DSCN_PATTERN = re.compile(r'DSC[N_]?[-_]?(\d{4})', re.IGNORECASE)


# ============================================================================
# EXIF / DATE HELPERS
# ============================================================================

def extract_exif_date(file_path):
    """
    Return the EXIF DateTimeOriginal (or CreateDate) for a single file.

    Runs exiftool on one file — this is acceptable here because the caller
    only invokes it for neighbor files, not for every file in the batch.

    Args:
        file_path: Path to the file

    Returns:
        datetime if found, None otherwise
    """
    try:
        proc = subprocess.run(
            [
                "exiftool", "-json", "-fast2",
                "-DateTimeOriginal", "-CreateDate",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        if proc.returncode != 0 or not proc.stdout.strip():
            return None

        entries = json.loads(proc.stdout)

        if not entries:
            return None

        entry = entries[0]

        for field in ("DateTimeOriginal", "CreateDate"):
            raw = entry.get(field)

            if raw and not raw.startswith("0000"):
                try:
                    parsed = datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")

                    if parsed.year > 1980:
                        return parsed

                except ValueError:
                    continue

    except Exception:
        pass

    return None


def find_nearest_dated_predecessor(target_path, no_exif_paths):
    """
    Walk backward through DSCN counter values in the same directory until a
    sibling with a valid EXIF date is found, skipping over any files that are
    themselves in the NO_EXIF set.

    This handles a dense cluster of dateless files: rather than stopping at
    the first predecessor and reporting "neighbor also lacks EXIF date", the
    function keeps walking until it clears the cluster or runs out of candidates.

    Falls back to alphabetical ordering if no DSCN pattern is present.

    Args:
        target_path:   Path to the NO_EXIF file being processed
        no_exif_paths: set of Path objects known to lack EXIF (the full cluster),
                       used to skip them without an extra exiftool call

    Returns:
        (Path, str, datetime|None):
            - neighbor Path (the closest dated predecessor), or None
            - reason string for logging
            - EXIF date of that neighbor (already fetched), or None
    """
    target_match = DSCN_PATTERN.search(target_path.stem)

    if not target_match:
        # No DSCN counter — alphabetical walk-back
        siblings = sorted(
            p for p in target_path.parent.iterdir()
            if p.is_file() and p != target_path
        )
        preceding = [p for p in siblings if p.name < target_path.name]

        for candidate in reversed(preceding):
            if candidate in no_exif_paths:
                continue

            date = extract_exif_date(candidate)

            if date:
                return candidate, "alphabetical predecessor", date

        return None, "No dated alphabetical predecessor found", None

    target_counter = int(target_match.group(1))

    # Build a sorted list of (counter, path) for all DSCN siblings with
    # counter < target. Sort descending so we walk from closest to farthest.
    candidates = []

    for sibling in target_path.parent.iterdir():
        if not sibling.is_file() or sibling == target_path:
            continue

        sib_match = DSCN_PATTERN.search(sibling.stem)

        if not sib_match:
            continue

        sib_counter = int(sib_match.group(1))

        if sib_counter < target_counter:
            candidates.append((sib_counter, sibling))

    if not candidates:
        return None, f"No sibling with counter < {target_counter:04d} found", None

    candidates.sort(key=lambda pair: pair[0], reverse=True)

    skipped_count = 0

    for sib_counter, sib_path in candidates:
        if sib_path in no_exif_paths:
            # Part of the same cluster — skip without an exiftool call
            skipped_count += 1
            continue

        date = extract_exif_date(sib_path)

        if date:
            reason = f"DSCN predecessor {sib_counter:04d}"

            if skipped_count > 0:
                reason += f" (skipped {skipped_count} dateless file(s))"

            return sib_path, reason, date

    return None, f"No dated predecessor found before counter {target_counter:04d}", None


# ============================================================================
# TIMESTAMP APPLICATION
# ============================================================================

def apply_mtime(file_path, date, dry_run):
    """
    Set the file's modification timestamp via `touch -t`.

    The format required by touch -t is: [[CC]YY]MMDDhhmm[.ss]
    e.g., 201308151430.00

    Args:
        file_path: Path to the file to stamp
        date:      datetime to apply
        dry_run:   If True, only print; do not execute

    Returns:
        bool: True if successful (or dry_run), False on error
    """
    # touch -t format: CCYYMMDDhhmm.ss
    touch_stamp = date.strftime("%Y%m%d%H%M.%S")
    cmd = ["touch", "-t", touch_stamp, str(file_path)]

    if dry_run:
        print(f"    [dry-run] touch -t {touch_stamp} {file_path.name}")
        return True

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            print(f"    ERROR: touch failed for {file_path.name}: {result.stderr.strip()}")
            return False

        return True

    except Exception as err:
        print(f"    ERROR: touch exception for {file_path.name}: {err}")
        return False


def apply_created_date(file_path, date, dry_run):
    """
    Set the macOS HFS+ creation date via SetFile (requires Xcode CLI tools).

    This is a best-effort operation — silently skips if SetFile is unavailable.
    Modification date is sufficient for organize_archive.py's fallback logic,
    so creation date is purely informational.

    Args:
        file_path: Path to the file
        date:      datetime to apply
        dry_run:   If True, only print; do not execute

    Returns:
        bool: True if applied or skipped gracefully, False on hard error
    """
    try:
        subprocess.run(["which", "SetFile"], capture_output=True, check=True)
    except subprocess.CalledProcessError:
        # SetFile not available — not an error
        return True

    # SetFile -d format: "MM/DD/YYYY HH:MM:SS"
    setfile_stamp = date.strftime("%m/%d/%Y %H:%M:%S")
    cmd = ["SetFile", "-d", setfile_stamp, str(file_path)]

    if dry_run:
        print(f"    [dry-run] SetFile -d '{setfile_stamp}' {file_path.name}")
        return True

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            print(f"    WARNING: SetFile failed for {file_path.name}: {result.stderr.strip()}")
            return False

        return True

    except Exception as err:
        print(f"    WARNING: SetFile exception for {file_path.name}: {err}")
        return False


# ============================================================================
# MAIN
# ============================================================================

def load_no_exif_entries(cache_path):
    """
    Read the reconcile cache and return all NO_EXIF entries sorted by
    source path (bucket/filename order, alphabetical within bucket).

    Args:
        cache_path: Path to reconcile_cache.json

    Returns:
        list of dicts (reconciliation result entries)
    """
    with open(cache_path, "r") as fh:
        data = json.load(fh)

    entries = [r for r in data["results"] if r["category"] == "NO_EXIF"]

    # Sort by bucket then filename so output matches the reconcile report order
    entries.sort(key=lambda r: (Path(r["source"]).parent.name, Path(r["source"]).name))

    return entries


def main():
    """
    Entry point. Reads NO_EXIF entries from a reconcile cache, finds a date
    donor (the immediately-preceding sibling file by DSCN counter), and stamps
    the target file's mtime so organize_archive.py can place it correctly.

    When --date is supplied the neighbor lookup is skipped entirely and every
    file in the NO_EXIF list receives that exact date.
    """
    parser = argparse.ArgumentParser(
        description="Stamp NO_EXIF NAS files with a date borrowed from their DSCN predecessor."
    )
    parser.add_argument(
        "--reconcile-cache",
        required=True,
        metavar="PATH",
        help="Path to the JSON cache produced by reconcile_nikon_archive.py",
    )
    parser.add_argument(
        "--date",
        metavar="YYYYMMDD",
        help=(
            "Override date to apply to every NO_EXIF file instead of borrowing "
            "from the DSCN predecessor. Format: YYYYMMDD (e.g. 20190601). "
            "Time is always set to midnight."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without touching any files",
    )
    parser.add_argument(
        "--set-created",
        action="store_true",
        help="Also set the macOS creation date via SetFile (requires Xcode CLI tools)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print neighbor-lookup details for every file",
    )

    args = parser.parse_args()

    cache_path = Path(args.reconcile_cache)

    if not cache_path.exists():
        print(f"ERROR: Cache file not found: {cache_path}", file=sys.stderr)
        sys.exit(1)

    # Validate and parse --date override up front so we fail fast before
    # loading the cache if the format is wrong.
    override_date = None

    if args.date:
        try:
            override_date = datetime.strptime(args.date, "%Y%m%d").replace(
                hour=0, minute=0, second=0
            )
        except ValueError:
            print(
                f"ERROR: --date '{args.date}' is not in YYYYMMDD format.",
                file=sys.stderr,
            )
            sys.exit(1)

    print(f"Loading NO_EXIF entries from: {cache_path}")
    no_exif_entries = load_no_exif_entries(cache_path)

    if not no_exif_entries:
        print("No NO_EXIF entries found. Nothing to do.")
        sys.exit(0)

    print(f"Found {len(no_exif_entries)} NO_EXIF file(s) to process.")

    if args.dry_run:
        print("DRY RUN — no files will be modified.\n")
    else:
        print()

    # Pre-build the full set of NO_EXIF paths so the cluster walk-back can
    # skip them without redundant exiftool calls.
    no_exif_paths = {Path(e["source"]) for e in no_exif_entries}

    success_count = 0
    skip_count = 0
    error_count = 0

    for entry in no_exif_entries:
        source_path = Path(entry["source"])
        bucket = source_path.parent.name

        if not source_path.exists():
            print(f"  SKIP {bucket}/{source_path.name} - file not found on disk")
            skip_count += 1
            continue

        if override_date:
            stamped_date = override_date
            date_str = stamped_date.strftime("%Y-%m-%d")
            reason = f"--date override"

            if args.verbose or args.dry_run:
                print(f"  {bucket}/{source_path.name} — using {date_str} ({reason})")
        else:
            neighbor, reason, neighbor_date = find_nearest_dated_predecessor(
                source_path, no_exif_paths
            )

            if neighbor is None or neighbor_date is None:
                print(f"  SKIP {bucket}/{source_path.name} - {reason}")
                skip_count += 1
                continue

            # Truncate to midnight — the exact second of the predecessor shot
            # is meaningless for edited copies.
            stamped_date = neighbor_date.replace(hour=0, minute=0, second=0)
            date_str = stamped_date.strftime("%Y-%m-%d")

            if args.verbose or args.dry_run:
                print(
                    f"  {bucket}/{source_path.name}"
                    f" — using {date_str} from {neighbor.name} ({reason})"
                )

        mtime_ok = apply_mtime(source_path, stamped_date, args.dry_run)

        # Always set creation date when an explicit --date override is given,
        # since an incorrect "Content created" timestamp is exactly the problem
        # being corrected. Otherwise, only set it if --set-created was passed.
        if args.set_created or override_date:
            apply_created_date(source_path, stamped_date, args.dry_run)

        if mtime_ok:
            if not args.dry_run and not args.verbose:
                print(f"  {bucket}/{source_path.name} - stamped {date_str}")

            success_count += 1
        else:
            error_count += 1

    print()
    print(f"Done. Stamped: {success_count}  Skipped: {skip_count}  Errors: {error_count}")

    if not args.dry_run and success_count > 0:
        print()
        print("Next step: re-run reconcile to verify these files now have resolvable dates.")
        print("  python3 reconcile_nikon_archive.py /Volumes/photosync/NIKON --no-md5")


if __name__ == "__main__":
    main()
