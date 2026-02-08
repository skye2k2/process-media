#!/usr/bin/env python3
"""
NAS Archive Verification Script

Compares files in a NAS archive directory against organized directories to find
files that would be lost if the archive were deleted.

Uses date-based matching from filenames to detect duplicates regardless of
naming conventions (VID_YYYYMMDD_HHMMSS vs YYYYMMDD_HHMMSS_PersonName).

Usage:
    python3 check_nas_archive.py /Volumes/home-movies
    python3 check_nas_archive.py /Volumes/home-movies --verbose
    python3 check_nas_archive.py /Volumes/home-movies --output missing.txt
"""

import argparse
import re
import sys
from pathlib import Path

from build_file_index import build_file_index
from media_utils import PHOTO_EXTENSIONS, VIDEO_EXTENSIONS

# Extensions to skip (handled separately by camcorder workflow)
SKIP_EXTENSIONS = {'.mts', '.m2ts', '.MTS', '.M2TS'}

# All media extensions to check
MEDIA_EXTENSIONS = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS


def extract_date_from_filename(filename):
    """
    Extract date portion from various filename formats.

    Supported formats:
    - VID_20210526_162641582.mp4 -> 20210526_162641
    - IMG_20210526_162641582.jpg -> 20210526_162641
    - 20210526_162641.jpg -> 20210526_162641
    - 20210526_162641_Nicole.mp4 -> 20210526_162641
    - PXL_20210526_162641582.mp4 -> 20210526_162641

    Args:
        filename: The filename to parse

    Returns:
        str: Date pattern (YYYYMMDD_HHMMSS) or None if not found
    """
    # Pattern: optional prefix, then YYYYMMDD_HHMMSS, then optional milliseconds
    # Matches: VID_20210526_162641582, IMG_20210526_162641, 20210526_162641, PXL_...
    match = re.search(r'(?:VID_|IMG_|PXL_)?(\d{8}_\d{6})', filename)

    if match:
        return match.group(1)

    return None


def scan_archive_files(archive_dir):
    """
    Scan archive directory for media files, excluding MTS files.

    Args:
        archive_dir: Path to the archive directory

    Returns:
        list: List of (path, date_pattern) tuples
    """
    files = []

    for path in archive_dir.rglob('*'):
        if not path.is_file():
            continue

        ext = path.suffix.lower()

        # Skip MTS files (handled separately)
        if ext in {'.mts', '.m2ts'}:
            continue

        # Only process media files
        if ext not in {e.lower() for e in MEDIA_EXTENSIONS}:
            continue

        date_pattern = extract_date_from_filename(path.name)
        files.append((path, date_pattern))

    return files


def check_file_exists(date_pattern, file_index, original_name):
    """
    Check if a file with matching date exists in the organized directories.

    Args:
        date_pattern: YYYYMMDD_HHMMSS format string
        file_index: Index from build_file_index
        original_name: Original filename for fallback matching

    Returns:
        Path if found, None otherwise
    """
    if not date_pattern:
        # No date in filename - try exact name match
        stem = Path(original_name).stem
        ext = Path(original_name).suffix.lower()

        for key in [(stem, ext, False), (stem, ext, True)]:
            if key in file_index:
                return file_index[key][0]

        return None

    # Search for any file with matching date pattern
    for (base_name, ext, is_edited), paths in file_index.items():
        # Check if this file contains the same date
        if date_pattern in base_name:
            return paths[0]

    return None


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Check NAS archive for files missing from organized directories",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s /Volumes/home-movies
  %(prog)s /Volumes/home-movies --verbose
  %(prog)s /Volumes/home-movies --output missing_files.txt
        """
    )

    parser.add_argument(
        'archive_dir',
        help="Path to NAS archive directory to check"
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help="Show all files, not just missing ones"
    )

    parser.add_argument(
        '--output', '-o',
        help="Write missing file paths to this file"
    )

    parser.add_argument(
        '--organized-photos',
        default='Organized_Photos',
        help="Path to organized photos directory"
    )

    parser.add_argument(
        '--organized-videos',
        default='Organized_Videos',
        help="Path to organized videos directory"
    )

    args = parser.parse_args()
    archive_dir = Path(args.archive_dir)

    if not archive_dir.exists():
        print(f"ERROR: Archive directory not found: {archive_dir}")
        return 1

    print("=" * 70)
    print("NAS Archive Verification")
    print("=" * 70)
    print(f"\nArchive: {archive_dir}")
    print(f"Checking against: {args.organized_photos}, {args.organized_videos}")
    print("\nNote: .MTS/.M2TS files are skipped (use camcorder workflow)")

    # Build file index from organized directories
    print("\n" + "-" * 70)
    script_dir = Path(__file__).parent
    photo_dir = script_dir / args.organized_photos
    video_dir = script_dir / args.organized_videos
    file_index = build_file_index(photo_dir=photo_dir, video_dir=video_dir)

    # Scan archive
    print("\n" + "-" * 70)
    print("Scanning archive...")
    archive_files = scan_archive_files(archive_dir)
    print(f"Found {len(archive_files)} media files (excluding .MTS)")

    # Check each file
    print("\n" + "-" * 70)
    print("Checking for missing files...\n")

    found_count = 0
    missing_count = 0
    no_date_count = 0
    missing_files = []
    mts_skipped = 0

    for file_path, date_pattern in archive_files:
        existing = check_file_exists(date_pattern, file_index, file_path.name)

        if existing:
            found_count += 1

            if args.verbose:
                print(f"  FOUND: {file_path.name}")
                print(f"         -> {existing}")
        else:
            missing_count += 1
            missing_files.append(file_path)

            if date_pattern:
                print(f"  MISSING: {file_path}")
            else:
                no_date_count += 1
                print(f"  MISSING (no date): {file_path}")

    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"\n  Total files checked:  {len(archive_files)}")
    print(f"  Found in organized:   {found_count}")
    print(f"  MISSING:              {missing_count}")

    if no_date_count > 0:
        print(f"    (no date pattern):  {no_date_count}")

    if missing_count > 0:
        pct_missing = (missing_count / len(archive_files)) * 100
        print(f"\n  ⚠️  {pct_missing:.1f}% of archive files are MISSING from organized directories")

        # Calculate size of missing files
        missing_size = sum(f.stat().st_size for f in missing_files if f.exists())
        missing_mb = missing_size / (1024 * 1024)
        missing_gb = missing_size / (1024 * 1024 * 1024)

        if missing_gb >= 1:
            print(f"  Missing data size:    {missing_gb:.2f} GB")
        else:
            print(f"  Missing data size:    {missing_mb:.1f} MB")

    # Write missing files to output if requested
    if args.output and missing_files:
        with open(args.output, 'w') as f:
            for path in missing_files:
                f.write(f"{path}\n")

        print(f"\n  Missing file list written to: {args.output}")

    print("")
    return 0 if missing_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
