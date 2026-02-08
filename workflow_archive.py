#!/usr/bin/env python3
"""
Archive Media Processing Workflow

Orchestrates the workflow for processing raw media files from NAS archives,
phone backups, or other sources that don't have JSON metadata files.

Unlike workflow_takeout.py (for Google Takeout with JSON), this workflow:
- Extracts dates from filenames (VID_YYYYMMDD_HHMMSS, IMG_YYYYMMDD_HHMMSS, etc.)
- Falls back to EXIF metadata or file modification time
- Uses smart duplicate detection (date + duration + size + quality analysis)
- Handles "bloated" re-encoded files by preferring smaller originals
- Preserves project folders as units

Usage:
    python3 workflow_archive.py              # Process TO_PROCESS/
    python3 workflow_archive.py --dry-run    # Preview without changes
    python3 workflow_archive.py /path/to/dir # Process custom directory
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path


def format_time(seconds):
    """Format seconds into human-readable string."""
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)

    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"


def format_size(bytes_val):
    """Format bytes into human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if abs(bytes_val) < 1024:
            return f"{bytes_val:.1f} {unit}"

        bytes_val /= 1024

    return f"{bytes_val:.1f} TB"


def count_media_files(directory):
    """Count media files in a directory."""
    media_extensions = {
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.heic', '.heif', '.webp',
        '.mp4', '.mov', '.avi', '.mkv', '.m4v', '.3gp', '.wmv', '.webm'
    }

    count = 0
    total_size = 0

    for item in Path(directory).rglob('*'):
        if item.is_file() and item.suffix.lower() in media_extensions:
            count += 1

            try:
                total_size += item.stat().st_size
            except OSError:
                pass

    return count, total_size


def run_script(script_name, args, description):
    """Run a Python script with given arguments. Returns (success, elapsed_time)."""
    print("\n" + "=" * 80)
    print(f"STEP: {description}")
    print("=" * 80 + "\n")

    cmd = [sys.executable, script_name] + args
    script_start = time.time()

    try:
        result = subprocess.run(cmd, check=True)
        elapsed = time.time() - script_start
        return result.returncode == 0, elapsed

    except subprocess.CalledProcessError as e:
        elapsed = time.time() - script_start
        print(f"\nError running {script_name}: {e}")
        return False, elapsed

    except KeyboardInterrupt:
        elapsed = time.time() - script_start
        print(f"\n\nInterrupted by user")
        return False, elapsed


def main():
    """Main workflow entry point."""
    parser = argparse.ArgumentParser(
        description="Process archive media files (NAS backups, phone exports, etc.)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s                     # Process files from TO_PROCESS/
    %(prog)s /path/to/media      # Process files from custom directory
    %(prog)s --dry-run           # Preview without making changes
        """
    )

    parser.add_argument(
        'input_dir',
        nargs='?',
        default=None,
        help="Directory containing media files (default: TO_PROCESS/)"
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help="Show what would be done without making changes"
    )

    args = parser.parse_args()

    start_time = time.time()
    script_dir = Path(__file__).parent
    input_dir = Path(args.input_dir) if args.input_dir else script_dir / "TO_PROCESS"

    # Header
    print("\n" + "=" * 80)
    print("Archive Media Processing Workflow")
    print("=" * 80)
    print("\nThis workflow processes raw media files WITHOUT JSON metadata.")
    print("For Google Takeout exports (with JSON), use workflow_takeout.py instead.")
    print("\nThis script will:")
    print("  1. Scan for media files and project folders")
    print("  2. Extract dates from filenames/EXIF/file timestamps")
    print("  3. Detect duplicates using date + duration + size matching")
    print("  4. Replace bloated re-encoded files with smaller originals")
    print("  5. Organize into year/month folder structure")

    if args.dry_run:
        print("\n*** DRY RUN MODE - No changes will be made ***")

    print("\n" + "-" * 80)

    # Validate input directory
    if not input_dir.exists():
        print(f"\n❌ ERROR: Input directory not found: {input_dir}")
        return 1

    # Count files to process
    file_count, total_size = count_media_files(input_dir)

    if file_count == 0:
        print(f"\n❌ No media files found in: {input_dir}")
        return 0

    print(f"\nInput directory: {input_dir}")
    print(f"Files to process: {file_count} ({format_size(total_size)})")

    # Confirm before proceeding (skip in dry-run mode)
    if not args.dry_run:
        print("\n" + "-" * 80)
        confirm = input("\nReady to proceed? (Y/n): ").strip().upper()

        if confirm not in ('', 'Y', 'YES'):
            print("\nCancelled by user")
            return 1

    # Run the organize_archive.py script
    print("\n" + "=" * 80)
    print("PHASE 1: ORGANIZATION")
    print("=" * 80)

    organize_args = [str(input_dir)]

    if args.dry_run:
        organize_args.append("--dry-run")

    success, organize_time = run_script(
        str(script_dir / "organize_archive.py"),
        organize_args,
        "Organizing archive media files"
    )

    if not success:
        print("\n❌ Failed to organize files")
        return 1

    # Summary
    elapsed_time = time.time() - start_time

    print("\n" + "=" * 80)
    print("✅ PROCESSING COMPLETE")
    print("=" * 80)

    if args.dry_run:
        print("\n*** DRY RUN - No files were moved ***")
        print("Run without --dry-run to process files.")
    else:
        print("\nResults:")
        print(f"  - Photos organized in: Organized_Photos/")
        print(f"  - Videos organized in: Organized_Videos/")
        print("\nNext steps:")
        print("  1. Verify files are organized correctly")
        print("  2. Delete source files from input directory if satisfied")
        print("  3. Run workflow_takeout.py for any Google Takeout exports")

    print("\nProcessing times:")
    print(f"  - Organization: {format_time(organize_time)}")
    print(f"  - Total time:   {format_time(elapsed_time)}")
    print("\n" + "=" * 80 + "\n")

    return 0


if __name__ == "__main__":
    try:
        exit(main())

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        exit(1)
