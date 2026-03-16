#!/usr/bin/env python3
"""
Event Folder Creator

Post-processing cleanup step that groups photos from standard month folders
into named event sub-folders for holidays and birthdays.

Run this AFTER initial organization (workflow_takeout.py or workflow_archive.py)
so that surrounding context is available before partitioning event photos.
Never moves files that are already inside a sub-folder of a month folder.

Events defined:
    J Birth / Birthday   - February 12 (± 1 day in birth year; ± 5 days all other years)
    K Birth / Birthday   - March 14    (± 1 day in birth year; ± 5 days all other years)
    Z Birth / Birthday   - September 8 (± 1 day in birth year; ± 5 days all other years)
    Fourth of July       - July 4 (exact day only)
    Halloween            - October 31 (exact day only)
    Thanksgiving         - Tue–Fri of the week containing the 4th Thursday of November
    Christmas            - December 24–25

Folder naming:
    Birth year  → "{YEAR} {INITIAL} Birth"              e.g., "2010 J Birth"
    Other years → "{YEAR} {INITIAL} Birthday - {AGE}"   e.g., "2024 J Birthday - 14"
    Holidays    → "{YEAR} {EVENT}"                      e.g., "2024 Christmas"

The year prefix makes event folders easy to identify when scanning across all
years (e.g., grepping or browsing all Christmas folders chronologically).

Cache behavior:
    Analysis cache entries (blur score, hashes, EXIF date) travel with moved
    files via ImageAnalysisCache.transfer_entry(). No re-analysis is needed
    after running this script.

Usage:
    python3 create_event_folders.py                    # Dry-run, all years
    python3 create_event_folders.py --year 2024        # Dry-run, 2024 only
    python3 create_event_folders.py --execute          # Move files, all years
    python3 create_event_folders.py --execute --year 2024 --verbose
"""

import argparse
import re
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

from analyze_photo_quality import get_analysis_cache, save_all_caches
from media_utils import get_metadata_path, MONTH_NAMES
from photo_triage import batch_extract_exif_dates

# ============================================================================
# CONFIGURATION
# ============================================================================

SCRIPT_DIR = Path(__file__).parent
PHOTO_OUTPUT_DIR = SCRIPT_DIR / "Organized_Photos"

# Children's birth dates: initial -> (birth_year, month, day)
# The birth_year drives which folder name and window size is used for a given year.
BIRTH_DATES = {
    'J': (2010, 2, 12),
    'K': (2016, 3, 14),
    'Z': (2013, 9, 8),
}

# Days on either side of the actual birth date (used only in the birth year).
# Kept tight: the day they were born, plus one day of buffer on each side for
# photos taken at the hospital before/after the birth itself.
BIRTH_WINDOW_DAYS = 1

# Days on either side of the birthday in all years after the birth year.
# Wide enough to capture birthday parties that fall on a nearby weekend.
BIRTHDAY_WINDOW_DAYS = 5

# Minimum number of photos on a single day to flag that day as a dense event
# candidate. Consecutive flagged days are merged into one span. Raise this if
# too many folders are created; lower it to catch smaller gatherings.
EVENT_CLUSTER_THRESHOLD = 35

# Photo extensions to consider when scanning month folders.
# Matches PHOTO_EXTENSIONS in media_utils, kept as a frozenset for O(1) lookup.
PHOTO_EXTENSIONS = frozenset({
    '.jpg', '.jpeg', '.png', '.gif', '.bmp',
    '.heic', '.heif', '.webp', '.tiff',
    '.JPG', '.JPEG', '.PNG', '.HEIC',
})

# Matches the YYYYMMDD_HHMMSS date pattern in filenames produced by the pipeline.
# re.search (not re.match) is intentional: lets it skip single-char prefixes
# like "P_" in "P_20240704_143723_Nicole.jpg" without listing every variant.
_FILENAME_DATE_RE = re.compile(
    r'(?:IMG_|VID_|PXL_|MVIMG_|PANO_|BURST)?'
    r'(\d{4})(\d{2})(\d{2})'      # YYYYMMDD
    r'[_\-]'                       # separator
    r'(\d{2})(\d{2})(\d{2})'      # HHMMSS
)

# Month folder names keyed by 1-based month number (derived from media_utils).
_MONTH_FOLDER = {i + 1: MONTH_NAMES[i] for i in range(12)}


# ============================================================================
# DATE COMPUTATION
# ============================================================================

def _find_fourth_thursday(year):
    """
    Return the date of the fourth Thursday in November for the given year.

    Args:
        year: Four-digit integer year

    Returns:
        date object for the fourth Thursday
    """
    # weekday() returns 0=Monday … 6=Sunday; Thursday is 3
    nov_first = date(year, 11, 1)
    days_to_first_thursday = (3 - nov_first.weekday()) % 7
    first_thursday = nov_first + timedelta(days=days_to_first_thursday)
    return first_thursday + timedelta(weeks=3)


def build_holiday_windows(year):
    """
    Build the event calendar for a given year.

    Returns a list of (folder_suffix, date_window) pairs, sorted in calendar
    order. The folder_suffix is the event portion of the destination folder
    name — the caller prepends the year.

    Args:
        year: Four-digit integer year

    Returns:
        list of (str, frozenset[date]) tuples
    """
    events = []

    # Birthdays — sorted by initial for deterministic output order.
    # In the child's actual birth year: tight ±1 day window, short folder name.
    # Every subsequent year: ±5 day window, full name with age.
    for initial, (birth_year, month, day) in sorted(BIRTH_DATES.items()):
        # No folder for years before the child existed
        if year < birth_year:
            continue

        center = date(year, month, day)

        if year == birth_year:
            # The year they were actually born — one and done
            window_days = BIRTH_WINDOW_DAYS
            event_name = f"{initial} Birth"
        else:
            window_days = BIRTHDAY_WINDOW_DAYS
            age = year - birth_year
            event_name = f"{initial} Birthday - {age}"

        window = frozenset(
            center + timedelta(days=delta)
            for delta in range(-window_days, window_days + 1)
        )
        events.append((event_name, window))

    # Fourth of July — exact day only
    events.append(("Fourth of July", frozenset({date(year, 7, 4)})))

    # Halloween — exact day only
    events.append(("Halloween", frozenset({date(year, 10, 31)})))

    # Thanksgiving — Tuesday through Friday of the week with the 4th Thursday
    fourth_thursday = _find_fourth_thursday(year)
    thanksgiving_window = frozenset({
        fourth_thursday - timedelta(days=2),   # Tuesday
        fourth_thursday - timedelta(days=1),   # Wednesday
        fourth_thursday,                        # Thursday
        fourth_thursday + timedelta(days=1),   # Friday
    })
    events.append(("Thanksgiving", thanksgiving_window))

    # Christmas — December 24–25
    events.append(("Christmas", frozenset({date(year, 12, 24), date(year, 12, 25)})))

    return events


# ============================================================================
# FILE DATE EXTRACTION
# ============================================================================

def _extract_date_from_filename(file_path):
    """
    Attempt to parse a date from the filename of a media file.

    re.search is used (not re.match) so that single-character prefixes like
    "P_" in "P_20240704_143723_Nicole.jpg" are silently skipped.

    Args:
        file_path: Path to the file

    Returns:
        date if parseable from the stem, None otherwise
    """
    match = _FILENAME_DATE_RE.search(file_path.stem)
    if not match:
        return None

    year_str, month_str, day_str = match.group(1), match.group(2), match.group(3)

    try:
        return date(int(year_str), int(month_str), int(day_str))
    except ValueError:
        return None


def _get_file_date(file_path):
    """
    Determine the date of a photo using the fastest available data source.

    Priority order (fastest to slowest):
        1. Filename pattern   — zero I/O; covers most pipeline-organized files
        2. Analysis cache     — O(1) dict lookup; populated by photo_triage or
                                prior runs of this script
        3. Single exiftool call — one subprocess per file; result is cached for
                                  future runs so this path is self-eliminating

    Args:
        file_path: Path to the photo file

    Returns:
        date if determinable, None otherwise
    """
    # 1. Filename pattern (covers the vast majority of organized files)
    filename_date = _extract_date_from_filename(file_path)
    if filename_date is not None:
        return filename_date

    # 2. Per-directory analysis cache (requires prior photo_triage or analyze run)
    cache = get_analysis_cache(file_path.parent)
    cached_ts = cache.get_exif_date(file_path)

    if cached_ts is not None:
        # Sentinel value: previously checked, confirmed no EXIF date in file
        if cached_ts == 0:
            return None
        from datetime import datetime as _dt
        return _dt.fromtimestamp(cached_ts).date()

    # 3. Single-file exiftool fallback (also populates the cache for next time)
    from photo_triage import get_exif_date as _triage_get_exif
    exif_dt = _triage_get_exif(file_path)

    if exif_dt is not None:
        return exif_dt.date()

    return None


# ============================================================================
# CACHE MAINTENANCE
# ============================================================================

def _transfer_cache_entry(old_path, new_path):
    """
    Move an analysis cache entry from old_path to new_path.

    Called after shutil.move() so cached analysis data (blur score, hashes,
    EXIF date) travels with the file. Within the same filesystem volume,
    shutil.move() is an atomic rename that preserves mtime and size, so
    the cached mtime/size values remain valid at the new path.

    Delegates to ImageAnalysisCache.transfer_entry() to keep dict
    manipulation inside the class.

    No-op if old_path has no cache entry.

    Args:
        old_path: Absolute pre-move file path
        new_path: Absolute post-move file path
    """
    source_cache = get_analysis_cache(old_path.parent)
    dest_cache = get_analysis_cache(new_path.parent)
    source_cache.transfer_entry(old_path, new_path, dest_cache)


def _move_file(file_path, dest_dir):
    """
    Move a photo file (and its sidecar JSON if present) into dest_dir.

    Handles filename collision resolution, cache-entry transfer, and
    co-movement of any `.supplemental-metadata[...].json` sidecar file that
    lives alongside the photo. The sidecar is renamed to match the (possibly
    collision-adjusted) photo filename so the pair stays linked.

    Args:
        file_path: Source Path of the photo file
        dest_dir:  Destination directory Path (must already exist)

    Returns:
        Path: the final destination path of the photo file
    """
    new_path = dest_dir / file_path.name

    # Resolve name collisions — rare, but two month folders could contribute
    # identically-named files to the same event window.
    if new_path.exists():
        stem = file_path.stem
        suffix = file_path.suffix
        counter = 1

        while new_path.exists():
            new_path = dest_dir / f"{stem}_{counter}{suffix}"
            counter += 1

    shutil.move(str(file_path), new_path)
    _transfer_cache_entry(file_path, new_path)

    # Co-move sidecar JSON (.supplemental-metadata[...].json) if one exists.
    # The sidecar keeps the same suffix structure, just on the new base name.
    sidecar = get_metadata_path(file_path)

    if sidecar is not None and sidecar.exists():
        # Preserve the full sidecar suffix (e.g. ".supplemental-me.json")
        # on whatever filename the photo ended up with after collision resolution.
        sidecar_suffix = sidecar.name[len(file_path.name):]
        new_sidecar = dest_dir / (new_path.name + sidecar_suffix)
        shutil.move(str(sidecar), new_sidecar)

    return new_path


# ============================================================================
# SCANNING
# ============================================================================

def _collect_direct_photos(month_folder):
    """
    Return all direct-child photo files in a month folder.

    Excludes sub-directories entirely — files already inside any event or
    project sub-folder are never candidates for re-sorting.

    Args:
        month_folder: Path to a month folder (e.g., "07 July")

    Returns:
        Sorted list of Path objects
    """
    files = [
        item for item in month_folder.iterdir()
        if item.is_file() and item.suffix.lower() in {ext.lower() for ext in PHOTO_EXTENSIONS}
    ]
    return sorted(files)


def _scan_event_candidates(month_folder, date_window):
    """
    Find direct-child photos in month_folder whose date falls in date_window.

    Batch-populates the analysis cache for files that cannot be dated from
    their filename before the per-file lookup loop, avoiding per-file exiftool
    process spawns for those files.

    Args:
        month_folder: Path to the source month folder
        date_window:  frozenset of date objects defining the event period

    Returns:
        List of (Path, date) tuples for matching files
    """
    all_files = _collect_direct_photos(month_folder)

    if not all_files:
        return []

    # Batch EXIF extraction for files with no parseable filename date.
    # Already-cached files are skipped inside batch_extract_exif_dates.
    needs_exif = [f for f in all_files if _extract_date_from_filename(f) is None]

    if needs_exif:
        batch_extract_exif_dates(needs_exif, show_progress=False)

    # Collect matches using the fast lookup chain
    candidates = []

    for file_path in all_files:
        file_date = _get_file_date(file_path)

        if file_date is not None and file_date in date_window:
            candidates.append((file_path, file_date))

    return candidates


def _detect_photo_clusters(year_dir, threshold, exclude_paths=None):
    """
    Find runs of consecutive days with a combined photo count >= threshold.

    Intended to surface untagged events (vacations, multi-day trips, parties)
    that don't correspond to a named holiday. Run this AFTER the holiday loop
    so that already-claimed files are excluded — either physically (execute
    mode, files already moved) or logically (dry-run, via exclude_paths).

    Algorithm:
        1. Collect all direct-child photos from every month folder in the year,
           minus any paths in exclude_paths.
        2. Batch-extract EXIF dates for files not datable from filename.
        3. Group files by date.
        4. A day is "dense" if it has >= threshold photos on its own.
        5. Consecutive dense days are merged into a single span; gaps (even one
           day with fewer photos) break the span.

    This means threshold applies per-day, not to the span total. A ten-day
    vacation where you shoot 25 photos each day produces one span; two busy
    single days separated by a quiet day produce two separate single-day spans.

    Folder name format:
        Single day  → "MM-DD Event"        e.g., "07-04 Event"
        Multi-day   → "MM-DD–MM-DD Event"  e.g., "07-14–07-25 Event"

    Args:
        year_dir:      Path to the year directory
        threshold:     Minimum photos on a single day to qualify (0 disables)
        exclude_paths: set of Path objects already claimed by holiday events;
                       used in dry-run mode to avoid phantom overlap

    Returns:
        List of (folder_label, [Path, ...]) tuples, sorted by start date
    """
    if threshold <= 0:
        return []

    from collections import defaultdict

    exclude_paths = exclude_paths or set()

    # Collect all eligible direct-child photos across every month folder
    all_photos = []

    for month_folder_name in MONTH_NAMES:
        month_folder = year_dir / month_folder_name
        if not month_folder.is_dir():
            continue
        all_photos.extend(
            f for f in _collect_direct_photos(month_folder)
            if f not in exclude_paths
        )

    if not all_photos:
        return []

    # Batch EXIF extraction for files not datable via filename — one call
    # for the entire year rather than one call per month folder.
    needs_exif = [f for f in all_photos if _extract_date_from_filename(f) is None]
    if needs_exif:
        batch_extract_exif_dates(needs_exif, show_progress=False)

    # Group files by date (undated files are discarded — can't cluster them)
    date_to_files = defaultdict(list)
    for file_path in all_photos:
        file_date = _get_file_date(file_path)
        if file_date is not None:
            date_to_files[file_date].append(file_path)

    if not date_to_files:
        return []

    # Keep only days that individually meet the per-day threshold
    dense_days = sorted(d for d, files in date_to_files.items() if len(files) >= threshold)

    if not dense_days:
        return []

    # Merge adjacent dense days (no gap allowed) into spans
    current_span = [dense_days[0]]
    all_spans = []

    for i in range(1, len(dense_days)):
        prev = dense_days[i - 1]
        curr = dense_days[i]

        if (curr - prev).days == 1:
            # Consecutive dense days — extend current span
            current_span.append(curr)
        else:
            # Gap (quiet day or multiple days between) — close and open
            all_spans.append(current_span)
            current_span = [curr]

    all_spans.append(current_span)

    # Build labeled results — no secondary filter needed; every span was
    # assembled from days that individually met the per-day threshold.
    results = []

    for span in all_spans:
        span_files = []
        for d in span:
            span_files.extend(date_to_files[d])

        if len(span) == 1:
            label = span[0].strftime('%m-%d')
        else:
            label = f"{span[0].strftime('%m-%d')}–{span[-1].strftime('%m-%d')}"

        results.append((f"{label} Event", span_files))

    return results


# ============================================================================
# YEAR PROCESSING
# ============================================================================

def process_year(year_dir, dry_run=True, verbose=False, event_threshold=EVENT_CLUSTER_THRESHOLD):
    """
    Identify and optionally create event folders for one year directory.

    Dry-run mode (default): prints a report of what would be moved without
    touching any files or directories.

    Execute mode (--execute): creates event sub-folders, moves matching
    photos, and updates analysis caches so no re-analysis is needed afterward.

    Important: only direct children of "MM MonthName" folders are candidates.
    Any file already inside a sub-folder (event, project, etc.) is untouched.

    Holiday/birthday events are processed first. Cluster detection runs
    afterward on whatever remains in the month folders, so there is no overlap
    between the two passes.

    Args:
        year_dir:        Path to the year directory (e.g., Organized_Photos/2024/)
        dry_run:         If True, report only — do not create folders or move files
        verbose:         If True, list individual filenames in output
        event_threshold: Min photos in a consecutive-day span to create an Event
                         folder. Pass 0 to disable cluster detection entirely.

    Returns:
        dict with keys 'events_found', 'total_candidates', 'total_moved',
        or None if year_dir.name is not a four-digit year string
    """
    try:
        year = int(year_dir.name)
    except ValueError:
        return None

    events = build_holiday_windows(year)
    print(f"\n  {year}:")

    summary = {
        'events_found': 0,
        'total_candidates': 0,
        'total_moved': 0,
    }

    # Track every file claimed by a holiday/birthday window. In dry-run mode
    # this set is passed to the cluster detector so it doesn't double-count
    # files that would have already been moved in execute mode.
    claimed_paths = set()

    for event_name, date_window in events:
        # Determine which month folder(s) this event window touches.
        # first_month_folder tracks the earliest month that has candidates —
        # the event folder is created inside it so photos stay within their
        # original containing folder rather than floating up to the year level.
        event_months = sorted({d.month for d in date_window})
        first_month_folder = None
        candidates = []

        for month_num in event_months:
            month_folder_name = _MONTH_FOLDER.get(month_num)
            if month_folder_name is None:
                continue

            month_folder = year_dir / month_folder_name
            if not month_folder.is_dir():
                continue

            matches = _scan_event_candidates(month_folder, date_window)

            if matches and first_month_folder is None:
                first_month_folder = month_folder

            candidates.extend(matches)

        if not candidates:
            continue

        for file_path, _ in candidates:
            claimed_paths.add(file_path)

        summary['events_found'] += 1
        summary['total_candidates'] += len(candidates)

        folder_name = f"{year} {event_name}"
        dest_dir = first_month_folder / folder_name

        print(f"    {folder_name}: {len(candidates)} photo(s)")

        if verbose:
            for file_path, file_date in sorted(candidates, key=lambda x: x[1]):
                print(f"      {file_date}  {file_path.name}")

        if dry_run:
            continue

        # Execute: create folder and move matching files
        dest_dir.mkdir(exist_ok=True)

        for file_path, _ in candidates:
            _move_file(file_path, dest_dir)
            summary['total_moved'] += 1

    # -------------------------------------------------------------------------
    # Cluster detection — runs on whatever is left in the month folders after
    # holiday/birthday files have been claimed (or moved, in execute mode).
    # -------------------------------------------------------------------------
    clusters = _detect_photo_clusters(
        year_dir,
        threshold=event_threshold,
        exclude_paths=claimed_paths,
    )

    if clusters:
        print(f"    --- potential events (>= {event_threshold} photos/day) ---")

    for event_name, cluster_files in clusters:
        # Cluster files are in date order (dense_days is sorted); the first
        # file's parent is the earliest month folder — event folder goes there.
        folder_name = event_name
        dest_dir = cluster_files[0].parent / folder_name

        summary['events_found'] += 1
        summary['total_candidates'] += len(cluster_files)

        print(f"    {folder_name}: {len(cluster_files)} photo(s)")

        if verbose:
            for file_path in sorted(cluster_files, key=lambda f: _get_file_date(f) or date.min):
                print(f"      {_get_file_date(file_path)}  {file_path.name}")

        if dry_run:
            continue

        dest_dir.mkdir(exist_ok=True)

        for file_path in cluster_files:
            _move_file(file_path, dest_dir)
            summary['total_moved'] += 1

    return summary


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Parse arguments and drive per-year processing."""
    parser = argparse.ArgumentParser(
        description="Group holiday and birthday photos into named event folders.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python3 create_event_folders.py                    dry-run across all years
  python3 create_event_folders.py --year 2024        dry-run for 2024 only
  python3 create_event_folders.py --execute          move files for all years
  python3 create_event_folders.py --execute --year 2024 --verbose
        """
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help="Actually move files. Default behavior is dry-run (preview only)."
    )
    parser.add_argument(
        '--year',
        type=int,
        metavar='YYYY',
        help="Process a single year only. Default: all years."
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help="List each individual file being moved."
    )
    parser.add_argument(
        '--event-threshold',
        type=int,
        default=EVENT_CLUSTER_THRESHOLD,
        metavar='N',
        help=(
            f"Min photos on a single day to flag it as an event candidate "
            f"(default: {EVENT_CLUSTER_THRESHOLD}; consecutive flagged days merge into one span; "
            f"0 disables cluster detection)."
        )
    )
    parser.add_argument(
        '--photos-dir',
        type=Path,
        default=PHOTO_OUTPUT_DIR,
        metavar='DIR',
        help="Override the photos directory (default: Organized_Photos/)"
    )
    args = parser.parse_args()

    dry_run = not args.execute
    photos_dir = Path(args.photos_dir)

    if not photos_dir.exists():
        print(f"ERROR: Photos directory not found: {photos_dir}")
        sys.exit(1)

    print()
    print('=' * 70)

    if dry_run:
        print("Event Folder Creator  —  DRY RUN (no files will be moved)")
        print("Re-run with --execute to actually move files.")
    else:
        print("Event Folder Creator  —  EXECUTING MOVES")

    print('=' * 70)
    print(f"  Photos: {photos_dir}")

    # Collect year directories to process
    if args.year:
        target = photos_dir / str(args.year)

        if not target.exists():
            print(f"\nERROR: Year directory not found: {target}")
            sys.exit(1)

        year_dirs = [target]
    else:
        year_dirs = sorted(
            d for d in photos_dir.iterdir()
            if d.is_dir() and d.name.isdigit() and len(d.name) == 4
        )

    print(f"  Years:  {', '.join(d.name for d in year_dirs)}")

    # Process each year, accumulating grand totals
    grand_candidates = 0
    grand_moved = 0
    years_with_events = 0

    for year_dir in year_dirs:
        result = process_year(
            year_dir,
            dry_run=dry_run,
            verbose=args.verbose,
            event_threshold=args.event_threshold,
        )

        if result is None:
            continue

        grand_candidates += result['total_candidates']
        grand_moved += result['total_moved']

        if result['events_found'] > 0:
            years_with_events += 1

    # Flush all dirty cache instances to disk in one pass after all moves.
    # No-op if nothing was moved (dry_run or no matches found).
    if not dry_run:
        save_all_caches()

    print()
    print('-' * 70)
    print("Summary:")
    print(f"  Years with event photos: {years_with_events}")
    print(f"  Total photos identified: {grand_candidates}")

    if dry_run:
        print("  (Run with --execute to move these files.)")
    else:
        print(f"  Total photos moved:      {grand_moved}")
        print("  Analysis caches updated.")

    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted. No changes made.")
        sys.exit(1)
