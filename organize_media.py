#!/usr/bin/env python3
"""
Google Takeout Photo Organization Script
- Organizes photos/videos into year/month structure based on metadata
- Preserves special project folders as intact directories
- Flags photos with conflicting photoTakenTime vs creationTime
"""

import argparse
import mimetypes
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from build_file_index import build_file_index
from media_utils import (
    MEDIA_EXTENSIONS,
    MONTH_NAMES,
    PHOTO_EXTENSIONS,
    VIDEO_EXTENSIONS,
    dates_match,
    get_metadata_path,
    parse_json_metadata,
)

# Base directory containing all Takeout folders
SCRIPT_DIR = Path(__file__).parent
BASE_DIR = None  # Will be set from command line args
OUTPUT_DIR = SCRIPT_DIR / "Organized_Photos"
VIDEO_OUTPUT_DIR = SCRIPT_DIR / "Organized_Videos"
REVIEW_DIR = OUTPUT_DIR / "_TO_REVIEW_"
GOOGLE_PHOTOS_DIR = "Google Photos"

# Directories to skip (only Trash - Public will be sorted normally)
SKIP_DIRS = {'Trash'}

# Person name for tagging (set via command line)
PERSON_NAME = None

# Dict to track files in project folders: {filename: project_folder_path}
# Used to avoid duplicates and to place -edited variants with originals
PROJECT_FILES = {}

# Standard Google Photos folders (these should be processed normally)
STANDARD_FOLDER_PATTERN = re.compile(r'^Photos from \d{4}$')

# Untitled folders should be processed normally too
UNTITLED_PATTERN = re.compile(r'^Untitled.*')


def is_standard_folder(folder_name):
    """Check if a folder is a standard Google Photos folder that should be processed normally"""
    if STANDARD_FOLDER_PATTERN.match(folder_name):
        return True
    if UNTITLED_PATTERN.match(folder_name):
        return True
    return False


def is_project_folder(folder_name):
    """Check if a folder is a project folder that should be preserved.
    Any folder that is not a standard folder and not a skip directory is considered a project folder.
    """
    if is_standard_folder(folder_name):
        return False
    if folder_name in SKIP_DIRS:
        return False
    return True


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class FileDestination:
    """
    Result of analyzing a media file to determine its destination.

    Consolidates the 10 separate return values from determine_destination()
    into a single, self-documenting object.
    """
    year: Optional[int] = None
    month: Optional[int] = None
    metadata_path: Optional[Path] = None
    needs_review: bool = False
    reason: str = ""
    create_date: Optional[datetime] = None
    modify_date: Optional[datetime] = None
    geo_data: Optional[dict] = None
    used_filename_date: bool = False
    inferred_year: Optional[int] = None

    @property
    def has_valid_date(self):
        """Check if we have a valid year/month for organization."""
        return self.year is not None and self.month is not None

    @property
    def needs_exif_write(self):
        """Check if we need to write date to EXIF (not already from filename/EXIF)."""
        return not self.used_filename_date and self.create_date is not None


# ============================================================================
# FILE TYPE DETECTION AND EXTENSION CORRECTION
# ============================================================================

# Mapping of file magic bytes to correct extension
# Format: (magic_bytes, offset, correct_extension)
FILE_SIGNATURES = [
    (b'RIFF', 0, None),  # RIFF container - need to check subtype
    (b'WEBP', 8, '.webp'),  # WebP (RIFF subtype at offset 8)
    (b'\xff\xd8\xff', 0, '.jpg'),  # JPEG
    (b'\x89PNG\r\n\x1a\n', 0, '.png'),  # PNG
    (b'GIF87a', 0, '.gif'),  # GIF87a
    (b'GIF89a', 0, '.gif'),  # GIF89a
    (b'\x00\x00\x00', 0, None),  # Could be MP4/MOV - check ftyp
    (b'ftyp', 4, '.mp4'),  # MP4/MOV (ftyp at offset 4)
]


def detect_actual_file_type(file_path):
    """
    Detect actual file type by reading magic bytes, not trusting extension.

    Returns the correct extension (e.g., '.webp', '.jpg') or None if unknown.
    """
    try:
        with open(file_path, 'rb') as f:
            header = f.read(16)

        if len(header) < 12:
            return None

        # Check for RIFF container (WebP uses RIFF)
        if header[0:4] == b'RIFF' and header[8:12] == b'WEBP':
            return '.webp'

        # Check for JPEG
        if header[0:3] == b'\xff\xd8\xff':
            return '.jpg'

        # Check for PNG
        if header[0:8] == b'\x89PNG\r\n\x1a\n':
            return '.png'

        # Check for GIF
        if header[0:6] in (b'GIF87a', b'GIF89a'):
            return '.gif'

        # Check for HEIC/HEIF (ftyp box with heic/mif1/etc brand)
        if header[4:8] == b'ftyp':
            brand = header[8:12]
            if brand in (b'heic', b'heix', b'mif1', b'msf1'):
                return '.heic'
            # Otherwise likely MP4/MOV
            return '.mp4'

        return None
    except Exception:
        return None


def fix_file_extension_if_needed(file_path):
    """
    Check if file extension matches actual file type, rename if needed.

    Returns:
        Path: The (possibly renamed) file path
        bool: True if file was renamed, False otherwise
    """
    file_path = Path(file_path)
    current_ext = file_path.suffix.lower()
    actual_ext = detect_actual_file_type(file_path)

    if actual_ext is None:
        return file_path, False

    # Normalize extensions for comparison
    ext_equivalents = {
        '.jpeg': '.jpg',
        '.jpe': '.jpg',
    }
    normalized_current = ext_equivalents.get(current_ext, current_ext)
    normalized_actual = ext_equivalents.get(actual_ext, actual_ext)

    if normalized_current == normalized_actual:
        return file_path, False

    # Extension mismatch - rename the file
    new_path = file_path.with_suffix(actual_ext)

    # Handle collision
    if new_path.exists():
        counter = 1
        stem = file_path.stem
        while new_path.exists():
            new_path = file_path.parent / f"{stem}_{counter}{actual_ext}"
            counter += 1

    try:
        file_path.rename(new_path)
        print(f"    Fixed extension: {file_path.name} -> {new_path.name}")
        return new_path, True
    except Exception as e:
        print(f"    Warning: Could not rename {file_path.name}: {e}")
        return file_path, False


# ============================================================================
# WALLPAPER/BACKGROUND DETECTION
# ============================================================================

def is_wallpaper_filename(filename):
    """
    Detect if a filename matches common wallpaper/background naming patterns.

    These files typically have no meaningful date metadata and should be
    separated from personal life photos.

    Patterns detected:
    - Resolution prefix: "1920x1080 Name.jpg", "2560x1440-Name.jpg"
    - Shorthand resolution: "4k Name.jpg", "2k Name.jpg", "8k Name.jpg"
    - Ultrawide prefix: "Ultrawide Name.jpg" (and typo "Untrawide")

    Returns True if filename matches a wallpaper pattern.
    """
    name = filename.stem if hasattr(filename, 'stem') else str(filename)

    # Pattern 1: Resolution prefix like "1920x1080 " or "2560x1440-"
    # Matches: "1920x1080 Star Wars.jpg", "2800x1200-Legend.jpg"
    if re.match(r'^\d{3,4}x\d{3,4}[\s_-]', name):
        return True

    # Pattern 2: Shorthand resolution like "4k " or "8k "
    # Matches: "4k Star Wars.jpg", "2k Nature.jpg", "8k Hitman.jpg"
    if re.match(r'^[248][kK][\s_-]', name):
        return True

    # Pattern 3: Ultrawide prefix (including typo "Untrawide")
    # Matches: "Ultrawide Star Wars.jpg", "Untrawide Dragon.jpg"
    if re.match(r'^[Uu](?:ltra|ntra)[Ww]ide[\s_-]', name):
        return True

    return False


# ============================================================================
# DATE EXTRACTION
# ============================================================================

# Note: get_metadata_path is imported from media_utils
# Note: parse_json_metadata is imported from media_utils (replaces local parse_metadata)


def get_date_from_filename(filename):
    """
    Try to extract date and time from various filename patterns.

    Supported patterns (in priority order):
    1. YYYYMMDD_HHMMSS - 8 digits, separator, 6+ digits (IMG_20200927_123456)
    2. YYYY-MM-DD-HH-MM-SS - ISO-ish with hyphens (Screenshot_2017-01-26-13-52-51)
    3. YYYYMMDD - 8 consecutive digits (20200927)
    4. YYYY-MM-DD - ISO date with hyphens (2017-01-26_something)
    5. YYYY-MM_ or YYYY-MM- - Year-month only at start (2010-03_Jacen_Announcement)

    Returns datetime object or None if no valid date found.
    """
    name = filename.stem

    # Pattern 1: YYYYMMDD_HHMMSS (14+ digits with separator)
    # Matches: IMG_20200927_123456, VID_20240504_113916789
    datetime_match = re.search(r'(\d{8})[_-](\d{6,})', name)
    if datetime_match:
        date_part = datetime_match.group(1)
        time_part = datetime_match.group(2)[:6]
        try:
            year = int(date_part[0:4])
            month = int(date_part[4:6])
            day = int(date_part[6:8])
            hour = int(time_part[0:2])
            minute = int(time_part[2:4])
            second = int(time_part[4:6])
            if (1990 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31 and
                0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
                return datetime(year, month, day, hour, minute, second)
        except ValueError:
            pass

    # Pattern 2: YYYY-MM-DD-HH-MM-SS with hyphens throughout
    # Matches: Screenshot_2017-01-26-13-52-51
    hyphen_datetime_match = re.search(r'(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})', name)
    if hyphen_datetime_match:
        try:
            year = int(hyphen_datetime_match.group(1))
            month = int(hyphen_datetime_match.group(2))
            day = int(hyphen_datetime_match.group(3))
            hour = int(hyphen_datetime_match.group(4))
            minute = int(hyphen_datetime_match.group(5))
            second = int(hyphen_datetime_match.group(6))
            if (1990 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31 and
                0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
                return datetime(year, month, day, hour, minute, second)
        except ValueError:
            pass

    # Pattern 3: 8 consecutive digits (YYYYMMDD)
    date_match = re.search(r'(\d{8})', name)
    if date_match:
        date_part = date_match.group(1)
        try:
            year = int(date_part[0:4])
            month = int(date_part[4:6])
            day = int(date_part[6:8])
            if 1990 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
                return datetime(year, month, day)
        except ValueError:
            pass

    # Pattern 4: YYYY-MM-DD with hyphens (ISO date)
    # Matches: 2017-01-26_photo, photo_2017-01-26
    iso_date_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', name)
    if iso_date_match:
        try:
            year = int(iso_date_match.group(1))
            month = int(iso_date_match.group(2))
            day = int(iso_date_match.group(3))
            if 1990 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
                return datetime(year, month, day)
        except ValueError:
            pass

    # Pattern 5: YYYY-MM at start of filename (year-month only, use day 1)
    # Matches: 2010-03_Jacen_Announcement, 2015-12-Christmas
    # Must be at start or after underscore/hyphen to avoid false positives
    year_month_match = re.match(r'^(\d{4})-(\d{2})[_-]', name)
    if year_month_match:
        try:
            year = int(year_month_match.group(1))
            month = int(year_month_match.group(2))
            if 1990 <= year <= 2100 and 1 <= month <= 12:
                return datetime(year, month, 1)
        except ValueError:
            pass

    return None


def get_exif_date(media_file):
    """
    Read existing EXIF dates from a media file using exiftool.
    Returns a datetime if a valid date is found that is more than one month in the past,
    otherwise returns None.

    Checks DateTimeOriginal and CreateDate EXIF fields. These are the standard fields
    for when a photo was actually taken.
    """
    try:
        result = subprocess.run(
            ['exiftool', '-DateTimeOriginal', '-CreateDate', '-s', '-s', '-s', str(media_file)],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            return None

        # Output will have up to two lines: DateTimeOriginal and CreateDate
        lines = result.stdout.strip().split('\n')
        one_month_ago = datetime.now().replace(day=1)  # First of current month as threshold

        for line in lines:
            if not line.strip():
                continue

            # Parse EXIF date format: "YYYY:MM:DD HH:MM:SS"
            try:
                parsed_date = datetime.strptime(line.strip(), '%Y:%m:%d %H:%M:%S')

                # Only accept dates more than one month in the past
                # This filters out bogus default dates like 1970-01-01 or future dates
                if parsed_date < one_month_ago:
                    return parsed_date

            except ValueError:
                continue

        return None

    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


# Note: dates_match is imported from media_utils


def extract_year_from_path(file_path):
    """
    Extract year from the file's path components.
    Prioritizes "Photos from YYYY" patterns, then searches all path parts for 4-digit years.
    Returns the year as an integer, or None if no year found.
    """
    path_str = str(file_path)

    # First priority: "Photos from YYYY" pattern (Google Takeout standard)
    photos_from_match = re.search(r'Photos from (\d{4})', path_str, re.IGNORECASE)
    if photos_from_match:
        year = int(photos_from_match.group(1))
        if 1990 <= year <= 2100:
            return year

    # Second priority: Any 4-digit year in the path (excluding filename)
    # Split path and check each directory component
    parts = file_path.parts[:-1]  # Exclude filename
    for part in parts:
        # Look for standalone 4-digit numbers that could be years
        year_match = re.search(r'\b(\d{4})\b', part)
        if year_match:
            year = int(year_match.group(1))
            if 1990 <= year <= 2100:
                return year

    return None


def determine_destination(media_file):
    """
    Determine the year/month destination for a media file.

    Returns a FileDestination object containing all relevant info for organizing
    and writing metadata to the file.

    Priority order for date extraction (for performance, filename is checked first):
    1. Filename date pattern (YYYYMMDD) - fastest, no JSON I/O required
    2. JSON metadata (photoTakenTime/creationTime) - only parsed if filename has no date
    3. Existing EXIF data - last resort fallback
    """
    result = FileDestination()

    # Always look up metadata path so we can delete it after processing
    result.metadata_path = get_metadata_path(media_file)

    # First, try to extract date from filename (fastest - no JSON parsing required)
    filename_date = get_date_from_filename(media_file)

    if filename_date:
        # Filename date is authoritative when present - skip metadata parsing entirely
        result.year = filename_date.year
        result.month = filename_date.month
        result.create_date = filename_date
        result.used_filename_date = True
        return result

    # Filename didn't have a parseable date, so parse JSON metadata
    if result.metadata_path:
        photo_taken_date, creation_date, result.geo_data = parse_json_metadata(result.metadata_path)

        # Check if dates conflict (different year/month by 3+ months)
        if photo_taken_date and creation_date:
            if not dates_match(photo_taken_date, creation_date):
                # Use earlier date for organization, store both for EXIF
                if photo_taken_date < creation_date:
                    chosen_date = photo_taken_date
                    result.create_date = photo_taken_date
                    result.modify_date = creation_date
                else:
                    chosen_date = creation_date
                    result.create_date = creation_date
                    result.modify_date = photo_taken_date

                result.reason = f"Using earlier date: {result.create_date.strftime('%Y-%m-%d')} (later: {result.modify_date.strftime('%Y-%m-%d')})"
            else:
                # Dates match (within 3 months), use photoTakenTime
                chosen_date = photo_taken_date
                result.create_date = photo_taken_date
        elif photo_taken_date:
            chosen_date = photo_taken_date
            result.create_date = photo_taken_date
        elif creation_date:
            chosen_date = creation_date
            result.create_date = creation_date
        else:
            chosen_date = None

        if chosen_date:
            result.year = chosen_date.year
            result.month = chosen_date.month
            return result

    # If we still don't have a date, try reading existing EXIF as last resort
    exif_date = get_exif_date(media_file)

    if exif_date:
        result.year = exif_date.year
        result.month = exif_date.month
        result.create_date = exif_date
        result.used_filename_date = True  # EXIF already has date, no need to write
        result.reason = f"Using existing EXIF date: {exif_date.strftime('%Y-%m-%d')}"
        return result

    # No date found - mark for review
    result.needs_review = True
    result.inferred_year = extract_year_from_path(media_file)
    result.reason = "No date in metadata, filename, or EXIF"

    if result.inferred_year:
        result.reason += f" (inferred year {result.inferred_year} from path)"
        # Create January 1 date for EXIF writing
        result.create_date = datetime(result.inferred_year, 1, 1, 0, 0, 0)

    return result


def create_destination_path(year, month, output_base_dir=OUTPUT_DIR):
    """Create the destination directory path"""
    year_dir = output_base_dir / str(year)
    month_dir = year_dir / MONTH_NAMES[month - 1]
    month_dir.mkdir(parents=True, exist_ok=True)
    return month_dir


def move_file_safely(src, dst_dir, create_date=None, modify_date=None, file_index=None):
    """Move file to destination, handling name conflicts and adding person metadata

    Args:
        file_index: Optional dict mapping (base_name, ext, is_edited) -> list of file paths
                   for fast duplicate detection without filesystem operations
    """
    base = src.stem
    ext = src.suffix.lower()
    is_media = ext in MEDIA_EXTENSIONS

    # Determine if current file is an -edited variant (needed for index operations)
    is_edited = base.endswith('-edited') or any(base.endswith(f'-edited_{suffix}') for suffix in ['_' + PERSON_NAME] if PERSON_NAME)

    # Strip any existing person suffix from the base name (for both index and glob operations)
    base_without_suffix = base
    if PERSON_NAME and base.endswith(f"_{PERSON_NAME}"):
        base_without_suffix = base[:-len(PERSON_NAME)-1]
    else:
        # Try to detect other person suffixes (pattern: ends with _Name)
        match = re.match(r'^(.+)_([A-Z][a-z]+)$', base)
        if match:
            base_without_suffix = match.group(1)

    # Also strip -edited suffix if present for base comparison
    if base_without_suffix.endswith('-edited'):
        base_without_suffix = base_without_suffix[:-7]  # Remove '-edited'

    # For media files, check if file already exists with any person suffix (first person in wins)
    if is_media:

        # Check if any file with this base name already exists (with any suffix or no suffix)
        # BUT: originals and -edited variants are NOT duplicates of each other

        if file_index is not None:
            # Use index for fast lookup (no filesystem operations)
            # Index already separates originals from -edited variants
            index_key = (base_without_suffix, ext, is_edited)
            existing_files = file_index.get(index_key, [])

            # With index, files are already filtered by is_edited status
            if existing_files:
                # Delete the duplicate source file
                try:
                    src.unlink()
                except Exception:
                    pass  # Silently continue if deletion fails
                return False, None
        else:
            # Fall back to filesystem glob if no index provided
            existing_files = list(dst_dir.glob(f"{base_without_suffix}*{ext}"))

            # Filter to exclude -edited variants if checking original, and vice versa
            if existing_files:
                actual_duplicates = []
                for existing in existing_files:
                    existing_base = existing.stem
                    # Remove person suffix from existing file for comparison
                    if PERSON_NAME and existing_base.endswith(f"_{PERSON_NAME}"):
                        existing_base = existing_base[:-len(PERSON_NAME)-1]
                    else:
                        match = re.match(r'^(.+)_([A-Z][a-z]+)$', existing_base)
                        if match:
                            existing_base = match.group(1)

                    existing_is_edited = existing_base.endswith('-edited')

                    # Only consider it a duplicate if both are edited or both are not edited
                    if is_edited == existing_is_edited:
                        actual_duplicates.append(existing)

                if actual_duplicates:
                    # File already exists - delete this duplicate
                    try:
                        src.unlink()
                    except Exception:
                        pass  # Silently continue if deletion fails
                    return False, None

    # Rename source file first if person name is specified (only for media files)
    # Check if person name suffix doesn't already exist
    if PERSON_NAME and is_media:
        # Check if filename already ends with _PERSON_NAME
        if not base.endswith(f"_{PERSON_NAME}"):
            new_src_name = f"{base}_{PERSON_NAME}{src.suffix}"
            new_src = src.parent / new_src_name
            if not new_src.exists():
                src.rename(new_src)
            src = new_src

    # Determine destination filename
    dst = dst_dir / src.name

    # Handle name conflicts by appending a number
    if dst.exists():
        counter = 1
        while dst.exists():
            dst = dst_dir / f"{src.stem}_{counter}{src.suffix}"
            counter += 1

    try:
        shutil.move(str(src), str(dst))

        # Only perform EXIF operations on media files
        if is_media:
            # Combine all EXIF operations into a single exiftool call for performance
            apply_all_metadata(dst, create_date, modify_date)

            # Update file_index with newly moved file
            if file_index is not None:
                index_key = (base_without_suffix, ext, is_edited)
                if index_key not in file_index:
                    file_index[index_key] = []
                file_index[index_key].append(dst)

        return True, dst
    except Exception as e:
        print(f"  Error moving {src} to {dst}: {e}")
        return False, None


def rename_metadata_to_match_media(media_original_name, media_new_name, metadata_path):
    """Rename metadata file to match the renamed media file"""
    if not metadata_path or not metadata_path.exists():
        return metadata_path

    # Get the metadata file extension (e.g., .supplemental-metadata.json)
    metadata_suffix = metadata_path.name.replace(media_original_name, '')

    # Create new metadata filename
    new_metadata_name = media_new_name + metadata_suffix
    new_metadata_path = metadata_path.parent / new_metadata_name

    try:
        metadata_path.rename(new_metadata_path)
        return new_metadata_path
    except Exception as e:
        print(f"  Warning: Could not rename metadata file: {e}")
        return metadata_path


def apply_all_metadata(file_path, create_date=None, modify_date=None, geo_data=None):
    """
    Apply all EXIF metadata changes in a single exiftool call for maximum performance.

    If EXIF write fails due to file format issues, attempts to fix the file extension
    and retry the write operation.

    Args:
        file_path: Path to the media file
        create_date: datetime for DateTimeOriginal/CreateDate (from JSON metadata)
        modify_date: datetime for ModifyDate (when dates conflicted)
        geo_data: dict with latitude/longitude/altitude (from JSON geoData)

    Returns:
        Path: The (possibly renamed) file path
    """
    file_path = Path(file_path)

    def build_exiftool_cmd(target_path):
        """Build the exiftool command for the given target path."""
        cmd = ['exiftool', '-overwrite_original', '-q']

        # Add person name if specified
        if PERSON_NAME:
            cmd.append(f'-Artist={PERSON_NAME}')

        # Handle timestamps from JSON metadata
        if create_date:
            create_str = create_date.strftime('%Y:%m:%d %H:%M:%S')
            cmd.extend([
                f'-DateTimeOriginal={create_str}',
                f'-CreateDate={create_str}',
                f'-FileCreateDate={create_str}',
            ])

            if modify_date:
                # Conflicting dates - use later for modification
                modify_str = modify_date.strftime('%Y:%m:%d %H:%M:%S')
                cmd.extend([
                    f'-ModifyDate={modify_str}',
                    f'-FileModifyDate={modify_str}',
                ])
            else:
                # Same date for all
                cmd.extend([
                    f'-ModifyDate={create_str}',
                    f'-FileModifyDate={create_str}',
                ])
        else:
            # No date from JSON - restore timestamps from existing EXIF
            cmd.extend([
                '-FileModifyDate<DateTimeOriginal',
                '-FileCreateDate<DateTimeOriginal',
            ])

        # Add GPS coordinates if available
        if geo_data:
            lat = geo_data.get('latitude')
            lon = geo_data.get('longitude')
            alt = geo_data.get('altitude', 0)

            if lat is not None and lon is not None:
                # Only write if coordinates are meaningful (not 0,0)
                if abs(lat) > 0.0001 or abs(lon) > 0.0001:
                    cmd.extend([
                        f'-GPSLatitude={lat}',
                        f'-GPSLongitude={lon}',
                    ])
                    if alt and alt != 0:
                        cmd.append(f'-GPSAltitude={alt}')

        cmd.append(str(target_path))
        return cmd

    try:
        cmd = build_exiftool_cmd(file_path)
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        # Check for format-related errors that might be fixed by correcting extension
        if result.returncode != 0:
            error_output = (result.stderr or '') + (result.stdout or '')
            format_errors = ['RIFF format error', 'Error reading RIFF', 'Not a valid']

            if any(err in error_output for err in format_errors):
                # Try fixing the file extension
                new_path, was_renamed = fix_file_extension_if_needed(file_path)

                if was_renamed:
                    # Retry with corrected extension
                    cmd = build_exiftool_cmd(new_path)
                    retry_result = subprocess.run(cmd, capture_output=True, text=True, check=False)

                    if retry_result.returncode != 0:
                        # Still failed - some files just don't support EXIF
                        pass

                    return new_path

        return file_path
    except Exception:
        return file_path


def extract_year_from_folder_name(folder_name):
    """Try to extract a 4-digit year from folder name"""
    match = re.search(r'\b(19\d{2}|20\d{2})\b', folder_name)
    if match:
        return int(match.group(1))
    return None


def determine_project_folder_month(project_path):
    """
    Determine the month prefix for a project folder by examining its contents.
    Returns the most common month, or None if can't determine.
    """
    months = []

    for root, dirs, files in os.walk(project_path):
        for filename in files:
            file_path = Path(root) / filename
            ext = file_path.suffix.lower()

            if ext in MEDIA_EXTENSIONS:
                dest = determine_destination(file_path)
                if dest.month and not dest.needs_review:
                    months.append(dest.month)

    if months:
        # Return the most common month
        month_counts = defaultdict(int)
        for m in months:
            month_counts[m] += 1
        return max(month_counts.items(), key=lambda x: x[1])[0]

    return None


def collect_project_media_files(project_path, dest_project_path):
    """Collect all media filenames in a project folder and map to destination path"""
    media_files = {}
    for root, dirs, files in os.walk(project_path):
        for filename in files:
            file_path = Path(root) / filename
            if file_path.suffix.lower() in MEDIA_EXTENSIONS:
                media_files[filename] = dest_project_path
    return media_files


def process_project_folder(project_path, source_folder):
    """
    Move an entire project folder to the appropriate year directory.
    If a folder with the same base name already exists (from another Takeout archive),
    merge the contents instead of creating duplicates.
    Returns dict of media filenames -> project folder path.
    """
    folder_name = project_path.name
    print(f"\nProcessing project folder: {source_folder}/{folder_name}")

    # First, check if this folder contains any media files at all
    # If not, leave it in place (likely just metadata JSON files)
    has_media = False
    for root, dirs, files in os.walk(project_path):
        for filename in files:
            ext = Path(filename).suffix.lower()
            if ext in MEDIA_EXTENSIONS:
                has_media = True
                break
        if has_media:
            break

    if not has_media:
        print("  Skipping: No media files found (leaving in source directory)")
        return {}

    # Try to determine year from folder name
    year = extract_year_from_folder_name(folder_name)

    # If no year in name, try to determine from contents
    if not year:
        for root, dirs, files in os.walk(project_path):
            for filename in files:
                file_path = Path(root) / filename
                ext = file_path.suffix.lower()

                if ext in MEDIA_EXTENSIONS:
                    dest = determine_destination(file_path)
                    if dest.year and not dest.needs_review:
                        year = dest.year
                        break
            if year:
                break

    if not year:
        # Can't determine year - move entire folder to review
        print(f"  Warning: Could not determine year for {folder_name}, moving to _TO_REVIEW_")
        REVIEW_DIR.mkdir(parents=True, exist_ok=True)

        # Check if folder already exists in review
        dest_path = REVIEW_DIR / folder_name

        # Collect media files with destination path
        media_files = collect_project_media_files(project_path, dest_path)

        if dest_path.exists():
            # Merge with existing folder in review
            try:
                for item in project_path.iterdir():
                    dest_item = dest_path / item.name
                    if dest_item.exists():
                        # Handle conflicts by adding suffix
                        base = dest_item.stem if dest_item.is_file() else dest_item.name
                        ext = dest_item.suffix if dest_item.is_file() else ""
                        counter = 1
                        while dest_item.exists():
                            if dest_item.is_file():
                                dest_item = dest_path / f"{base}_{counter}{ext}"
                            else:
                                dest_item = dest_path / f"{base}_{counter}"
                            counter += 1
                    shutil.move(str(item), str(dest_item))
                project_path.rmdir()
            except Exception as e:
                print(f"  Error moving folder to review: {e}")
                return media_files
        else:
            # Move entire folder to review
            try:
                shutil.move(str(project_path), str(dest_path))
            except Exception as e:
                print(f"  Error moving folder to review: {e}")
                return media_files
        return media_files

    # Create destination year directory
    year_dir = OUTPUT_DIR / str(year)
    year_dir.mkdir(parents=True, exist_ok=True)

    # Check if a folder with this base name already exists (with any month prefix)
    existing_folder = None
    for existing in year_dir.iterdir():
        if existing.is_dir():
            # Remove month prefix if present (format: "NN FolderName")
            existing_name = existing.name
            if existing_name[:2].isdigit() and existing_name[2:3] == ' ':
                existing_base = existing_name[3:]
            else:
                existing_base = existing_name

            if existing_base == folder_name:
                existing_folder = existing
                break

    # Collect media files based on destination
    if existing_folder:
        dest_path = existing_folder
    else:
        month = determine_project_folder_month(project_path)
        if month:
            dest_folder_name = f"{month:02d} {folder_name}"
        else:
            dest_folder_name = folder_name
        dest_path = year_dir / dest_folder_name

    media_files = collect_project_media_files(project_path, dest_path)

    if existing_folder:
        # Merge contents into existing folder
        print(f"  Merging {source_folder}/{folder_name} into existing folder: {existing_folder.name}")
        try:
            for item in project_path.iterdir():
                dest_item = existing_folder / item.name
                if dest_item.exists():
                    # Handle conflicts by adding suffix
                    base = dest_item.stem if dest_item.is_file() else dest_item.name
                    ext = dest_item.suffix if dest_item.is_file() else ""
                    counter = 1
                    while dest_item.exists():
                        if dest_item.is_file():
                            dest_item = existing_folder / f"{base}_{counter}{ext}"
                        else:
                            dest_item = existing_folder / f"{base}_{counter}"
                        counter += 1
                shutil.move(str(item), str(dest_item))
            # Remove the now-empty source folder
            project_path.rmdir()
            return media_files
        except Exception as e:
            print(f"  Error merging folder {project_path}: {e}")
            return media_files
    else:
        # No existing folder, move it
        try:
            shutil.move(str(project_path), str(dest_path))
            print(f"  Moved folder: {source_folder}/{folder_name} -> {year}/{dest_path.name}")
            return media_files
        except Exception as e:
            print(f"  Error moving folder {source_folder}/{folder_name}: {e}")
            return media_files


def process_regular_files(takeout_path, file_index=None):
    """Process regular photo files (not in project folders)

    Args:
        takeout_path: Path to the Takeout directory to process
        file_index: Optional dict for fast duplicate detection
    """
    # Check if this is the _TO_REVIEW_ directory (no Google Photos subdirectory)
    if "_TO_REVIEW_" in str(takeout_path):
        photos_dir = takeout_path
        print(f"\nProcessing files from _TO_REVIEW_: {takeout_path}")
    else:
        photos_dir = takeout_path / GOOGLE_PHOTOS_DIR
        if not photos_dir.exists():
            print(f"Skipping {takeout_path}: No '{GOOGLE_PHOTOS_DIR}' directory found")
            return
        print(f"\nProcessing regular files from: {takeout_path}")

    stats = {
        'media_files': 0,
        'moved': 0,
        'failed': 0,
        'review': 0,
        'duplicates_deleted': 0,
        'skipped_existing': 0
    }

    # Walk through all subdirectories
    for root, dirs, files in os.walk(photos_dir):
        root_path = Path(root)

        # Skip trash directories
        if any(skip in root_path.parts for skip in SKIP_DIRS):
            continue

        # Skip if this is a project folder
        relative_to_photos = root_path.relative_to(photos_dir)
        if len(relative_to_photos.parts) > 0:
            top_level_folder = relative_to_photos.parts[0]
            if is_project_folder(top_level_folder):
                continue

        for filename in files:
            file_path = root_path / filename
            ext = file_path.suffix.lower()

            # Process media files
            if ext in MEDIA_EXTENSIONS:
                stats['media_files'] += 1

                # Check if this file already exists in a project folder
                if filename in PROJECT_FILES:
                    # Delete duplicate from regular directory
                    try:
                        file_path.unlink()
                        stats['duplicates_deleted'] += 1
                        # Also delete associated metadata if it exists
                        metadata_path = get_metadata_path(file_path)
                        if metadata_path and metadata_path.exists():
                            metadata_path.unlink()
                    except Exception as e:
                        print(f"  Warning: Could not delete duplicate {filename}: {e}")
                    continue

                # Check if this is an -edited variant of a project file
                if filename.endswith(('-edited.jpg', '-edited.jpeg', '-edited.png', '-edited.heic',
                                      '-edited.mp4', '-edited.mov', '-edited.avi')):
                    # Extract base name (remove -edited suffix)
                    name_parts = filename.rsplit('-edited.', 1)
                    if len(name_parts) == 2:
                        base_filename = name_parts[0] + '.' + name_parts[1]
                        if base_filename in PROJECT_FILES:
                            # Move this edited file into the project folder with original
                            project_folder = PROJECT_FILES[base_filename]
                            try:
                                # Apply EXIF metadata BEFORE moving (project was already processed)
                                metadata_path = get_metadata_path(file_path)
                                if metadata_path and metadata_path.exists():
                                    photo_taken, _, geo_data = parse_json_metadata(metadata_path)
                                    # photo_taken is already a datetime object from parse_metadata
                                    if photo_taken or geo_data:
                                        apply_all_metadata(file_path, photo_taken, None, geo_data)
                                    # Delete JSON after applying metadata
                                    metadata_path.unlink()

                                dest = project_folder / filename
                                if dest.exists():
                                    # Handle conflicts
                                    counter = 1
                                    while dest.exists():
                                        dest = project_folder / f"{file_path.stem}_{counter}{ext}"
                                        counter += 1
                                shutil.move(str(file_path), str(dest))
                                stats['moved'] += 1
                                print(f"  Moved edited variant: {filename} -> {project_folder.name}/")
                            except Exception as e:
                                print(f"  Warning: Could not move edited variant {filename}: {e}")
                            continue

                # Call determine_destination to get file info
                dest = determine_destination(file_path)

                # Get source folder relative to Google Photos (or _TO_REVIEW_)
                try:
                    if "_TO_REVIEW_" in str(photos_dir):
                        source_folder = "_TO_REVIEW_"
                    else:
                        source_folder = file_path.relative_to(photos_dir).parts[0] if len(file_path.relative_to(photos_dir).parts) > 0 else "root"
                except (ValueError, IndexError):
                    source_folder = "unknown"

                # Check for wallpaper/background files first - route to separate folder
                if is_wallpaper_filename(file_path):
                    wallpapers_dir = REVIEW_DIR / "Wallpapers"
                    wallpapers_dir.mkdir(parents=True, exist_ok=True)

                    success, _ = move_file_safely(file_path, wallpapers_dir, file_index=file_index)
                    if success:
                        stats['review'] += 1
                        print(f"  Moved wallpaper: {source_folder}/{file_path.name}")

                        # Delete metadata if it exists (no need for wallpapers)
                        if dest.metadata_path and dest.metadata_path.exists():
                            dest.metadata_path.unlink()
                    continue

                if dest.needs_review:
                    # Create year-based subdirectory in review if we have an inferred year
                    if dest.inferred_year:
                        review_dest_dir = REVIEW_DIR / str(dest.inferred_year)
                    else:
                        review_dest_dir = REVIEW_DIR

                    review_dest_dir.mkdir(parents=True, exist_ok=True)

                    # Write EXIF date if we inferred a year (Jan 1 of that year)
                    if dest.create_date:
                        apply_all_metadata(file_path, dest.create_date, None, None)

                    success, _ = move_file_safely(file_path, review_dest_dir, file_index=file_index)
                    if success:
                        stats['review'] += 1
                        print(f"  Review: {source_folder}/{file_path.name} ({dest.reason})")

                        # Move metadata too (we need it to figure out the date later)
                        if dest.metadata_path and dest.metadata_path.exists():
                            move_file_safely(dest.metadata_path, review_dest_dir, file_index=file_index)

                elif dest.year and dest.month:
                    # Determine if this is a photo or video
                    is_video = ext in VIDEO_EXTENSIONS
                    output_base = VIDEO_OUTPUT_DIR if is_video else OUTPUT_DIR

                    # Create destination directory
                    dest_dir = create_destination_path(dest.year, dest.month, output_base)

                    # Store original filename before moving
                    original_filename = file_path.name

                    # Write EXIF metadata BEFORE moving if we have date or geo data
                    # This includes dates from JSON, filename, or existing EXIF
                    if dest.create_date or dest.geo_data:
                        apply_all_metadata(file_path, dest.create_date, dest.modify_date, dest.geo_data)

                    # Move media file
                    success, moved_file = move_file_safely(file_path, dest_dir, dest.create_date, dest.modify_date, file_index)
                    if success:
                        stats['moved'] += 1
                        media_type = "video" if is_video else "photo"
                        if dest.reason:
                            print(f"  Moved {media_type}: {source_folder}/{original_filename} -> {dest.year}/{MONTH_NAMES[dest.month-1]} ({dest.reason})")
                        else:
                            print(f"  Moved {media_type}: {source_folder}/{original_filename} -> {dest.year}/{MONTH_NAMES[dest.month-1]}")

                        # Always delete JSON after successful move (metadata already applied to EXIF if available)
                        if dest.metadata_path and dest.metadata_path.exists():
                            dest.metadata_path.unlink()
                    elif success is False and moved_file is None:
                        # File already exists from another person's import - skip it
                        stats['skipped_existing'] += 1
                        print(f"  Skipped (exists): {source_folder}/{original_filename}")
                        # Also delete the metadata file if it exists
                        if dest.metadata_path and dest.metadata_path.exists():
                            dest.metadata_path.unlink()
                    else:
                        stats['failed'] += 1
                else:
                    print(f"  Warning: Could not determine date for {source_folder}/{file_path.name}")
                    stats['failed'] += 1

    print(f"\nStats for {takeout_path.name}:")
    print(f"  Media files found: {stats['media_files']}")
    print(f"  Successfully moved: {stats['moved']}")
    print(f"  Sent to review: {stats['review']}")
    print(f"  Duplicates deleted: {stats['duplicates_deleted']}")
    print(f"  Skipped (already exists): {stats['skipped_existing']}")
    print(f"  Failed: {stats['failed']}")

    return stats


def merge_project_metadata(project_path):
    """Merge JSON metadata for all files in a project folder before moving it"""
    print(f"  Merging metadata for project folder: {project_path.name}")

    # Import here to avoid circular dependency
    script_dir = Path(__file__).parent
    merge_script = script_dir / "merge_metadata.py"

    try:
        result = subprocess.run(
            [sys.executable, str(merge_script), str(project_path), "--recursive", "--remove-json"],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0:
            return True
        else:
            print(f"  Warning: Could not merge metadata for {project_path.name}: {result.stderr}")
            return False
    except Exception as e:
        print(f"  Warning: Error merging metadata for {project_path.name}: {e}")
        return False


def process_project_folders(takeout_path):
    """Find project folders, merge their metadata, then move them"""
    global PROJECT_FILES
    photos_dir = takeout_path / GOOGLE_PHOTOS_DIR

    if not photos_dir.exists():
        return

    print(f"\nProcessing project folders from: {takeout_path}")

    # Look for project folders at the top level of Google Photos
    for item in photos_dir.iterdir():
        if item.is_dir() and is_project_folder(item.name):
            # First, merge metadata for this project folder while it's still in place
            merge_project_metadata(item)

            # Then move the folder with merged metadata
            source_folder = item.name
            media_files_dict = process_project_folder(item, source_folder)
            PROJECT_FILES.update(media_files_dict)


def find_google_photos_dirs(base_dir):
    """
    Find all directories containing a 'Google Photos' subdirectory.
    Returns list of (parent_path, label) tuples for processing.
    """
    results = []

    for item in base_dir.iterdir():
        if item.is_dir():
            google_photos_path = item / GOOGLE_PHOTOS_DIR
            if google_photos_path.exists() and google_photos_path.is_dir():
                results.append((item, item.name))

    return results


def cleanup_empty_directories():
    """Remove empty directories and directories with only metadata files"""
    print("\n\nCleaning up empty directories...")

    for takeout_path, _ in find_google_photos_dirs(BASE_DIR):
        photos_dir = takeout_path / GOOGLE_PHOTOS_DIR

        if not photos_dir.exists():
            continue

        # Walk bottom-up to handle nested empty directories
        for root, dirs, files in os.walk(photos_dir, topdown=False):
            root_path = Path(root)

            # Skip the root Google Photos directory
            if root_path == photos_dir:
                continue

            try:
                # Check if directory is empty or contains only metadata/json files
                all_files = list(root_path.iterdir())

                if not all_files:
                    # Completely empty
                    print(f"  Removing empty directory: {root_path.name}")
                    root_path.rmdir()
                else:
                    # Check if only metadata files remain
                    has_media = any(
                        f.is_file() and f.suffix.lower() in MEDIA_EXTENSIONS
                        for f in all_files
                    )

                    if not has_media:
                        # Only metadata or other files, remove them and the directory
                        print(f"  Removing directory with no media: {root_path.name}")
                        for item in all_files:
                            if item.is_file():
                                item.unlink()
                            elif item.is_dir():
                                shutil.rmtree(item)
                        root_path.rmdir()
            except Exception as e:
                print(f"  Warning: Could not remove {root_path}: {e}")


def archive_trash_directories():
    """Move Trash directories to _TO_REVIEW_ for final review"""
    print("\n\nMoving Trash directories to _TO_REVIEW_ for final review...")

    trash_archive_dir = REVIEW_DIR / "Trash_Archives"
    trash_archive_dir.mkdir(parents=True, exist_ok=True)

    for takeout_path, source_label in find_google_photos_dirs(BASE_DIR):
        photos_dir = takeout_path / GOOGLE_PHOTOS_DIR

        if not photos_dir.exists():
            continue

        for skip_dir in SKIP_DIRS:
            target_dir = photos_dir / skip_dir
            if target_dir.exists():
                try:
                    dest_dir = trash_archive_dir / skip_dir
                    dest_dir.mkdir(parents=True, exist_ok=True)

                    # Move contents to combined directory
                    for item in target_dir.iterdir():
                        dest_item = dest_dir / item.name
                        if dest_item.exists():
                            # Handle duplicates with numbering
                            counter = 1
                            stem = item.stem
                            suffix = item.suffix
                            while dest_item.exists():
                                if item.is_file():
                                    dest_item = dest_dir / f"{stem}_{counter}{suffix}"
                                else:
                                    dest_item = dest_dir / f"{stem}_{counter}"
                                counter += 1
                        shutil.move(str(item), str(dest_item))

                    # Remove now-empty source directory
                    target_dir.rmdir()
                    print(f"  Archived: {source_label}/{skip_dir} -> Trash_Archives/{skip_dir}")
                except Exception as e:
                    print(f"  Error archiving {target_dir}: {e}")


def main():
    """Main execution function"""
    global PERSON_NAME, BASE_DIR, PROJECT_FILES

    # Reset project files dict for clean run
    PROJECT_FILES = {}

    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description='Organize Google Takeout photos and videos by date',
        epilog='Example: python3 organize_media.py --person "John Doe"'
    )
    parser.add_argument(
        '--person',
        type=str,
        help='Name of the person whose photos are being imported (for metadata tagging and conflict resolution)'
    )
    parser.add_argument(
        '--input-dir',
        type=str,
        default='TO_PROCESS',
        help='Input directory to process (default: TO_PROCESS)'
    )
    args = parser.parse_args()

    PERSON_NAME = args.person
    BASE_DIR = SCRIPT_DIR / args.input_dir

    # Validate input directory exists
    if not BASE_DIR.exists():
        print(f"\n❌ ERROR: Input directory does not exist: {BASE_DIR}")
        print(f"   Please create the directory or specify a valid --input-dir")
        sys.exit(1)

    if not BASE_DIR.is_dir():
        print(f"\n❌ ERROR: Input path is not a directory: {BASE_DIR}")
        sys.exit(1)

    print("\n" + "=" * 80)
    print("Google Takeout Photo Organization Script")
    print("=" * 80)

    if PERSON_NAME:
        print(f"\nImporting photos for: {PERSON_NAME}")

    print(f"\nInput directory: {BASE_DIR}")

    # Create output directories
    OUTPUT_DIR.mkdir(exist_ok=True)
    VIDEO_OUTPUT_DIR.mkdir(exist_ok=True)
    print(f"\nPhotos output directory: {OUTPUT_DIR}")
    print(f"Videos output directory: {VIDEO_OUTPUT_DIR}")

    # Check if processing _TO_REVIEW_ directory
    is_review_dir = "_TO_REVIEW_" in str(BASE_DIR)

    # Archive trash directories first (move to _TO_REVIEW_) - skip if already processing _TO_REVIEW_
    if not is_review_dir:
        archive_trash_directories()

    # Process each Takeout folder
    total_stats = defaultdict(int)

    # Find all directories containing Google Photos
    takeout_dirs = find_google_photos_dirs(BASE_DIR)

    # First pass: Move project folders (skip for _TO_REVIEW_)
    if not is_review_dir:
        print("\n" + "=" * 80)
        print("PASS 1: Processing Project Folders")
        print("=" * 80)

        # Check for ProjectsToProcess directory (folders that need metadata merging)
        projects_to_process = BASE_DIR / "ProjectsToProcess"
        if projects_to_process.exists():
            print("\nProcessing folders in ProjectsToProcess/")
            for item in projects_to_process.iterdir():
                if item.is_dir():
                    # Merge metadata first
                    merge_project_metadata(item)

                    # Then move to appropriate location
                    source_folder = item.name
                    media_files_dict = process_project_folder(item, f"ProjectsToProcess/{source_folder}")
                    PROJECT_FILES.update(media_files_dict)

        for takeout_path, _ in takeout_dirs:
            process_project_folders(takeout_path)

        print(f"\nTracked {len(PROJECT_FILES)} unique media files from project folders")

    # Second pass: Process regular files
    print("\n" + "=" * 80)
    print("PASS 2: Processing Regular Files")
    print("=" * 80)

    # Build file index for fast duplicate detection (only if not processing review dir)
    file_index = None
    if not is_review_dir:
        file_index = build_file_index(OUTPUT_DIR, VIDEO_OUTPUT_DIR, PERSON_NAME)

    if is_review_dir:
        # Process _TO_REVIEW_ directly
        stats = process_regular_files(BASE_DIR, file_index)
        if stats:
            for key, value in stats.items():
                total_stats[key] += value
    else:
        # Process all Takeout directories found
        for takeout_path, _ in takeout_dirs:
            stats = process_regular_files(takeout_path, file_index)
            if stats:
                for key, value in stats.items():
                    total_stats[key] += value

            # Rebuild index after each Takeout to keep it fresh for the next one
            if file_index is not None:
                file_index = build_file_index(OUTPUT_DIR, VIDEO_OUTPUT_DIR, PERSON_NAME)

    # Clean up empty directories (skip for _TO_REVIEW_)
    if not is_review_dir:
        cleanup_empty_directories()

    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80 + "\n")
    print(f"Total media files found: {total_stats['media_files']}")
    print(f"Total media files sent to review: {total_stats['review']}")
    print(f"Total media files organized: {total_stats['moved']}")
    print(f"Total duplicates deleted: {total_stats['duplicates_deleted']}")
    print(f"Total skipped (already exists): {total_stats['skipped_existing']}")
    print(f"Total failed: {total_stats['failed']}")
    print(f"\nOrganized photos location: {OUTPUT_DIR}")
    print(f"Organized videos location: {VIDEO_OUTPUT_DIR}\n")
    if total_stats['review'] > 0:
        print(f"Files needing review: {REVIEW_DIR}")
    print("\nNOTE: Any files remaining in original Takeout directories are duplicates")
    print("      and can be safely deleted.")
    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
