#!/usr/bin/env python3
"""
Nikon Archive Reconciliation Tool

Compares a Nikon NAS archive directory against the existing Organized_Photos/
archive WITHOUT moving, copying, or modifying any files.

This is a pure read/analysis tool designed for the specific challenge of
Nikon cameras: DSCN_XXXX.JPG filenames carry no embedded date, so comparison
must rely entirely on EXIF metadata. Additionally, because photos from this
camera have been manually renamed and moved for years, we may have:
  - Exact duplicates (identical bytes, different path or name)
  - Visual duplicates (same shot, different crop/edit, different EXIF timestamp)
  - Numbering collisions (two cameras that both produced DSCN_0001.JPG for
    completely different events on different days)
  - True new content (photos not yet in the archive at all)

Output categories:
  EXACT_MATCH       Byte-identical file already exists in archive (MD5 match).
                    Safe to skip.
  DATE_SIZE_MATCH   EXIF date + file size within 5% matches an archived file.
                    High confidence duplicate; review before skipping.
  DEST_COLLISION     Would land in the same YYYY/MM MonthName/ directory with
                    the same filename as an existing file, but content differs.
                    This is the "different camera, same DSCN counter" case.
                    workflow_archive.py will append a camera model suffix
                    (e.g., _S3100, _S3500) to the filename on ingestion so
                    both files survive. Review to confirm they are distinct.
  NEW_CONTENT       No match found by any strategy. Candidate for ingestion.
  NO_EXIF           EXIF extraction failed or returned no date. Cannot compare
                    by date. Flagged for manual review.
  ERROR             File could not be read at all.

Usage:
    python3 reconcile_nikon_archive.py /Volumes/photosync/NIKON
    python3 reconcile_nikon_archive.py /Volumes/photosync/NIKON --verbose
    python3 reconcile_nikon_archive.py /Volumes/photosync/NIKON --output report.json
    python3 reconcile_nikon_archive.py /Volumes/photosync/NIKON --cache-only
    python3 reconcile_nikon_archive.py /Volumes/photosync/NIKON --no-md5
        (skip byte-level comparison — faster first pass)

Report:
    Results are written to a .TMP_reconcile_cache.json beside the archive
    directory (or at --output path) so that repeated runs are fast.
    A human-readable summary is always printed to stdout.

Caveats:
    - MD5 computation for 5000 files is I/O-bound. Expect 1-3 minutes on
      spinning disk, 20-40 seconds on SSD/NAS with a warm OS cache.
    - EXIF extraction is batched (1000 files per exiftool call) for performance.
    - This tool does NOT write to Organized_Photos/ or TO_PROCESS/ under any
      circumstances. It is safe to run while the archive is being reviewed.
"""

# pylint: disable=no-console -- node scripts use the console

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from media_utils import MONTH_NAMES, PHOTO_EXTENSIONS, VIDEO_EXTENSIONS

SCRIPT_DIR = Path(__file__).parent
DEFAULT_ARCHIVE_DIR = SCRIPT_DIR / "Organized_Photos"

# Extensions we can meaningfully compare
MEDIA_EXTENSIONS = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS

# EXIF batch size — tuned to avoid exiftool argument-list overflow on most OSes
EXIF_BATCH_SIZE = 500

# Size tolerance for date+size matching (±5%)
SIZE_TOLERANCE = 0.05

# Output categories
CAT_EXACT_MATCH = "EXACT_MATCH"
CAT_DATE_SIZE_MATCH = "DATE_SIZE_MATCH"
CAT_DEST_COLLISION = "DEST_COLLISION"
CAT_NEW_CONTENT = "NEW_CONTENT"
CAT_NO_EXIF = "NO_EXIF"
CAT_ERROR = "ERROR"


# ============================================================================
# EXIF EXTRACTION
# ============================================================================

def batch_extract_exif(file_paths):
    """
    Extract DateTimeOriginal (or fallback CreateDate) for a batch of files.

    Uses exiftool's JSON output mode for efficiency — a single process call
    handles up to EXIF_BATCH_SIZE files, reducing subprocess overhead by ~500x
    compared to per-file calls.

    Args:
        file_paths: List of Path objects

    Returns:
        dict: {Path: datetime | None}  (None = extraction failed or no date)
    """
    result = {}
    total = len(file_paths)
    processed = 0

    # Process in chunks to avoid OS arg-list size limits
    chunk_index = 0

    while processed < total:
        chunk = file_paths[processed : processed + EXIF_BATCH_SIZE]
        chunk_index += 1

        try:
            proc = subprocess.run(
                [
                    "exiftool", "-json", "-fast2",
                    "-DateTimeOriginal",
                    "-CreateDate",
                    "-MediaCreateDate",
                ] + [str(p) for p in chunk],
                capture_output=True,
                text=True,
                check=False,
            )

            if proc.returncode == 0 and proc.stdout.strip():
                entries = json.loads(proc.stdout)

                for entry in entries:
                    source_file = Path(entry.get("SourceFile", ""))
                    parsed_date = None

                    for field in ("DateTimeOriginal", "CreateDate", "MediaCreateDate"):
                        raw = entry.get(field)

                        if raw and not raw.startswith("0000"):
                            try:
                                parsed_date = datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
                                break
                            except ValueError:
                                continue

                    result[source_file] = parsed_date

        except (json.JSONDecodeError, Exception) as err:
            print(f"  WARNING: EXIF batch {chunk_index} failed: {err}")

        processed += len(chunk)

        if total > EXIF_BATCH_SIZE:
            print(f"  EXIF extraction: {min(processed, total)}/{total} files...")

    return result


# ============================================================================
# MD5 COMPUTATION
# ============================================================================

def compute_md5(file_path, chunk_size=65536):
    """
    Compute MD5 hash of a file for byte-level duplicate detection.

    Args:
        file_path: Path to the file
        chunk_size: Read block size in bytes (64KB default)

    Returns:
        str: Hex MD5 digest, or None if the file could not be read
    """
    h = hashlib.md5()

    try:
        with open(file_path, "rb") as fh:
            while True:
                block = fh.read(chunk_size)

                if not block:
                    break

                h.update(block)

        return h.hexdigest()

    except OSError:
        return None


# ============================================================================
# ARCHIVE INDEX
# ============================================================================

def build_archive_md5_index(archive_dir):
    """
    Walk Organized_Photos/ and build a set of MD5 hashes for all media files.

    This is the ground truth for exact-match detection. We trade off upfront
    cost (~5 min for 30k files) against the per-comparison cost later.

    Args:
        archive_dir: Path to Organized_Photos/

    Returns:
        dict: {md5_hex: [Path, ...]}  (list because hash collisions are theoretically possible)
    """
    index = defaultdict(list)
    all_files = [
        p for p in archive_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in {e.lower() for e in MEDIA_EXTENSIONS}
    ]

    total = len(all_files)
    print(f"  Building MD5 index for {total} archived files...")
    start_time = time.time()

    for i, file_path in enumerate(all_files):
        md5 = compute_md5(file_path)

        if md5:
            index[md5].append(file_path)

        if (i + 1) % 500 == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed
            remaining = (total - i - 1) / rate if rate > 0 else 0
            print(f"  MD5 index: {i + 1}/{total} ({remaining:.0f}s remaining)...")

    elapsed = time.time() - start_time
    print(f"  MD5 index complete: {len(index)} unique hashes in {elapsed:.1f}s")

    return index


def build_archive_date_index(archive_dir):
    """
    Walk Organized_Photos/ and extract EXIF dates for all media files,
    returning an index keyed by YYYYMMDD_HHMMSS date string.

    Used for date+size matching when MD5 doesn't match (e.g., same photo
    that was lightly re-encoded or had metadata stripped).

    Args:
        archive_dir: Path to Organized_Photos/

    Returns:
        dict: {"YYYYMMDD_HHMMSS": [(Path, size), ...]}
    """
    all_files = [
        p for p in archive_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in {e.lower() for e in MEDIA_EXTENSIONS}
    ]

    print(f"  Extracting EXIF dates from {len(all_files)} archived files...")
    exif_results = batch_extract_exif(all_files)

    date_index = defaultdict(list)

    for file_path, date in exif_results.items():
        if date:
            key = date.strftime("%Y%m%d_%H%M%S")

            try:
                size = file_path.stat().st_size
            except OSError:
                size = 0

            date_index[key].append((file_path, size))

    print(f"  Date index: {len(date_index)} unique timestamps")

    return date_index


def build_archive_dest_index(archive_dir):
    """
    Index every file already in the archive by (year, month_folder, filename).

    This mirrors the destination key that organize_archive.py would compute
    before placing a new file, so we can detect exact filename+folder conflicts
    before ingestion happens.

    Event subfolders (e.g., 2013/05 May/New Volkswagen/) are intentionally
    flattened — organize_archive.py always places files directly into the
    YYYY/MM MonthName/ level, so the collision key uses only those two parts
    plus the filename.

    Args:
        archive_dir: Path to Organized_Photos/

    Returns:
        dict: {(year_str, month_folder, filename): Path}
              e.g. {("2013", "08 August", "DSCN2542.JPG"): Path(...)}
    """
    index = {}

    for p in archive_dir.rglob("*"):
        if not p.is_file():
            continue

        if p.suffix.lower() not in {e.lower() for e in MEDIA_EXTENSIONS}:
            continue

        try:
            rel = p.relative_to(archive_dir)
            parts = rel.parts

            # Require at least YYYY/MM MonthName/filename structure
            if len(parts) >= 2 and re.match(r'^\d{4}$', parts[0]) and re.match(r'^\d{2} [A-Z]', parts[1]):
                index[(parts[0], parts[1], p.name)] = p
        except ValueError:
            continue

    return index


def extract_camera_model_suffix(exif_data):
    """
    Derive a short camera-model suffix from EXIF Model field.

    Used to disambiguate filenames when two cameras share the same DSCN
    counter range. Returns a string like "_S3100" or "_S3500" that can be
    appended to the stem before the extension.

    Only the model number portion is used (not the full "COOLPIX S3500" string)
    to keep filenames short. If the model is unknown or unparseable, returns
    an empty string (no suffix added).

    Args:
        exif_data: dict from exiftool JSON output for a single file

    Returns:
        str: e.g. "_S3500", "_S3100", "_D3000", or ""
    """
    model = exif_data.get("Model", "") or ""

    # Extract model number: last space-separated token that starts with a letter
    # followed by digits. Handles "COOLPIX S3500", "D3000", "NIKON D3000", etc.
    tokens = model.strip().split()

    for token in reversed(tokens):
        if re.match(r'^[A-Za-z]\d', token):
            return f"_{token}"

    return ""


def compute_destination_filename(source_path, model_suffix):
    """
    Compute the filename that organize_archive.py would assign to this file,
    including the camera model suffix when one is provided.

    DSCN2542.JPG from a S3500 becomes DSCN2542_S3500.JPG.
    This mirrors how organize_archive.py appends person suffixes like "_Clif".

    Args:
        source_path:  Path to the NAS source file
        model_suffix: String like "_S3500" or "" if no suffix needed

    Returns:
        str: final filename (stem + model_suffix + ext)
    """
    if not model_suffix:
        return source_path.name

    return f"{source_path.stem}{model_suffix}{source_path.suffix}"


def compute_destination_path(source_path, exif_date, model_suffix, archive_dir):
    """
    Compute the full path where organize_archive.py would place this file.

    Args:
        source_path:  Path to the NAS source file
        exif_date:    datetime from EXIF (required; returns None if None)
        model_suffix: Camera model suffix string (e.g. "_S3500" or "")
        archive_dir:  Root Organized_Photos/ directory

    Returns:
        Path: predicted destination, or None if date is unavailable
    """
    if not exif_date:
        return None

    month_folder = MONTH_NAMES[exif_date.month - 1]
    dest_dir = archive_dir / str(exif_date.year) / month_folder
    filename = compute_destination_filename(source_path, model_suffix)

    return dest_dir / filename


# ============================================================================
# RECONCILIATION LOGIC
# ============================================================================

def classify_file(
    source_path,
    source_md5,
    source_exif_date,
    source_model_suffix,
    archive_md5_index,
    archive_date_index,
    archive_dest_index,
    archive_dir,
):
    """
    Classify a single NAS file against the existing archive.

    Classification is attempted in priority order:
    1. Exact byte match (MD5) — highest confidence; safe to skip
    2. Date + size match — high-confidence duplicate
    3. Destination collision — the file would land in the same
       YYYY/MM MonthName/ directory with the same filename (after model
       suffix is applied) as an existing file, but byte content differs.
       This is the "different camera, same DSCN counter" case.
    4. No EXIF date — cannot compute destination; needs manual review
    5. No match — genuinely new content; ready to ingest

    Args:
        source_path:         Path to the NAS file being classified
        source_md5:          Pre-computed MD5 of the source file (or None)
        source_exif_date:    datetime from EXIF, or None
        source_model_suffix: Camera model suffix, e.g. "_S3500" or ""
        archive_md5_index:   {md5: [Path, ...]}
        archive_date_index:  {"YYYYMMDD_HHMMSS": [(Path, size), ...]}
        archive_dest_index:  {(year, month_folder, filename): Path}
        archive_dir:         Root Organized_Photos/ directory

    Returns:
        dict with keys: category, source, match, dest, note
    """
    if source_md5 is None and not source_exif_date:
        return {
            "category": CAT_ERROR,
            "source": str(source_path),
            "match": None,
            "dest": None,
            "note": "Could not read file — permissions or corruption",
        }

    # 1. Exact byte match
    if source_md5 and source_md5 in archive_md5_index:
        match_path = archive_md5_index[source_md5][0]

        return {
            "category": CAT_EXACT_MATCH,
            "source": str(source_path),
            "match": str(match_path),
            "dest": None,
            "note": "Byte-identical copy already in archive",
        }

    # Compute predicted destination (with model suffix baked in)
    dest_path = compute_destination_path(
        source_path, source_exif_date, source_model_suffix, archive_dir
    )

    # 2. Date + size match
    if source_exif_date:
        date_key = source_exif_date.strftime("%Y%m%d_%H%M%S")

        if date_key in archive_date_index:
            try:
                source_size = source_path.stat().st_size
            except OSError:
                source_size = 0

            for archived_path, archived_size in archive_date_index[date_key]:
                if archived_size == 0:
                    continue

                ratio = source_size / archived_size

                if (1 - SIZE_TOLERANCE) <= ratio <= (1 + SIZE_TOLERANCE):
                    size_diff_pct = abs(ratio - 1.0) * 100

                    return {
                        "category": CAT_DATE_SIZE_MATCH,
                        "source": str(source_path),
                        "match": str(archived_path),
                        "dest": str(dest_path) if dest_path else None,
                        "note": (
                            f"EXIF date {date_key} matches, size within "
                            f"{size_diff_pct:.1f}%"
                        ),
                    }

    # 3. Destination collision — same YYYY/MM MonthName/ + same final filename,
    #    content is not a byte or date+size match.
    if dest_path and source_exif_date:
        month_folder = MONTH_NAMES[source_exif_date.month - 1]
        year_str = str(source_exif_date.year)
        dest_filename = compute_destination_filename(source_path, source_model_suffix)
        collision_key = (year_str, month_folder, dest_filename)

        if collision_key in archive_dest_index:
            existing_path = archive_dest_index[collision_key]

            return {
                "category": CAT_DEST_COLLISION,
                "source": str(source_path),
                "match": str(existing_path),
                "dest": str(dest_path),
                "note": (
                    f"'{dest_filename}' already exists in "
                    f"{year_str}/{month_folder}/ with different content. "
                    f"Different camera, same DSCN counter."
                ),
            }

    # 4. No EXIF — cannot compute destination
    if not source_exif_date:
        return {
            "category": CAT_NO_EXIF,
            "source": str(source_path),
            "match": None,
            "dest": None,
            "note": "No EXIF date available; cannot classify reliably",
        }

    # 5. Genuinely new content
    return {
        "category": CAT_NEW_CONTENT,
        "source": str(source_path),
        "match": None,
        "dest": str(dest_path) if dest_path else None,
        "note": (
            f"Not in archive. Would land in: "
            f"{source_exif_date.year}/{MONTH_NAMES[source_exif_date.month - 1]}/"
            f" as {compute_destination_filename(source_path, source_model_suffix)}"
        ),
    }


# ============================================================================
# REPORT GENERATION
# ============================================================================

def print_summary(results, archive_dir, elapsed):
    """
    Print a human-readable reconciliation summary to stdout.

    Args:
        results:     List of classification dicts
        archive_dir: Path that was compared against
        elapsed:     Total elapsed time in seconds
    """
    by_category = defaultdict(list)

    for r in results:
        by_category[r["category"]].append(r)

    total = len(results)

    print("\n" + "=" * 72)
    print("NIKON ARCHIVE RECONCILIATION REPORT")
    print("=" * 72)
    print(f"  Compared against: {archive_dir}")
    print(f"  Total NAS files analyzed: {total}")
    if elapsed > 0:
        print(f"  Elapsed: {elapsed:.1f}s")
    print()

    categories_in_order = [
        CAT_EXACT_MATCH,
        CAT_DATE_SIZE_MATCH,
        CAT_DEST_COLLISION,
        CAT_NEW_CONTENT,
        CAT_NO_EXIF,
        CAT_ERROR,
    ]

    labels = {
        CAT_EXACT_MATCH:    "Exact duplicates   (byte-identical, safe to skip)",
        CAT_DATE_SIZE_MATCH:"Date+size match    (high-confidence duplicate)",
        CAT_DEST_COLLISION: "Dest clash         (same folder+name after suffix, diff content)",
        CAT_NEW_CONTENT:    "New content        (not yet in archive, ready to ingest)",
        CAT_NO_EXIF:        "No EXIF date       (manual review needed)",
        CAT_ERROR:          "Read errors        (permissions/corruption)",
    }

    for cat in categories_in_order:
        items = by_category.get(cat, [])
        label = labels[cat]
        print(f"  {len(items):>5}  {label}")

    print()

    # Detail lists for categories needing human attention.
    # Sorted alphabetically by "BUCKET/filename" so the caller can work through
    # them sequentially without hunting across folders.
    for cat in [CAT_DEST_COLLISION, CAT_NO_EXIF, CAT_ERROR]:
        items = by_category.get(cat, [])

        if not items:
            continue

        # Build display strings and sort before printing
        display_lines = []

        for item in items:
            source_path = Path(item["source"])
            # Use the immediate parent directory (DCIM bucket like "108NIKON")
            # as a short prefix so the caller knows which folder without the
            # full absolute path cluttering the line.
            bucket = source_path.parent.name
            label = f"{bucket}/{source_path.name}"

            note = item["note"]

            if item.get("match"):
                try:
                    match_rel = Path(item["match"]).relative_to(archive_dir)
                    note = f"{note} — conflicts with: {match_rel}"
                except ValueError:
                    note = f"{note} — conflicts with: {item['match']}"

            display_lines.append(f"  {label} - {note}")

        display_lines.sort()

        print(f"  {cat} ({len(display_lines)} files):")

        for line in display_lines:
            print(line)

        print()

    new_items = by_category.get(CAT_NEW_CONTENT, [])

    if new_items:
        print(f"  NEW_CONTENT -- {len(new_items)} files to potentially ingest:")
        print()

        # Group by year so the user can see the time distribution
        by_year = defaultdict(int)

        for item in new_items:
            # Pull year from dest path ("...2013/08 August/...") or note string
            dest = item.get("dest") or ""
            year_match = re.search(r'/(\d{4})/', dest) or re.search(r'(\d{4})/', item.get("note", ""))
            year = year_match.group(1) if year_match else "unknown"
            by_year[year] += 1

        for year in sorted(by_year):
            print(f"    {year}: {by_year[year]} file(s)")

        print()
        print("  To ingest new content:")
        print("    1. Copy/symlink the NAS NIKON directory into TO_PROCESS/")
        print("    2. python3 workflow_archive.py --dry-run")
        print("    3. python3 workflow_archive.py")
        print()

    print("=" * 72)


# ============================================================================
# CACHE MANAGEMENT
# ============================================================================

def load_run_cache(cache_path):
    """
    Load a previous run's classification results from disk.

    This allows re-running the summary without re-doing MD5 computation and
    EXIF extraction, which can take several minutes on a large NAS archive.

    Args:
        cache_path: Path to the JSON cache file

    Returns:
        list of classification dicts, or None if cache doesn't exist / is invalid
    """
    if not cache_path.exists():
        return None

    try:
        with open(cache_path, "r") as fh:
            data = json.load(fh)

        print(f"  Loaded {len(data['results'])} results from cache ({cache_path.name})")
        print(f"  Cache generated: {data.get('generated', 'unknown')}")

        # Migrate old POSSIBLE_COLLISION entries from previous cache format
        for r in data["results"]:
            if r.get("category") == "POSSIBLE_COLLISION":
                r["category"] = CAT_DEST_COLLISION
                r.setdefault("dest", None)

        return data["results"]

    except (json.JSONDecodeError, KeyError, IOError) as err:
        print(f"  WARNING: Cache file invalid ({err}), re-running analysis")

        return None


def save_run_cache(cache_path, results, source_dir, archive_dir):
    """
    Persist classification results to disk for fast re-runs.

    Args:
        cache_path:  Path to write the JSON cache
        results:     List of classification dicts
        source_dir:  NAS directory that was scanned
        archive_dir: Archive directory that was compared against
    """
    data = {
        "generated": datetime.now().isoformat(),
        "source_dir": str(source_dir),
        "archive_dir": str(archive_dir),
        "results": results,
    }

    with open(cache_path, "w") as fh:
        json.dump(data, fh, indent=2)

    print(f"  Results cached to: {cache_path.name}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Compare a Nikon NAS archive against Organized_Photos/ without moving anything.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 reconcile_nikon_archive.py /Volumes/photosync/NIKON
  python3 reconcile_nikon_archive.py /Volumes/photosync/NIKON --verbose
  python3 reconcile_nikon_archive.py /Volumes/photosync/NIKON --cache-only
  python3 reconcile_nikon_archive.py /Volumes/photosync/NIKON --output report.json
        """,
    )
    parser.add_argument(
        "source_dir",
        nargs="?",
        default=None,
        help="NAS archive directory to analyze (e.g., /Volumes/photosync/NIKON)",
    )
    parser.add_argument(
        "--archive-dir",
        default=None,
        help="Organized archive to compare against (default: ./Organized_Photos/)",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Path for JSON results cache (default: <source_dir>/.TMP_reconcile_cache.json)",
    )
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help=(
            "Load and display a previous run's cache without re-running analysis. "
            "Useful for reviewing results after a long scan."
        ),
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print each file's classification as it is determined",
    )
    parser.add_argument(
        "--no-md5",
        action="store_true",
        help=(
            "Skip MD5 computation (faster, but misses byte-identical files that "
            "have different EXIF dates or sizes)"
        ),
    )

    args = parser.parse_args()

    # -- Resolve paths -------------------------------------------------------

    if not args.source_dir:
        nas_default = Path("/Volumes/photosync/NIKON")

        if nas_default.exists():
            print(f"  No source directory specified; using default: {nas_default}")
            source_dir = nas_default
        else:
            print("ERROR: No source directory specified and /Volumes/photosync/NIKON not mounted.")
            print("       Mount the NAS first, or specify a path: python3 reconcile_nikon_archive.py /path/to/NIKON")
            sys.exit(1)
    else:
        source_dir = Path(args.source_dir)

    if not source_dir.exists():
        print(f"ERROR: Source directory does not exist: {source_dir}")
        sys.exit(1)

    archive_dir = Path(args.archive_dir) if args.archive_dir else SCRIPT_DIR / "Organized_Photos"

    if not archive_dir.exists():
        print(f"ERROR: Archive directory does not exist: {archive_dir}")
        print("       Run from the process-media directory or specify --archive-dir")
        sys.exit(1)

    cache_path = Path(args.output) if args.output else source_dir / ".TMP_reconcile_cache.json"

    # -- Cache-only mode -----------------------------------------------------

    if args.cache_only:
        results = load_run_cache(cache_path)

        if results is None:
            print("ERROR: No cache file found. Run without --cache-only first.")
            sys.exit(1)

        print_summary(results, archive_dir, 0)
        return

    # -- Scan source files ---------------------------------------------------

    print(f"\nScanning NAS source: {source_dir}")
    source_files = [
        p for p in source_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in {e.lower() for e in MEDIA_EXTENSIONS}
        and not p.name.startswith(".")
    ]
    print(f"  Found {len(source_files)} media files")

    if not source_files:
        print("  Nothing to analyze.")
        return

    start_time = time.time()

    # -- Build archive indexes -----------------------------------------------

    print(f"\nBuilding archive indexes from: {archive_dir}")

    archive_md5_index = {}
    if not args.no_md5:
        archive_md5_index = build_archive_md5_index(archive_dir)

    archive_date_index = build_archive_date_index(archive_dir)
    archive_dest_index = build_archive_dest_index(archive_dir)
    print(f"  Destination-path index: {len(archive_dest_index)} files indexed\n")

    # -- Extract EXIF from source files (date + camera model) ----------------

    print(f"Extracting EXIF from {len(source_files)} NAS source files...")

    # Fetch Model field alongside date fields so we can compute model suffixes
    # without a second exiftool pass.
    source_exif_raw = {}
    total_src = len(source_files)
    processed_src = 0
    chunk_index = 0

    while processed_src < total_src:
        chunk = source_files[processed_src : processed_src + EXIF_BATCH_SIZE]
        chunk_index += 1

        try:
            proc = subprocess.run(
                [
                    "exiftool", "-json", "-fast2",
                    "-DateTimeOriginal", "-CreateDate", "-MediaCreateDate",
                    "-Model",
                ] + [str(p) for p in chunk],
                capture_output=True,
                text=True,
                check=False,
            )

            if proc.returncode == 0 and proc.stdout.strip():
                for entry in json.loads(proc.stdout):
                    source_exif_raw[Path(entry.get("SourceFile", ""))] = entry

        except (json.JSONDecodeError, Exception) as err:
            print(f"  WARNING: EXIF batch {chunk_index} failed: {err}")

        processed_src += len(chunk)

        if total_src > EXIF_BATCH_SIZE:
            print(f"  EXIF extraction: {min(processed_src, total_src)}/{total_src} files...")

    # Parse dates and model suffixes from raw EXIF
    source_exif = {}
    source_model_suffixes = {}

    for file_path, entry in source_exif_raw.items():
        parsed_date = None

        for field in ("DateTimeOriginal", "CreateDate", "MediaCreateDate"):
            raw = entry.get(field)

            if raw and not raw.startswith("0000"):
                try:
                    parsed_date = datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")

                    if parsed_date.year > 1980:
                        break
                    else:
                        parsed_date = None
                except ValueError:
                    continue

        source_exif[file_path] = parsed_date
        source_model_suffixes[file_path] = extract_camera_model_suffix(entry)

    # -- Compute source MD5s -------------------------------------------------

    source_md5s = {}
    if not args.no_md5:
        print(f"\nComputing MD5 hashes for {len(source_files)} NAS source files...")
        md5_start = time.time()

        for i, file_path in enumerate(source_files):
            source_md5s[file_path] = compute_md5(file_path)

            if (i + 1) % 200 == 0:
                elapsed_md5 = time.time() - md5_start
                rate = (i + 1) / elapsed_md5
                remaining = (len(source_files) - i - 1) / rate if rate > 0 else 0
                print(f"  MD5: {i + 1}/{len(source_files)} ({remaining:.0f}s remaining)...")

        print(f"  MD5 computation complete ({time.time() - md5_start:.1f}s)")

    # -- Classify each file --------------------------------------------------

    print(f"\nClassifying {len(source_files)} files...")
    results = []

    for i, source_path in enumerate(source_files):
        md5 = source_md5s.get(source_path)
        exif_date = source_exif.get(source_path)
        model_suffix = source_model_suffixes.get(source_path, "")

        classification = classify_file(
            source_path=source_path,
            source_md5=md5,
            source_exif_date=exif_date,
            source_model_suffix=model_suffix,
            archive_md5_index=archive_md5_index,
            archive_date_index=archive_date_index,
            archive_dest_index=archive_dest_index,
            archive_dir=archive_dir,
        )
        results.append(classification)

        if args.verbose:
            cat = classification["category"]
            note = classification["note"]
            print(f"  [{cat}] {source_path.name} -- {note}")

        if (i + 1) % 500 == 0:
            print(f"  Classified {i + 1}/{len(source_files)}...")

    elapsed = time.time() - start_time

    # -- Save cache and print summary ----------------------------------------

    save_run_cache(cache_path, results, source_dir, archive_dir)
    print_summary(results, archive_dir, elapsed)

    needs_attention = sum(
        1 for r in results
        if r["category"] in {CAT_DEST_COLLISION, CAT_NO_EXIF, CAT_ERROR}
    )

    if needs_attention:
        print(f"  {needs_attention} file(s) require human review before ingestion.")

    new_count = sum(1 for r in results if r["category"] == CAT_NEW_CONTENT)

    if new_count:
        print(f"  {new_count} new file(s) ready to ingest via workflow_archive.py.")


if __name__ == "__main__":
    main()
