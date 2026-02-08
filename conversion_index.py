#!/usr/bin/env python3
"""
Persistent conversion index for video deduplication.

Tracks which videos have been converted to prevent re-processing the same
content from multiple backup sources. Uses (creation_date, file_size) as the
unique key since camcorder filenames are useless (00000.MTS, 00001.MTS, etc.).

Index file location: Organized_Videos/conversion_index.json

Used by:
- camcorder_convert.py: Check before conversion, add after successful conversion
"""

import json
from datetime import datetime
from pathlib import Path

# Index file version for future schema migrations
INDEX_VERSION = 1

# Default index location
DEFAULT_INDEX_PATH = Path(__file__).parent / "Organized_Videos" / "conversion_index.json"


def generate_index_key(creation_date, file_size):
    """
    Generate a unique key for the index based on creation date and file size.

    This combination uniquely identifies video content regardless of filename,
    since identical videos will have the same recording timestamp and byte count.

    Args:
        creation_date: datetime object of the video's creation/recording time
        file_size: Size of the original file in bytes

    Returns:
        str: Index key in format "YYYY-MM-DDTHH:MM:SS_SIZE"
    """
    date_str = creation_date.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{date_str}_{file_size}"


def load_index(index_path=None):
    """
    Load the conversion index from disk.

    Creates an empty index structure if the file doesn't exist.

    Args:
        index_path: Path to index file (default: Organized_Videos/conversion_index.json)

    Returns:
        dict: Index data structure with 'version' and 'entries' keys
    """
    if index_path is None:
        index_path = DEFAULT_INDEX_PATH

    index_path = Path(index_path)

    if not index_path.exists():
        return {
            "version": INDEX_VERSION,
            "entries": {}
        }

    try:
        with open(index_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Validate structure
        if "entries" not in data:
            data["entries"] = {}

        if "version" not in data:
            data["version"] = INDEX_VERSION

        return data

    except (json.JSONDecodeError, IOError) as e:
        print(f"  Warning: Could not load index {index_path}: {e}")
        print("  Starting with empty index.")
        return {
            "version": INDEX_VERSION,
            "entries": {}
        }


def save_index(index_data, index_path=None):
    """
    Save the conversion index to disk.

    Creates parent directories if needed. Writes atomically via temp file
    to prevent corruption on interruption.

    Args:
        index_data: Index data structure to save
        index_path: Path to index file (default: Organized_Videos/conversion_index.json)

    Returns:
        bool: True if successful, False otherwise
    """
    if index_path is None:
        index_path = DEFAULT_INDEX_PATH

    index_path = Path(index_path)

    try:
        # Ensure parent directory exists
        index_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file first, then rename (atomic on most filesystems)
        temp_path = index_path.with_suffix('.json.tmp')

        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(index_data, f, indent=2, sort_keys=True)

        temp_path.rename(index_path)
        return True

    except (IOError, OSError) as e:
        print(f"  Warning: Could not save index: {e}")
        return False


def lookup_in_index(index_data, creation_date, file_size):
    """
    Check if a video with given creation date and size has already been converted.

    Args:
        index_data: Loaded index data structure
        creation_date: datetime object of the video's creation time
        file_size: Size of the original file in bytes

    Returns:
        dict: Entry data if found, None otherwise
        Entry contains: original_name, original_path, output_name, output_path, converted_at
    """
    key = generate_index_key(creation_date, file_size)
    return index_data["entries"].get(key)


def add_to_index(index_data, creation_date, file_size, original_path, output_path):
    """
    Add a converted video to the index.

    Args:
        index_data: Loaded index data structure (modified in place)
        creation_date: datetime object of the video's creation time
        file_size: Size of the original file in bytes
        original_path: Path to the original source file
        output_path: Path to the converted output file (relative to Organized_Videos)

    Returns:
        str: The index key that was added
    """
    key = generate_index_key(creation_date, file_size)

    original_path = Path(original_path)
    output_path = Path(output_path)

    index_data["entries"][key] = {
        "original_name": original_path.name,
        "original_path": str(original_path),
        "original_size": file_size,
        "output_name": output_path.name,
        "output_path": str(output_path),
        "converted_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    }

    return key


def get_index_stats(index_data):
    """
    Get summary statistics about the conversion index.

    Args:
        index_data: Loaded index data structure

    Returns:
        dict: Statistics including entry_count, total_original_size, etc.
    """
    entries = index_data.get("entries", {})

    total_original_size = sum(
        entry.get("original_size", 0)
        for entry in entries.values()
    )

    return {
        "entry_count": len(entries),
        "total_original_size_mb": total_original_size / (1024 * 1024),
        "version": index_data.get("version", INDEX_VERSION)
    }


def print_index_summary(index_data):
    """
    Print a human-readable summary of the conversion index.

    Args:
        index_data: Loaded index data structure
    """
    stats = get_index_stats(index_data)

    print(f"  Conversion index: {stats['entry_count']} videos tracked")

    if stats['entry_count'] > 0:
        print(f"  Total original size: {stats['total_original_size_mb']:.1f} MB")
