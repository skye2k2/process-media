#!/usr/bin/env python3
"""
Shared file indexing utility for fast O(1) duplicate detection.

Builds an in-memory index of all organized media files, keyed by
(base_name, extension, is_edited) for instant lookups.

Used by:
- organize_media.py: Duplicate detection during organization
- cleanup_orphaned_json.py: Finding matching media for orphaned JSON
"""

from collections import defaultdict
from pathlib import Path
import re

from media_utils import MEDIA_EXTENSIONS

# Default output directories (can be overridden)
DEFAULT_PHOTO_DIR = Path("Organized_Photos")
DEFAULT_VIDEO_DIR = Path("Organized_Videos")


def build_file_index(photo_dir=None, video_dir=None, person_name=None):
    """
    Build an in-memory index of all organized files for fast duplicate detection.

    Args:
        photo_dir: Path to organized photos directory (default: Organized_Photos)
        video_dir: Path to organized videos directory (default: Organized_Videos)
        person_name: Optional person name suffix to strip (e.g., "Clif")

    Returns:
        dict: {(base_name, ext, is_edited): [file_paths]}

    The index key structure:
    - base_name: Filename stem with person suffix and -edited removed
    - ext: Lowercase file extension (e.g., '.jpg')
    - is_edited: Boolean indicating if this is an -edited variant

    This allows O(1) lookups while correctly distinguishing originals from edited variants.
    """
    if photo_dir is None:
        photo_dir = DEFAULT_PHOTO_DIR
    if video_dir is None:
        video_dir = DEFAULT_VIDEO_DIR

    print("Building file index for fast lookups...")
    file_index = defaultdict(list)
    file_count = 0

    for base_dir in [photo_dir, video_dir]:
        if not base_dir.exists():
            continue

        for ext in MEDIA_EXTENSIONS:
            for file_path in base_dir.rglob(f"*{ext}"):
                if file_path.is_file():
                    base = file_path.stem
                    ext_lower = file_path.suffix.lower()

                    # Strip person suffix (e.g., "_Clif", "_John")
                    base_without_suffix = base
                    if person_name and base.endswith(f"_{person_name}"):
                        base_without_suffix = base[:-len(person_name)-1]
                    else:
                        # Try to detect any person suffix (pattern: ends with _Name)
                        match = re.match(r'^(.+)_([A-Z][a-z]+)$', base)
                        if match:
                            base_without_suffix = match.group(1)

                    # Determine if edited
                    is_edited = base_without_suffix.endswith('-edited')

                    # Strip -edited for indexing
                    if is_edited:
                        base_without_suffix = base_without_suffix[:-7]

                    index_key = (base_without_suffix, ext_lower, is_edited)
                    file_index[index_key].append(file_path)
                    file_count += 1

    print(f"  Indexed {file_count} files with {len(file_index)} unique base names")
    return file_index


def lookup_in_index(media_filename, file_index):
    """
    Look up a media file in the index.

    Args:
        media_filename: The filename to search for (e.g., "IMG_1234.jpg")
        file_index: The index dict from build_file_index()

    Returns:
        list: Matching file paths, or empty list if not found
    """
    name_parts = media_filename.rsplit('.', 1)
    if len(name_parts) != 2:
        return []

    base = name_parts[0]
    ext = '.' + name_parts[1].lower()

    # Strip person suffix from base if present
    base_without_suffix = base
    match = re.match(r'^(.+)_([A-Z][a-z]+)$', base)
    if match:
        base_without_suffix = match.group(1)

    # Check if it's an edited file
    is_edited = base_without_suffix.endswith('-edited')
    if is_edited:
        base_without_suffix = base_without_suffix[:-7]

    # Look up in index
    index_key = (base_without_suffix, ext, is_edited)
    matches = file_index.get(index_key, [])

    # Also check for the opposite edited status if no matches
    if not matches:
        alt_key = (base_without_suffix, ext, not is_edited)
        matches = file_index.get(alt_key, [])

    return matches


if __name__ == "__main__":
    # When run directly, just build and display the index stats
    index = build_file_index()
    print(f"\nIndex contains {len(index)} unique file keys")
