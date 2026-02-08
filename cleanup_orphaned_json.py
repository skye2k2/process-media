#!/usr/bin/env python3
"""
Find and intelligently handle orphaned JSON metadata files.

These can occur when:
1. Media files were deleted as duplicates but JSON wasn't
2. Project folders were moved wholesale with JSON but media went elsewhere
3. Processing errors left JSON behind
4. Google Takeout fragmentation split media and metadata across archives

Before deleting, this script:
1. Builds a file index for O(1) lookups (same as organize_media.py)
2. Searches for matching media files using the index
3. If found (especially in _TO_REVIEW_ or inferred January folders), applies EXIF metadata
4. Only deletes truly orphaned JSON (no media found anywhere)
"""

import argparse
from datetime import datetime
from pathlib import Path
import re

from build_file_index import build_file_index, lookup_in_index
from media_utils import (
    MEDIA_EXTENSIONS,
    apply_exif_metadata,
    extract_media_filename,
    parse_json_metadata_raw,
)

ORGANIZED_PHOTOS = Path("Organized_Photos")
ORGANIZED_VIDEOS = Path("Organized_Videos")
REVIEW_DIR = ORGANIZED_PHOTOS / "_TO_REVIEW_"

# Note: extract_media_filename is imported from media_utils


def find_media_file_locally(json_path):
    """Check if media file exists in the same directory as the JSON."""
    media_filename = extract_media_filename(json_path)
    if not media_filename:
        return None

    directory = json_path.parent
    media_path = directory / media_filename

    if media_path.exists():
        return media_path

    # Check for -edited variant
    name_parts = media_filename.rsplit('.', 1)
    if len(name_parts) == 2:
        edited_path = directory / f"{name_parts[0]}-edited.{name_parts[1]}"
        if edited_path.exists():
            return edited_path

    return None


def find_media_in_organized(media_filename, file_index):
    """
    Search for a media file using the pre-built index (O(1) lookup).
    Returns (path, priority) where priority indicates how valuable metadata would be:
    - 0: In _TO_REVIEW_ (highest priority - file has no good date)
    - 1: In January folder (likely inferred date)
    - 2: In regular dated folder (lower priority - already has date)
    """
    matches = lookup_in_index(media_filename, file_index)

    if not matches:
        return None, None

    # Find highest priority match (prefer _TO_REVIEW_ and January folders)
    best_match = None
    best_priority = 999

    for file_path in matches:
        priority = determine_priority(file_path)
        if priority < best_priority:
            best_priority = priority
            best_match = file_path

    return best_match, best_priority


def determine_priority(file_path):
    """
    Determine how valuable applying metadata would be for this file.
    Lower number = higher priority (more valuable to apply metadata).
    """
    path_str = str(file_path)

    # Highest priority: files in _TO_REVIEW_ (no date information)
    if '_TO_REVIEW_' in path_str:
        return 0

    # High priority: files in January folders (likely inferred dates)
    if '/01 January/' in path_str or '\\01 January\\' in path_str:
        return 1

    # Normal priority: files in other dated folders
    return 2


# Note: parse_json_metadata_raw and apply_exif_metadata are imported from media_utils


def safe_input(prompt, auto_yes=False):
    """
    Safely prompt for user input, handling non-interactive contexts.

    Args:
        prompt: The prompt to display
        auto_yes: If True, skip prompt and return 'yes'

    Returns:
        User response or 'yes' if auto_yes or 'no' on EOF
    """
    if auto_yes:
        print(prompt + "yes (auto)")
        return 'yes'

    print(prompt, end='')
    try:
        return input().strip().lower()
    except EOFError:
        print("no (non-interactive)")
        return 'no'


def main(auto_yes=False):
    """
    Main cleanup function that intelligently handles orphaned JSON files.

    Args:
        auto_yes: If True, automatically answer 'yes' to all prompts
    """
    stats = {
        'json_found': 0,
        'has_local_media': 0,
        'found_in_organized': 0,
        'metadata_applied': 0,
        'truly_orphaned': 0,
        'deleted': 0,
    }

    orphaned_json = []  # Truly orphaned (no media found anywhere)
    recoverable_json = []  # Has matching media in organized structure

    # Build file index once for O(1) lookups (uses shared module)
    file_index = build_file_index(ORGANIZED_PHOTOS, ORGANIZED_VIDEOS)

    print("\nScanning for orphaned JSON files...")

    for base_dir in [ORGANIZED_PHOTOS, ORGANIZED_VIDEOS]:
        if not base_dir.exists():
            continue

        print(f"\nScanning {base_dir}...")
        json_files = list(base_dir.rglob("*.json"))
        stats['json_found'] += len(json_files)
        print(f"  Found {len(json_files)} JSON files")

        for json_path in json_files:
            # Skip folder metadata.json files
            if json_path.name == 'metadata.json':
                continue

            # Skip analysis cache files (used by photo_triage.py)
            if json_path.name == '.analysis_cache.json':
                continue

            # First check if media exists locally
            local_media = find_media_file_locally(json_path)
            if local_media:
                stats['has_local_media'] += 1
                continue  # Not orphaned - media is right there

            # Media not local - search using file index (O(1) lookup)
            media_filename = extract_media_filename(json_path)
            if not media_filename:
                orphaned_json.append((json_path, None, None))
                stats['truly_orphaned'] += 1
                continue

            found_path, priority = find_media_in_organized(media_filename, file_index)

            if found_path:
                stats['found_in_organized'] += 1
                recoverable_json.append((json_path, found_path, priority))
            else:
                orphaned_json.append((json_path, None, None))
                stats['truly_orphaned'] += 1

    # Report findings
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"Total JSON files scanned: {stats['json_found']}")
    print(f"JSON with local media (skipped): {stats['has_local_media']}")
    print(f"JSON with media found elsewhere: {stats['found_in_organized']}")
    print(f"Truly orphaned JSON (no media): {stats['truly_orphaned']}")

    # Handle recoverable JSON (apply metadata then delete)
    if recoverable_json:
        print(f"\n{'='*70}")
        print("RECOVERABLE METADATA")
        print(f"{'='*70}")
        print(f"\nFound {len(recoverable_json)} JSON files with matching media elsewhere:")

        # Group by priority for display
        priority_labels = {
            0: "_TO_REVIEW_ (no date - HIGH VALUE)",
            1: "January folder (inferred date - HIGH VALUE)",
            2: "Dated folder (has date - lower value)",
        }

        for priority in sorted(priority_labels.keys()):
            matches = [(j, m, p) for j, m, p in recoverable_json if p == priority]
            if matches:
                print(f"\n  {priority_labels[priority]}: {len(matches)} files")
                for json_path, media_path, _ in matches[:5]:  # Show first 5
                    print(f"    {json_path.name} -> {media_path.name}")
                if len(matches) > 5:
                    print(f"    ... and {len(matches) - 5} more")

        response = safe_input("\nDo you want to apply this metadata to the matching files? (yes/no): ", auto_yes)

        if response in ('yes', 'y'):
            for json_path, media_path, priority in recoverable_json:
                timestamp, geo_data = parse_json_metadata_raw(json_path)

                if timestamp or geo_data:
                    if apply_exif_metadata(media_path, timestamp, geo_data):
                        stats['metadata_applied'] += 1
                        print(f"  ✓ Applied: {json_path.name} -> {media_path.name}")

                        # Delete JSON after successful application
                        try:
                            json_path.unlink()
                            stats['deleted'] += 1
                        except Exception as e:
                            print(f"    Warning: Could not delete {json_path.name}: {e}")
                    else:
                        print(f"  ✗ Failed: {json_path.name}")
                else:
                    # No useful metadata - just delete
                    print(f"  - No metadata: {json_path.name} (deleting)")
                    try:
                        json_path.unlink()
                        stats['deleted'] += 1
                    except Exception:
                        pass

            print(f"\nApplied metadata to {stats['metadata_applied']} files")

    # Handle truly orphaned JSON
    if orphaned_json:
        print(f"\n{'='*70}")
        print("TRULY ORPHANED JSON (no media found anywhere)")
        print(f"{'='*70}")
        print(f"\nFound {len(orphaned_json)} JSON files with no matching media:")

        for json_path, _, _ in orphaned_json[:10]:
            try:
                rel_path = json_path.relative_to(ORGANIZED_PHOTOS)
            except ValueError:
                try:
                    rel_path = json_path.relative_to(ORGANIZED_VIDEOS)
                except ValueError:
                    rel_path = json_path
            print(f"  {rel_path}")

        if len(orphaned_json) > 10:
            print(f"  ... and {len(orphaned_json) - 10} more")

        response = safe_input("\nDo you want to delete these orphaned JSON files? (yes/no): ", auto_yes)

        if response in ('yes', 'y'):
            for json_path, _, _ in orphaned_json:
                try:
                    json_path.unlink()
                    stats['deleted'] += 1
                except Exception as e:
                    print(f"  Error deleting {json_path}: {e}")

            print(f"\nDeleted {stats['deleted']} orphaned JSON files")
        else:
            print("\nNo files deleted")
    elif not recoverable_json:
        print("\nNo orphaned JSON files found!")

    # Final summary
    print(f"\n{'='*70}")
    print("FINAL STATS")
    print(f"{'='*70}")
    print(f"Metadata applied: {stats['metadata_applied']}")
    print(f"JSON files deleted: {stats['deleted']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Find and handle orphaned JSON metadata files"
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Automatically answer 'yes' to all prompts (for batch processing)"
    )
    args = parser.parse_args()
    main(auto_yes=args.yes)
