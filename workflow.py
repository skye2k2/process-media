#!/usr/bin/env python3
"""
Google Takeout Master Processing Script
Orchestrates the complete workflow for processing Google Takeout photo exports.

Workflow:
1. Fix truncated file extensions (.MP -> .mp4)
2. Organize photos/videos by date with person tagging (reads JSON metadata, deletes duplicates)
3. Merge remaining JSON metadata into EXIF data (removes JSON files after)
"""

import subprocess
import sys
import time
from pathlib import Path


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
    start_time = time.time()
    script_dir = Path(__file__).parent

    print("\n" + "=" * 80)
    print("Google Takeout Master Processing Script")
    print("=" * 80)
    print("\nThis script will:")
    print("  1. Fix truncated file extensions (e.g., .MP -> .mp4)")
    print("  2. Organize photos/videos by date (deleting duplicates from project folders)")
    print("  3. Reunite fractured project directories (move media to project folders)")
    print("  4. Clean up orphaned JSON metadata files")
    print("  5. Merge remaining JSON metadata into EXIF data (review files only)")
    print("\n" + "=" * 80 + "\n")

    # Prompt for person name
    person_name = input("Enter person's name for this import (or press Enter to skip person tagging): ").strip()

    if person_name:
        print(f"\nProcessing photos for: {person_name}")
    else:
        print("\nProcessing photos without person tagging")

    confirm = input("\nReady to proceed? (Y/n): ").strip().upper()
    if confirm != 'Y':
        print("\nCancelled by user")
        return 1

    # Step 1: Fix truncated extensions
    print("\n" + "=" * 80)
    print("PHASE 1: PREPARATION")
    print("=" * 80)

    success, fix_time = run_script(
        str(script_dir / "fix_truncated_extensions.py"),
        ["TAKEOUT_DATA/"],
        "Fixing truncated file extensions"
    )
    if not success:
        print("\n❌ Failed to fix extensions")
        return 1

    # Step 2: Organize photos (reads JSON, deletes duplicates)
    print("\n" + "=" * 80)
    print("PHASE 2: ORGANIZATION")
    print("=" * 80)

    # Check if TAKEOUT_DATA has any files to process
    takeout_data_dir = script_dir / "TAKEOUT_DATA"
    has_files = False
    if takeout_data_dir.exists():
        for root, dirs, files in takeout_data_dir.walk():
            if any(Path(root, f).suffix.lower() in {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.heic', '.heif', '.mp4', '.mov', '.avi', '.mkv', '.m4v', '.3gp', '.wmv'} for f in files):
                has_files = True
                break

    # Determine input directory
    if not has_files:
        review_dir = script_dir / "Organized_Photos" / "_TO_REVIEW_"
        if review_dir.exists() and any(review_dir.iterdir()):
            print(f"\nNo files found in TAKEOUT_DATA/")
            print(f"Processing files from _TO_REVIEW_ instead...")
            input_dir = "Organized_Photos/_TO_REVIEW_"
        else:
            print(f"\nNo files found in TAKEOUT_DATA/ or _TO_REVIEW_/")
            print(f"Nothing to process.")
            return 0
    else:
        input_dir = "TAKEOUT_DATA"

    organize_args = ["--input-dir", input_dir]
    if person_name:
        organize_args.extend(["--person", person_name])

    success, organize_time = run_script(
        str(script_dir / "organize_media.py"),
        organize_args,
        f"Organizing photos{' for ' + person_name if person_name else ''}"
    )
    if not success:
        print("\n❌ Failed to organize photos")
        return 1

    # Step 3: Reunite fractured project directories
    print("\n" + "=" * 80)
    print("PHASE 3: POST-PROCESSING")
    print("=" * 80)

    success, reunite_time = run_script(
        str(script_dir / "fix_fragmented_metadata.py"),
        [],
        "Reuniting fractured project directories"
    )
    if not success:
        print("\n⚠️  Warning: Failed to reunite project files")
        # Don't fail the whole workflow for this
        reunite_time = 0

    # Step 4: Clean up orphaned JSON files
    # Run cleanup script with --yes flag for automatic confirmation
    print("\n" + "=" * 80)
    print("Cleaning up orphaned JSON metadata files")
    print("=" * 80 + "\n")

    cleanup_start = time.time()
    try:
        result = subprocess.run(
            [sys.executable, str(script_dir / "cleanup_orphaned_json.py"), "--yes"],
            check=False
        )
        cleanup_time = time.time() - cleanup_start
        if result.returncode != 0:
            print("\n⚠️  Warning: Orphaned JSON cleanup encountered issues")
    except Exception as e:
        cleanup_time = time.time() - cleanup_start
        print(f"\n⚠️  Warning: Error during cleanup: {e}")

    # Step 5: Merge metadata for _TO_REVIEW_ only
    # (Regular files have EXIF written during organization, only review files need merging)
    print("\n" + "=" * 80)
    print("PHASE 4: METADATA (review files only)")
    print("=" * 80)

    review_dir = script_dir / "Organized_Photos" / "_TO_REVIEW_"
    merge_time = 0

    if review_dir.exists() and any(review_dir.iterdir()):
        success, merge_time = run_script(
            str(script_dir / "merge_metadata.py"),
            ["Organized_Photos/_TO_REVIEW_/", "--recursive", "--remove-json"],
            "Merging JSON metadata into EXIF for review files"
        )
        if not success:
            print("\n⚠️  Warning: Failed to merge metadata for review files")
            # Don't fail the whole workflow for this
    else:
        print("\nNo files in _TO_REVIEW_, skipping metadata merge.")

    # Success!
    elapsed_time = time.time() - start_time
    minutes, seconds = divmod(int(elapsed_time), 60)
    hours, minutes = divmod(minutes, 60)

    print("\n" + "=" * 80)
    print("✅ PROCESSING COMPLETE")
    print("=" * 80)
    print("\nResults:")
    print(f"  - Photos organized in: Organized_Photos/")
    print(f"  - Videos organized in: Organized_Videos/")
    print(f"  - Files needing review: Organized_Photos/_TO_REVIEW_/")
    print("\nNext steps:")
    print("  1. Review any files in _TO_REVIEW_/")
    print("  2. Check Trash_Archives/ for files to permanently delete")
    if person_name:
        print(f"  3. All files tagged with owner: {person_name}")

    # Format time helper
    def format_time(seconds):
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}h {m}m {s}s"
        elif m > 0:
            return f"{m}m {s}s"
        else:
            return f"{s}s"

    print("\nProcessing times:")
    print(f"  - Fix extensions: {format_time(fix_time)}")
    print(f"  - Organize files: {format_time(organize_time)}")
    print(f"  - Reunite projects: {format_time(reunite_time)}")
    print(f"  - Cleanup orphaned JSON: {format_time(cleanup_time)}")
    print(f"  - Merge metadata: {format_time(merge_time)}")
    print(f"  - Total time: {format_time(elapsed_time)}")
    print("\n" + "=" * 80 + "\n")

    return 0


if __name__ == "__main__":
    try:
        exit(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        exit(1)
