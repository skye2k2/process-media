#!/usr/bin/env python3
"""
Organized Media Reprocessing Workflow

Menu-driven workflow for performing maintenance operations on already-organized
media files. Unlike the import workflows (workflow_takeout.py, workflow_archive.py),
this operates on files that are already in Organized_Photos/ and Organized_Videos/.

Available Actions:
1. Convert Legacy Formats - Convert AVI/MTS/WMV/etc. to H.265
2. Duplicate Check - Scan for potential duplicates within organized directories
3. (Future) Metadata Repair - Fix missing EXIF data
4. (Future) Thumbnail Generation - Generate preview thumbnails
5. (Future) Backup Verification - Verify NAS backup matches local

Usage:
    python3 workflow_reprocess.py

The workflow presents a menu and guides through each operation with
dry-run by default for safety.
"""

import sys
import time
from pathlib import Path

# ============================================================================
# CONFIGURATION
# ============================================================================

SCRIPT_DIR = Path(__file__).parent
VIDEO_OUTPUT_DIR = SCRIPT_DIR / "Organized_Videos"
PHOTO_OUTPUT_DIR = SCRIPT_DIR / "Organized_Photos"


# ============================================================================
# MENU DISPLAY
# ============================================================================

def print_header():
    """Print workflow header."""
    print()
    print('=' * 70)
    print("Organized Media Reprocessing Workflow")
    print('=' * 70)
    print()
    print(f"Video directory: {VIDEO_OUTPUT_DIR}")
    print(f"Photo directory: {PHOTO_OUTPUT_DIR}")
    print()


def print_menu():
    """Print available actions menu."""
    print('-' * 70)
    print("Available Actions:")
    print('-' * 70)
    print()
    print("  1. Convert Legacy Formats")
    print("     Convert AVI, MTS, WMV, and other legacy formats to H.265/HEVC")
    print("     Replaces original files after verification")
    print()
    print("  2. Duplicate Check")
    print("     Scan organized directories for potential duplicate files")
    print("     Uses duration + size matching to identify duplicates")
    print()
    print("  3. Deep Codec Scan")
    print("     Check ALL video files (including MP4) for legacy codecs")
    print("     Slower but catches H.264 videos that could be converted")
    print()
    print("  4. Fix Motion Photos")
    print("     Find Pixel Motion Photos (dual-stream videos that break QuickLook)")
    print("     Extract stills, delete videos, or make QuickLook-compatible")
    print()
    print("  0. Exit")
    print()


def get_user_choice(prompt, valid_choices):
    """
    Get validated user input.

    Args:
        prompt: Prompt to display
        valid_choices: List of valid input values

    Returns:
        str: User's validated choice
    """
    while True:
        choice = input(prompt).strip().lower()

        if choice in valid_choices:
            return choice

        print(f"Invalid choice. Please enter one of: {', '.join(valid_choices)}")


def confirm_action(action_name, dry_run=True):
    """
    Confirm user wants to proceed with action.

    Args:
        action_name: Name of the action
        dry_run: Whether this will be a dry run

    Returns:
        bool: True if user confirms
    """
    print()

    if dry_run:
        print(f"Ready to perform: {action_name} (DRY RUN)")
        print("No changes will be made - this is a preview only.")
    else:
        print(f"Ready to perform: {action_name}")
        print("⚠️  This will make actual changes to your files!")

    print()
    response = get_user_choice("Proceed? [y/n]: ", ['y', 'n', 'yes', 'no'])

    return response in ['y', 'yes']


# ============================================================================
# ACTION HANDLERS
# ============================================================================

def action_convert_legacy(deep_scan=False):
    """
    Run legacy format conversion.

    Args:
        deep_scan: If True, also check MP4/MOV for legacy codecs
    """
    # Import here to avoid circular imports and allow menu to display quickly
    from convert_legacy import process_legacy_videos, print_summary, find_legacy_videos

    print()
    print('-' * 70)

    if deep_scan:
        print("Deep Codec Scan - Checking all video files for legacy codecs")
    else:
        print("Legacy Format Conversion - Converting AVI/MTS/WMV to H.265")

    print('-' * 70)

    # First, show what would be found
    print("\nScanning for legacy videos...")
    print()

    # Do a quick scan to show counts
    from convert_legacy import VIDEO_OUTPUT_DIR as LEGACY_VIDEO_DIR
    legacy_videos = find_legacy_videos(LEGACY_VIDEO_DIR, check_all_codecs=deep_scan)

    if not legacy_videos:
        print("\nNo legacy videos found. Nothing to convert.")
        return

    print(f"\nFound {len(legacy_videos)} videos to convert:")
    print()

    # Show first 20 files
    for i, (file_path, reason) in enumerate(legacy_videos[:20]):
        rel_path = file_path.relative_to(LEGACY_VIDEO_DIR)
        size_mb = file_path.stat().st_size / 1024 / 1024
        print(f"  {rel_path}")
        print(f"    {reason}, {size_mb:.1f} MB")

    if len(legacy_videos) > 20:
        print(f"\n  ... and {len(legacy_videos) - 20} more files")

    # Calculate total size
    total_size = sum(f.stat().st_size for f, _ in legacy_videos)
    total_gb = total_size / 1024 / 1024 / 1024
    print(f"\nTotal size: {total_gb:.2f} GB")

    # Estimate time (rough: ~1 minute per 100MB for slow preset)
    est_minutes = (total_size / 1024 / 1024) / 100
    print(f"Estimated time: ~{est_minutes:.0f} minutes (varies by file)")

    # Dry run first
    print()

    if not confirm_action("Legacy format conversion (dry run)", dry_run=True):
        print("\nCancelled.")
        return

    start_time = time.time()
    stats = process_legacy_videos(
        dry_run=True,
        check_all_codecs=deep_scan,
        delete_original=True
    )
    elapsed = time.time() - start_time

    print_summary(stats, dry_run=True)
    print(f"\nDry run completed in {elapsed:.1f} seconds")

    # Offer to run for real
    print()
    response = get_user_choice(
        "Run for real (this will take a while)? [y/n]: ",
        ['y', 'n', 'yes', 'no']
    )

    if response not in ['y', 'yes']:
        print("\nConversion cancelled. Files unchanged.")
        return

    print()
    print("=" * 70)
    print("EXECUTING CONVERSIONS - This may take a long time")
    print("=" * 70)

    start_time = time.time()
    stats = process_legacy_videos(
        dry_run=False,
        check_all_codecs=deep_scan,
        delete_original=True
    )
    elapsed = time.time() - start_time

    print_summary(stats, dry_run=False)

    hours = int(elapsed // 3600)
    minutes = int((elapsed % 3600) // 60)
    seconds = int(elapsed % 60)

    if hours > 0:
        print(f"\nCompleted in {hours}h {minutes}m {seconds}s")
    elif minutes > 0:
        print(f"\nCompleted in {minutes}m {seconds}s")
    else:
        print(f"\nCompleted in {seconds}s")


def action_duplicate_check():
    """Run duplicate detection on organized directories."""
    # Import here to avoid circular imports
    from duplicate_detector import DuplicateDetector

    print()
    print('-' * 70)
    print("Duplicate Check - Scanning for duplicates within organized directories")
    print('-' * 70)
    print()

    print("Initializing duplicate detector...")
    detector = DuplicateDetector(
        photo_dir=PHOTO_OUTPUT_DIR,
        video_dir=VIDEO_OUTPUT_DIR,
        duration_tolerance=1.0,
        size_tolerance=0.20
    )

    print()
    print("This feature scans for potential duplicates within your organized")
    print("directories - files that may have been imported multiple times or")
    print("exist in multiple locations.")
    print()

    # For now, just show the index stats
    print(f"Index contains {len(detector.file_index)} unique base names")
    print(f"Total files indexed: {sum(len(v) for v in detector.file_index.values())}")

    # Find files with same base name in multiple locations
    duplicates_found = 0

    print()
    print("Scanning for files with same base name in multiple locations...")
    print()

    for base_name, matches in sorted(detector.file_index.items()):
        if len(matches) > 1:
            # Filter to actual duplicates (not just same name, different dates)
            # For now, just report multi-location files
            duplicates_found += 1

            if duplicates_found <= 20:
                print(f"  {base_name}: {len(matches)} copies")

                for match in matches[:3]:
                    rel_path = match.relative_to(VIDEO_OUTPUT_DIR) if VIDEO_OUTPUT_DIR in match.parents else match.relative_to(PHOTO_OUTPUT_DIR)
                    print(f"    - {rel_path}")

                if len(matches) > 3:
                    print(f"    ... and {len(matches) - 3} more")

    if duplicates_found > 20:
        print(f"\n  ... and {duplicates_found - 20} more base names with duplicates")

    print()
    print(f"Found {duplicates_found} base names with multiple copies")
    print()
    print("NOTE: This is informational only. Manual review recommended before")
    print("removing any files, as some may be intentional copies or edits.")

    # Save cache for future runs
    detector.save_duration_cache()


def action_motion_photos():
    """
    Handle Motion Photo files (Pixel videos with embedded stills).

    Presents submenu for different actions:
    - Scan only
    - Extract stills
    - Extract stills and delete videos
    - Fix for QuickLook (strip embedded still)
    """
    from motion_photo_extract import (
        scan_for_motion_photos,
        process_motion_photos,
        print_summary
    )

    print()
    print('-' * 70)
    print("Motion Photo Handler")
    print('-' * 70)
    print()
    print("Google Pixel 'Motion Photos' embed a still image in video files.")
    print("These dual-stream videos don't play in macOS QuickLook/Preview.")
    print()

    # Scan first
    print("Scanning Organized_Videos/ for Motion Photos...")
    motion_photos = scan_for_motion_photos(VIDEO_OUTPUT_DIR, recursive=True)

    print_summary(motion_photos)

    if not motion_photos:
        print("\nNo Motion Photos found.")
        return

    # Submenu for action
    print()
    print('-' * 40)
    print("What would you like to do?")
    print()
    print("  1. Extract stills only (keep videos)")
    print("  2. Extract stills and delete videos")
    print("  3. Fix for QuickLook (strip embedded still, keep playable video)")
    print("  0. Cancel")
    print()

    action_choice = get_user_choice("Select action [0-3]: ", ['0', '1', '2', '3'])

    if action_choice == '0':
        print("\nCancelled.")
        return

    action_map = {
        '1': 'extract',
        '2': 'extract-delete',
        '3': 'fix-quicklook'
    }
    action = action_map[action_choice]

    action_names = {
        'extract': 'Extract stills (keep videos)',
        'extract-delete': 'Extract stills and delete videos',
        'fix-quicklook': 'Fix for QuickLook'
    }

    # Dry run first
    if not confirm_action(f"{action_names[action]} (dry run)", dry_run=True):
        print("\nCancelled.")
        return

    print()
    stats = process_motion_photos(motion_photos, action, dry_run=True)

    print()
    print(f"Dry run complete: {stats['processed']} files would be processed")

    # Offer to run for real
    print()
    response = get_user_choice(
        "Run for real? [y/n]: ",
        ['y', 'n', 'yes', 'no']
    )

    if response not in ['y', 'yes']:
        print("\nCancelled.")
        return

    print()
    print("Processing for real...")
    print()

    stats = process_motion_photos(motion_photos, action, dry_run=False)

    print()
    print('-' * 40)
    print("Results:")
    print(f"  Processed: {stats['processed']}")
    if stats['extracted']:
        print(f"  Stills extracted: {stats['extracted']}")
    if stats['fixed']:
        print(f"  Fixed for QuickLook: {stats['fixed']}")
    if stats['deleted']:
        print(f"  Videos deleted: {stats['deleted']}")
    if stats['errors']:
        print(f"  Errors: {stats['errors']}")


# ============================================================================
# MAIN WORKFLOW
# ============================================================================

def main():
    """Main workflow entry point."""
    print_header()

    while True:
        print_menu()

        choice = get_user_choice("Select action [0-4]: ", ['0', '1', '2', '3', '4'])

        if choice == '0':
            print("\nExiting. No changes made.")
            sys.exit(0)

        elif choice == '1':
            action_convert_legacy(deep_scan=False)

        elif choice == '2':
            action_duplicate_check()

        elif choice == '3':
            action_convert_legacy(deep_scan=True)

        elif choice == '4':
            action_motion_photos()

        print()
        input("Press Enter to return to menu...")
        print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Exiting.")
        sys.exit(1)
