#!/usr/bin/env python3
"""
Reunite fractured project directories by finding media files that belong to projects
but ended up in dated folders.

Google Takeout sometimes splits projects: the project folder contains JSON metadata,
but the actual media files appear in "Photos from YYYY" dated folders in later exports.

This script:
1. Walks through organized project directories
2. Finds JSON metadata files without corresponding media files
3. Searches organized photos for those media files
4. Applies EXIF metadata from JSON to media files
5. Moves media files from dated folders into their proper project folders
6. Deletes JSON files after successful reunification
"""

from pathlib import Path
import re
import shutil

from media_utils import (
    apply_exif_metadata,
    extract_media_filename,
    is_month_folder,
    parse_json_metadata_raw,
)

ORGANIZED_PHOTOS = Path("Organized_Photos")
ORGANIZED_VIDEOS = Path("Organized_Videos")


def is_project_folder(name):
    """Check if a folder name represents a project folder (not a regular month folder)"""
    return not is_month_folder(name)


# Note: extract_media_filename is imported from media_utils


def find_media_file_in_organized(media_filename, search_base):
    """
    Search for a media file in the organized directory structure.
    Returns the path if found, None otherwise.
    """
    # Search in all year directories, but skip project folders
    for year_dir in search_base.iterdir():
        if not year_dir.is_dir():
            continue

        # Skip if not a year directory
        if not year_dir.name.isdigit():
            continue

        # Search in month folders (skip project folders)
        for month_dir in year_dir.iterdir():
            if not month_dir.is_dir():
                continue

            # Skip project folders
            if is_project_folder(month_dir.name):
                continue

            # Check if media file exists in this month folder
            media_path = month_dir / media_filename
            if media_path.exists():
                return media_path

            # Also check for -edited variant
            name_parts = media_filename.rsplit('.', 1)
            if len(name_parts) == 2:
                edited_filename = f"{name_parts[0]}-edited.{name_parts[1]}"
                edited_path = month_dir / edited_filename
                if edited_path.exists():
                    return edited_path

    return None


def fix_fragmented_metadata(dry_run=False):
    """
    Main function to reunite fractured project files.

    Args:
        dry_run: If True, only report what would be done without making changes
    """
    stats = {
        'orphaned_json_found': 0,
        'media_found': 0,
        'media_moved': 0,
        'json_deleted': 0,
        'media_not_found': 0,
    }

    print("Scanning for fractured project directories...\n")

    for base_dir in [ORGANIZED_PHOTOS, ORGANIZED_VIDEOS]:
        if not base_dir.exists():
            continue

        print(f"Processing {base_dir}/")

        # Walk through all year directories
        for year_dir in base_dir.iterdir():
            if not year_dir.is_dir() or not year_dir.name.isdigit():
                continue

            # Look for project folders
            for folder in year_dir.iterdir():
                if not folder.is_dir():
                    continue

                # Skip regular month folders
                if not is_project_folder(folder.name):
                    continue

                # This is a project folder - scan for orphaned JSON files
                json_files = list(folder.glob("*.json"))

                for json_path in json_files:
                    media_filename = extract_media_filename(json_path)

                    if not media_filename:
                        continue  # Skip metadata.json

                    # Check if corresponding media file exists in project folder
                    media_in_project = folder / media_filename

                    # Also check for -edited variant
                    name_parts = media_filename.rsplit('.', 1)
                    edited_filename = f"{name_parts[0]}-edited.{name_parts[1]}" if len(name_parts) == 2 else None
                    edited_in_project = folder / edited_filename if edited_filename else None

                    if media_in_project.exists() or (edited_in_project and edited_in_project.exists()):
                        # Media file exists - JSON should be deleted after EXIF is written
                        # (This is handled by normal processing, skip for now)
                        continue

                    # Orphaned JSON - find the media file
                    stats['orphaned_json_found'] += 1

                    media_path = find_media_file_in_organized(media_filename, base_dir)

                    if media_path:
                        stats['media_found'] += 1
                        relative_path = media_path.relative_to(base_dir)
                        print(f"  Found: {media_filename}")
                        print(f"    JSON in: {folder.relative_to(base_dir)}")
                        print(f"    Media in: {relative_path.parent}")

                        if not dry_run:
                            # Parse JSON and apply EXIF metadata BEFORE moving
                            timestamp, geo_data = parse_json_metadata_raw(json_path)
                            if timestamp or geo_data:
                                if apply_exif_metadata(media_path, timestamp, geo_data):
                                    print(f"    ✓ Applied EXIF metadata")
                                else:
                                    print(f"    ⚠ Failed to apply EXIF metadata")

                            # Move media file to project folder
                            dest_path = folder / media_path.name

                            # Handle name conflicts
                            if dest_path.exists():
                                counter = 1
                                stem = dest_path.stem
                                ext = dest_path.suffix
                                while dest_path.exists():
                                    dest_path = folder / f"{stem}_{counter}{ext}"
                                    counter += 1

                            try:
                                shutil.move(str(media_path), str(dest_path))
                                stats['media_moved'] += 1
                                print(f"    ✓ Moved to project folder")

                                # Delete the JSON file after successful move
                                json_path.unlink()
                                stats['json_deleted'] += 1
                                print(f"    ✓ Deleted JSON metadata")
                            except Exception as e:
                                print(f"    ✗ Error: {e}")
                        else:
                            print(f"    [DRY RUN] Would move to project folder")
                    else:
                        stats['media_not_found'] += 1
                        print(f"  Orphaned: {media_filename}")
                        print(f"    JSON in: {folder.relative_to(base_dir)}")
                        print(f"    Media not found in organized structure")

    # Print summary
    print(f"\n{'='*60}")
    print("Summary:")
    print(f"  Orphaned JSON files found: {stats['orphaned_json_found']}")
    print(f"  Corresponding media files found: {stats['media_found']}")
    print(f"  Media files moved: {stats['media_moved']}")
    print(f"  JSON files deleted: {stats['json_deleted']}")
    print(f"  Media files not found: {stats['media_not_found']}")

    if stats['media_not_found'] > 0:
        print(f"\nNote: {stats['media_not_found']} media files were not found.")
        print("They may still be in the Takeout source and will be processed later.")


if __name__ == "__main__":
    import sys

    dry_run = '--dry-run' in sys.argv

    if dry_run:
        print("DRY RUN MODE - No changes will be made\n")

    fix_fragmented_metadata(dry_run=dry_run)

    if dry_run:
        print("\nRun without --dry-run to actually move files")
