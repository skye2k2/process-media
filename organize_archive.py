#!/usr/bin/env python3
"""
Archive Media Organizer

Organizes raw video/photo files (without JSON metadata) into the standard
year/month folder structure. Designed for NAS archives and other media
that doesn't have accompanying Google Takeout JSON files.

Features:
- Extracts dates from filenames (VID_YYYYMMDD_HHMMSS, IMG_YYYYMMDD_HHMMSS, etc.)
- Falls back to EXIF metadata or file modification time
- Uses date+size matching to detect duplicates across naming conventions
- Preserves project folders (moves entire folder as a unit)
- Skips .MTS/.M2TS files (handled by camcorder workflow)

Usage:
    python3 organize_archive.py [input_dir]
    python3 organize_archive.py --dry-run [input_dir]
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from build_file_index import build_file_index
from duplicate_detector import DuplicateDetector, MatchConfidence
from media_utils import PHOTO_EXTENSIONS, VIDEO_EXTENSIONS, MONTH_NAMES

# ============================================================================
# CONFIGURATION
# ============================================================================

SCRIPT_DIR = Path(__file__).parent
DEFAULT_INPUT_DIR = SCRIPT_DIR / "TO_PROCESS"
PHOTO_OUTPUT_DIR = SCRIPT_DIR / "Organized_Photos"
VIDEO_OUTPUT_DIR = SCRIPT_DIR / "Organized_Videos"

# Extensions to skip (handled by camcorder workflow)
SKIP_EXTENSIONS = {'.mts', '.m2ts'}

# All media extensions we process
MEDIA_EXTENSIONS = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS


# ============================================================================
# DATE EXTRACTION
# ============================================================================

def extract_date_from_filename(filename):
    """
    Extract datetime from various filename formats.

    Supported formats:
    - VID_20210526_162641582.mp4 -> 2021-05-26 16:26:41
    - IMG_20210526_162641.jpg -> 2021-05-26 16:26:41
    - PXL_20210526_162641582.mp4 -> 2021-05-26 16:26:41
    - 20210526_162641.jpg -> 2021-05-26 16:26:41

    Args:
        filename: The filename to parse

    Returns:
        datetime or None if no date pattern found
    """
    # Pattern: optional prefix, then YYYYMMDD_HHMMSS
    match = re.search(r'(?:VID_|IMG_|PXL_)?(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})', filename)

    if match:
        year, month, day, hour, minute, second = match.groups()

        try:
            return datetime(int(year), int(month), int(day),
                           int(hour), int(minute), int(second))
        except ValueError:
            return None

    return None


def get_date_from_exif(file_path):
    """
    Extract creation date from file using exiftool.

    Args:
        file_path: Path to the media file

    Returns:
        datetime or None
    """
    try:
        result = subprocess.run(
            [
                'exiftool', '-s', '-s', '-s',
                '-DateTimeOriginal',
                '-CreateDate',
                '-MediaCreateDate',
                str(file_path)
            ],
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode != 0 or not result.stdout.strip():
            return None

        for line in result.stdout.strip().split('\n'):
            date_str = line.strip()

            if not date_str:
                continue

            try:
                return datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
            except ValueError:
                continue

        return None

    except Exception:
        return None


def get_creation_date(file_path):
    """
    Get creation date from file, trying multiple methods.

    Priority:
    1. Filename patterns (fastest, most common for phone videos)
    2. EXIF metadata
    3. File modification time (last resort)

    Args:
        file_path: Path to the media file

    Returns:
        tuple: (datetime, source_string)
    """
    # Try filename first
    date = extract_date_from_filename(file_path.name)

    if date:
        return date, "filename"

    # Try EXIF
    date = get_date_from_exif(file_path)

    if date:
        return date, "exif"

    # Fallback to file modification time
    try:
        mtime = os.path.getmtime(file_path)
        return datetime.fromtimestamp(mtime), "file_mtime"
    except Exception:
        return None, None


# ============================================================================
# DUPLICATE DETECTION
# ============================================================================

def find_existing_by_date(creation_date, file_size, file_index):
    """
    Find existing files that match the creation date.

    Handles multiple naming conventions by matching on date pattern.
    Size tolerance of 5% to account for metadata differences.

    Args:
        creation_date: datetime of the source file
        file_size: Size of source file in bytes
        file_index: Index from build_file_index

    Returns:
        Path if match found, None otherwise
    """
    if not creation_date:
        return None

    # Build date pattern: YYYYMMDD_HHMMSS
    date_pattern = creation_date.strftime("%Y%m%d_%H%M%S")

    # Size tolerance
    min_size = file_size * 0.95
    max_size = file_size * 1.05

    for (base_name, ext, is_edited), paths in file_index.items():
        # Skip edited versions
        if is_edited:
            continue

        # Check if filename contains the date pattern
        if date_pattern not in base_name:
            continue

        existing_path = paths[0]

        if not existing_path.exists():
            continue

        # Check size similarity
        existing_size = existing_path.stat().st_size

        if min_size <= existing_size <= max_size:
            return existing_path

    return None


# ============================================================================
# FILE ORGANIZATION
# ============================================================================

def get_destination_folder(creation_date, is_video):
    """
    Determine destination folder based on creation date and file type.

    Args:
        creation_date: datetime object
        is_video: True if video file, False if photo

    Returns:
        Path: Destination directory
    """
    base_dir = VIDEO_OUTPUT_DIR if is_video else PHOTO_OUTPUT_DIR
    year = creation_date.year
    month_folder = MONTH_NAMES[creation_date.month - 1]

    return base_dir / str(year) / month_folder


def is_video_file(file_path):
    """Check if file is a video based on extension."""
    return file_path.suffix.lower() in {e.lower() for e in VIDEO_EXTENSIONS}


def move_file(file_path, dest_folder, dry_run=False):
    """
    Move file to destination folder.

    Args:
        file_path: Source file path
        dest_folder: Destination directory
        dry_run: If True, don't actually move

    Returns:
        Path: Final destination path, or None if failed
    """
    filename = file_path.name
    dest_path = dest_folder / filename

    if dry_run:
        print(f"    [DRY RUN] Would move to: {dest_path}")
        return dest_path

    try:
        dest_folder.mkdir(parents=True, exist_ok=True)

        # Handle collision
        if dest_path.exists():
            stem = file_path.stem
            ext = file_path.suffix
            counter = 1

            while dest_path.exists():
                new_name = f"{stem}_{counter}{ext}"
                dest_path = dest_folder / new_name
                counter += 1

            print(f"    Collision resolved: {filename} -> {dest_path.name}")

        shutil.move(str(file_path), str(dest_path))
        return dest_path

    except Exception as e:
        print(f"    ERROR: Could not move file: {e}")
        return None


# ============================================================================
# PROJECT FOLDER HANDLING
# ============================================================================

def is_project_folder(folder_path, input_dir):
    """
    Determine if a folder is a project folder (should be moved as a unit).

    A project folder is a subdirectory of the input that:
    - Contains media files
    - Has a descriptive name (not just a year or date)

    Args:
        folder_path: Path to check
        input_dir: The root input directory

    Returns:
        bool
    """
    if folder_path == input_dir:
        return False

    folder_name = folder_path.name

    # Skip if it's just a year folder
    if re.match(r'^\d{4}$', folder_name):
        return False

    # Check if it contains media files
    has_media = False

    for ext in MEDIA_EXTENSIONS:
        if list(folder_path.glob(f"*{ext}")):
            has_media = True
            break

    return has_media


def get_folder_date_range(folder_path):
    """
    Determine the date range of files in a folder.

    Args:
        folder_path: Path to the folder

    Returns:
        tuple: (earliest_date, most_common_month) or (None, None)
    """
    dates = []

    for file_path in folder_path.rglob('*'):
        if not file_path.is_file():
            continue

        ext = file_path.suffix.lower()

        if ext in SKIP_EXTENSIONS:
            continue

        if ext not in {e.lower() for e in MEDIA_EXTENSIONS}:
            continue

        date, _ = get_creation_date(file_path)

        if date:
            dates.append(date)

    if not dates:
        return None, None

    # Find earliest date and most common month
    earliest = min(dates)

    # Count months to find most common
    month_counts = {}

    for d in dates:
        key = (d.year, d.month)
        month_counts[key] = month_counts.get(key, 0) + 1

    most_common = max(month_counts, key=month_counts.get)

    return earliest, most_common


def move_project_folder(folder_path, file_index, dry_run=False):
    """
    Move an entire project folder to the organized structure.

    Args:
        folder_path: Path to the project folder
        file_index: For duplicate checking
        dry_run: If True, don't actually move

    Returns:
        tuple: (result, file_count)
    """
    folder_name = folder_path.name

    # Get date range for folder
    earliest, most_common = get_folder_date_range(folder_path)

    if not earliest:
        print(f"  WARNING: No dates found in project folder: {folder_name}")
        return 'skipped', 0

    year, month = most_common
    month_folder = MONTH_NAMES[month - 1]

    # Determine if it's primarily video or photo content
    video_count = sum(1 for f in folder_path.rglob('*')
                      if f.is_file() and f.suffix.lower() in {e.lower() for e in VIDEO_EXTENSIONS})
    photo_count = sum(1 for f in folder_path.rglob('*')
                      if f.is_file() and f.suffix.lower() in {e.lower() for e in PHOTO_EXTENSIONS})

    base_dir = VIDEO_OUTPUT_DIR if video_count >= photo_count else PHOTO_OUTPUT_DIR
    dest_parent = base_dir / str(year)
    dest_path = dest_parent / f"{month:02d} {folder_name}"

    # Check if destination already exists
    if dest_path.exists():
        print(f"  SKIPPED: Project folder already exists -> {dest_path}")
        return 'skipped', 0

    file_count = video_count + photo_count

    if dry_run:
        print(f"  [DRY RUN] Would move project folder: {folder_name}")
        print(f"            -> {dest_path}")
        print(f"            ({file_count} files)")
        return 'moved', file_count

    try:
        dest_parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(folder_path), str(dest_path))
        print(f"  Moved project: {folder_name} -> {dest_path.name}")
        return 'moved', file_count
    except Exception as e:
        print(f"  ERROR moving project folder: {e}")
        return 'failed', 0


# ============================================================================
# MAIN PROCESSING
# ============================================================================

def process_file(file_path, detector, dry_run=False):
    """
    Process a single media file using smart duplicate detection.

    Uses the DuplicateDetector for multi-signal matching:
    - Filename date pattern
    - Video duration
    - File size
    - Quality analysis for size mismatches

    Args:
        file_path: Path to the media file
        detector: DuplicateDetector instance
        dry_run: If True, don't make changes

    Returns:
        tuple: (result_code, action_taken)
            result_code: 'moved', 'skipped', 'replaced', or 'failed'
            action_taken: Description of what happened
    """
    print(f"\n  Processing: {file_path.name}")

    # Get creation date (required for organizing into year/month folders)
    creation_date, date_source = get_creation_date(file_path)

    if not creation_date:
        print(f"    WARNING: Could not determine date, skipping")
        return 'skipped', 'no date'

    # Use smart duplicate detection
    dup_result = detector.find_duplicate(file_path)

    if dup_result.is_duplicate:
        if dup_result.confidence == MatchConfidence.EXACT or dup_result.confidence == MatchConfidence.HIGH:
            # Exact or high-confidence match - skip
            print(f"    SKIPPED: {dup_result.reason}")
            print(f"             -> {dup_result.existing_path.name}")
            return 'skipped', 'exact duplicate'

        elif dup_result.confidence == MatchConfidence.MEDIUM:
            # Same content, different encoding - need to decide which to keep
            if dup_result.prefer_existing:
                print(f"    SKIPPED: {dup_result.reason}")
                print(f"             -> {dup_result.existing_path.name}")
                return 'skipped', 'existing preferred'
            else:
                # Source is better - replace existing with source
                print(f"    REPLACE: {dup_result.reason}")

                if dup_result.source_quality and dup_result.existing_quality:
                    sq = dup_result.source_quality
                    eq = dup_result.existing_quality
                    print(f"             Source: {sq.file_size/1_000_000:.1f}MB @ {sq.bitrate/1_000_000:.1f}Mbps")
                    print(f"             Existing: {eq.file_size/1_000_000:.1f}MB @ {eq.bitrate/1_000_000:.1f}Mbps")

                if dry_run:
                    print(f"    [DRY RUN] Would replace {dup_result.existing_path.name}")
                    return 'replaced', 'source is better quality/size'

                # Move source to same location as existing, preserving the existing filename
                # (which may have a personName suffix like _Nicole or _Clif)
                existing_path = dup_result.existing_path
                dest_folder = existing_path.parent

                # Preserve the existing file's name (including any personName suffix)
                # by keeping the stem and updating only the extension if needed
                existing_name = existing_path.name

                try:
                    # Delete the bloated existing file
                    existing_path.unlink()
                    print(f"    Deleted bloated: {existing_name}")

                    # Move source to destination, preserving the existing filename
                    dest_path = dest_folder / existing_name
                    shutil.move(str(file_path), str(dest_path))
                    print(f"    Replaced with: {dest_path.name}")
                    return 'replaced', 'source is better quality/size'

                except Exception as e:
                    print(f"    ERROR: Could not replace: {e}")
                    return 'failed', str(e)

    # No duplicate found - move to organized location
    is_video = is_video_file(file_path)
    dest_folder = get_destination_folder(creation_date, is_video)

    # Move file
    result = move_file(file_path, dest_folder, dry_run)

    if result:
        print(f"    Moved to: {dest_folder.name}/")
        return 'moved', 'new file'
    else:
        return 'failed', 'move failed'


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Organize archive media files into year/month folders",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Process files from TO_PROCESS/
  %(prog)s /path/to/archive   # Process files from custom directory
  %(prog)s --dry-run          # Preview without making changes
        """
    )

    parser.add_argument(
        'input_dir',
        nargs='?',
        default=str(DEFAULT_INPUT_DIR),
        help=f"Directory containing media files (default: {DEFAULT_INPUT_DIR})"
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help="Show what would be done without making changes"
    )

    args = parser.parse_args()
    input_dir = Path(args.input_dir)

    print("\n" + "=" * 70)
    print("Archive Media Organizer (Smart Duplicate Detection)")
    print("=" * 70)

    if args.dry_run:
        print("\n*** DRY RUN MODE - No changes will be made ***")

    # Validate input
    if not input_dir.exists():
        print(f"\nERROR: Input directory not found: {input_dir}")
        return 1

    # Check if duration cache exists (first run will be slower as ffprobe analyzes each video)
    cache_file = SCRIPT_DIR / ".duration_cache.json"
    cache_exists = cache_file.exists()

    # Initialize smart duplicate detector
    print("\n" + "-" * 70)
    print("Initializing duplicate detector...")

    import time
    init_start = time.time()

    detector = DuplicateDetector(
        photo_dir=PHOTO_OUTPUT_DIR,
        video_dir=VIDEO_OUTPUT_DIR,
        duration_tolerance=1.0,  # 1 second tolerance for duration matching
        size_tolerance=0.20      # 20% tolerance for "similar" size
    )

    init_time = time.time() - init_start

    if cache_exists:
        print(f"  Index built in {init_time:.1f}s (using cached video durations)")
    else:
        print(f"  Index built in {init_time:.1f}s")
        print(f"  NOTE: First run will be slower as video durations are analyzed via ffprobe")

    # Also build simple file index for project folder processing
    file_index = detector.file_index

    # Find project folders and loose files
    print("\n" + "-" * 70)
    print("Scanning input directory...")

    project_folders = []
    loose_files = []

    for item in input_dir.iterdir():
        if item.name.startswith('.'):
            continue

        if item.is_dir():
            if is_project_folder(item, input_dir):
                project_folders.append(item)
            else:
                # Recurse into non-project directories
                for file_path in item.rglob('*'):
                    if file_path.is_file():
                        ext = file_path.suffix.lower()

                        if ext in SKIP_EXTENSIONS:
                            continue

                        if ext in {e.lower() for e in MEDIA_EXTENSIONS}:
                            loose_files.append(file_path)
        else:
            ext = item.suffix.lower()

            if ext in SKIP_EXTENSIONS:
                continue

            if ext in {e.lower() for e in MEDIA_EXTENSIONS}:
                loose_files.append(item)

    print(f"\nFound {len(project_folders)} project folders")
    print(f"Found {len(loose_files)} loose media files")

    # Process project folders first
    project_moved = 0
    project_skipped = 0
    project_files_moved = 0

    if project_folders:
        print("\n" + "-" * 70)
        print("Processing project folders...")

        for folder in sorted(project_folders, key=lambda p: p.name):
            result, file_count = move_project_folder(folder, file_index, args.dry_run)

            if result == 'moved':
                project_moved += 1
                project_files_moved += file_count
            else:
                project_skipped += 1

    # Process loose files
    moved_count = 0
    replaced_count = 0
    skipped_count = 0
    failed_count = 0
    space_saved = 0  # Track bytes saved from replacing bloated files

    if loose_files:
        print("\n" + "-" * 70)
        print("Processing loose files...")

        for file_path in sorted(loose_files, key=lambda p: p.name):
            result, action = process_file(file_path, detector, args.dry_run)

            if result == 'moved':
                moved_count += 1
            elif result == 'replaced':
                replaced_count += 1
            elif result == 'skipped':
                skipped_count += 1
            else:
                failed_count += 1

    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"\n  Project folders moved:   {project_moved} ({project_files_moved} files)")
    print(f"  Project folders skipped: {project_skipped}")
    print(f"\n  Loose files moved:       {moved_count}")
    print(f"  Loose files replaced:    {replaced_count} (bloated versions removed)")
    print(f"  Loose files skipped:     {skipped_count}")
    print(f"  Loose files failed:      {failed_count}")

    total_moved = project_files_moved + moved_count + replaced_count

    if args.dry_run and total_moved > 0:
        print(f"\n  Run without --dry-run to process {total_moved} files")

    # Save the duration cache for faster future runs
    detector.save_duration_cache()

    print("")
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
