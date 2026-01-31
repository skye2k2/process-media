#!/usr/bin/env python3
"""
Shared media utilities for Google Takeout processing scripts.

Contains constants and functions used across multiple scripts to avoid
duplication and ensure consistent behavior.

Used by:
- build_file_index.py: Media extensions for indexing
- organize_media.py: Metadata parsing, EXIF application, constants
- cleanup_orphaned_json.py: Metadata parsing, EXIF application
- fix_fragmented_metadata.py: Metadata parsing, EXIF application
- check_leftover_files.py: Media extensions
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path

# ============================================================================
# CONSTANTS
# ============================================================================

# Media file extensions (case variations included for rglob matching)
PHOTO_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.heic', '.heif', '.webp', '.tiff',
    '.JPG', '.JPEG', '.PNG', '.HEIC'
}

VIDEO_EXTENSIONS = {
    '.mp4', '.mov', '.avi', '.mkv', '.m4v', '.3gp', '.wmv',
    '.MP4', '.MOV'
}

MEDIA_EXTENSIONS = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS

# Month names for directory creation (1-indexed, so index 0 is skipped)
MONTH_NAMES = [
    "01 January", "02 February", "03 March", "04 April",
    "05 May", "06 June", "07 July", "08 August",
    "09 September", "10 October", "11 November", "12 December"
]

# Set for O(1) month folder lookups (derived from MONTH_NAMES)
MONTH_FOLDER_NAMES = set(MONTH_NAMES)

# Google Takeout JSON suffix - the full expected suffix
# Truncation is handled dynamically by checking decreasing-length prefixes
JSON_FULL_SUFFIX = '.supplemental-metadata'
JSON_MIN_SUFFIX_LEN = 5  # Minimum recognizable: '.supp'


# ============================================================================
# DATE UTILITIES
# ============================================================================

def dates_match(date1, date2):
    """
    Check if two dates are within 3 months of each other.

    Used to detect conflicts between photoTakenTime and creationTime in
    Google Takeout metadata. When dates differ by 3+ months, it indicates
    the file may have been edited or re-uploaded significantly later.

    Args:
        date1: datetime object or None
        date2: datetime object or None

    Returns:
        bool: True if dates match (within 3 months) or either is None
    """
    if date1 is None or date2 is None:
        return True  # If either is None, consider them matching (no conflict)

    months_diff = abs((date1.year - date2.year) * 12 + (date1.month - date2.month))
    return months_diff < 3


def is_month_folder(folder_name):
    """
    Check if a folder name is a standard month folder (e.g., "01 January").

    Args:
        folder_name: The folder name to check

    Returns:
        bool: True if it matches the "MM MonthName" pattern
    """
    return folder_name in MONTH_FOLDER_NAMES

def strip_json_suffix(base):
    """
    Remove any truncated form of the supplemental-metadata suffix from a filename base.

    Google Takeout truncates filenames, so we might see:
    - filename.jpg.supplemental-metadata (full)
    - filename.jpg.supplemental-meta (truncated)
    - filename.jpg.supp (heavily truncated)

    This function checks from longest to shortest prefix of the full suffix,
    which naturally handles the "most specific first" matching requirement.

    Args:
        base: The filename base (after removing .json extension)

    Returns:
        str: The base with any supplemental-metadata suffix removed
    """
    # Check from longest to shortest prefix of the full suffix
    for length in range(len(JSON_FULL_SUFFIX), JSON_MIN_SUFFIX_LEN - 1, -1):
        prefix = JSON_FULL_SUFFIX[:length]

        if base.endswith(prefix):
            return base[:-length]

    return base


# ============================================================================
# JSON METADATA PARSING
# ============================================================================

def parse_json_metadata(json_path):
    """
    Parse Google Takeout JSON metadata file and extract timestamps and geo data.

    Args:
        json_path: Path to the JSON metadata file

    Returns:
        tuple: (photo_taken_datetime, creation_datetime, geo_data)
        - photo_taken_datetime: datetime from photoTakenTime, or None
        - creation_datetime: datetime from creationTime, or None
        - geo_data: dict with latitude/longitude/altitude, or None

    Note: Returns datetimes, not raw timestamps. For raw timestamp access,
    use parse_json_metadata_raw() instead.
    """
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        photo_taken = None
        creation_time = None
        geo_data = None

        # Extract photoTakenTime
        if 'photoTakenTime' in data and 'timestamp' in data['photoTakenTime']:
            try:
                timestamp = int(data['photoTakenTime']['timestamp'])
                photo_taken = datetime.fromtimestamp(timestamp)
            except (ValueError, OSError):
                pass

        # Extract creationTime
        if 'creationTime' in data and 'timestamp' in data['creationTime']:
            try:
                timestamp = int(data['creationTime']['timestamp'])
                creation_time = datetime.fromtimestamp(timestamp)
            except (ValueError, OSError):
                pass

        # Extract geoData (only if coordinates are non-zero)
        if 'geoData' in data:
            geo = data['geoData']
            lat = geo.get('latitude', 0)
            lon = geo.get('longitude', 0)

            if lat != 0 or lon != 0:
                geo_data = {
                    'latitude': lat,
                    'longitude': lon,
                    'altitude': geo.get('altitude', 0)
                }

        return photo_taken, creation_time, geo_data

    except (json.JSONDecodeError, IOError) as e:
        print(f"  Warning: Could not parse metadata {json_path}: {e}")
        return None, None, None


def parse_json_metadata_raw(json_path):
    """
    Parse Google Takeout JSON and return raw timestamp (for scripts that need
    the integer timestamp rather than datetime objects).

    Args:
        json_path: Path to the JSON metadata file

    Returns:
        tuple: (timestamp, geo_data)
        - timestamp: integer Unix timestamp from photoTakenTime, or None
        - geo_data: dict with latitude/longitude/altitude, or None
    """
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        timestamp = None
        geo_data = None

        # Extract photoTakenTime as raw timestamp
        if 'photoTakenTime' in data and 'timestamp' in data['photoTakenTime']:
            try:
                timestamp = int(data['photoTakenTime']['timestamp'])
            except (ValueError, OSError):
                pass

        # Extract geoData (only if coordinates are non-zero)
        if 'geoData' in data:
            geo = data['geoData']
            lat = geo.get('latitude', 0)
            lon = geo.get('longitude', 0)

            if lat != 0 or lon != 0:
                geo_data = {
                    'latitude': lat,
                    'longitude': lon,
                    'altitude': geo.get('altitude', 0)
                }

        return timestamp, geo_data

    except (json.JSONDecodeError, IOError) as e:
        print(f"    Warning: Could not parse JSON {json_path.name}: {e}")
        return None, None


# ============================================================================
# EXIF METADATA APPLICATION
# ============================================================================

def apply_exif_metadata(file_path, timestamp=None, geo_data=None, quiet=True):
    """
    Apply EXIF metadata to a media file using exiftool.

    This is the simpler version for post-processing scripts that only need
    to apply timestamp and GPS data.

    Args:
        file_path: Path to the media file
        timestamp: Unix timestamp (int) to set as DateTimeOriginal/CreateDate
        geo_data: dict with latitude/longitude/altitude from JSON geoData
        quiet: If True, suppress exiftool output (default: True)

    Returns:
        bool: True if successful, False otherwise
    """
    if not timestamp and not geo_data:
        return True  # Nothing to do, but not a failure

    args = ['exiftool', '-overwrite_original']

    if quiet:
        args.append('-q')

    if timestamp:
        dt = datetime.fromtimestamp(timestamp)
        exif_date = dt.strftime("%Y:%m:%d %H:%M:%S")
        args.extend([
            f'-DateTimeOriginal={exif_date}',
            f'-CreateDate={exif_date}',
            f'-FileCreateDate={exif_date}',
            f'-ModifyDate={exif_date}',
            f'-FileModifyDate={exif_date}',
        ])

    if geo_data:
        lat = geo_data['latitude']
        lon = geo_data['longitude']
        lat_ref = 'N' if lat >= 0 else 'S'
        lon_ref = 'E' if lon >= 0 else 'W'
        args.extend([
            f'-GPSLatitude={abs(lat)}',
            f'-GPSLatitudeRef={lat_ref}',
            f'-GPSLongitude={abs(lon)}',
            f'-GPSLongitudeRef={lon_ref}',
        ])

        if 'altitude' in geo_data and geo_data['altitude']:
            args.append(f'-GPSAltitude={geo_data["altitude"]}')

    args.append(str(file_path))

    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        return result.returncode == 0
    except Exception as e:
        print(f"    Warning: exiftool failed: {e}")
        return False


# ============================================================================
# FILENAME UTILITIES
# ============================================================================

def extract_media_filename(json_path):
    """
    Extract the original media filename from a JSON metadata filename.

    Handles various Google Takeout patterns:
    - filename.jpg.json
    - filename.jpg.supplemental-metadata.json
    - filename.jpg.supplemental-.json (truncated)
    - filename(1).jpg.json (duplicate indicator)

    Args:
        json_path: Path to the JSON file

    Returns:
        str: The media filename (e.g., "filename.jpg"), or None if invalid
    """
    import re

    json_name = json_path.name if isinstance(json_path, Path) else Path(json_path).name

    # Skip folder metadata.json files
    if json_name == 'metadata.json':
        return None

    if not json_name.endswith('.json'):
        return None

    base = json_name[:-5]  # Remove .json

    # Remove (1), (2), etc. duplicate suffixes on the JSON itself
    base = re.sub(r'\(\d+\)$', '', base)

    # Remove any truncated supplemental-metadata suffix
    base = strip_json_suffix(base)

    # Clean up trailing dots
    while base.endswith('.'):
        base = base[:-1]

    return base if base else None


def get_metadata_path(media_file):
    """
    Find the supplemental metadata JSON file for a media file.

    Searches in the same directory for:
    1. Exact match: filename.jpg.json
    2. Wildcard: filename.jpg.*.json (handles truncation)

    Args:
        media_file: Path to the media file

    Returns:
        Path to the JSON file if found, None otherwise
    """
    if isinstance(media_file, str):
        media_file = Path(media_file)

    base_name = media_file.name
    directory = media_file.parent

    # Try exact match first
    exact_match = directory / f"{base_name}.json"

    if exact_match.exists():
        return exact_match

    # Use wildcard to match any JSON with the media filename as prefix
    # This handles all truncation variations
    matches = list(directory.glob(f"{base_name}.*.json"))

    if matches:
        return matches[0]

    return None
