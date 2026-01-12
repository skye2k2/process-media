#!/usr/bin/env python3
"""
Google Takeout Photo Organization Script
- Organizes photos/videos into year/month structure based on metadata
- Preserves special project folders as intact directories
- Flags photos with conflicting photoTakenTime vs creationTime
"""

import os
import json
import shutil
import subprocess
import sys
import re
import argparse
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# Base directory containing all Takeout folders
SCRIPT_DIR = Path(__file__).parent
BASE_DIR = None  # Will be set from command line args
OUTPUT_DIR = SCRIPT_DIR / "Organized_Photos"
VIDEO_OUTPUT_DIR = SCRIPT_DIR / "Organized_Videos"
REVIEW_DIR = OUTPUT_DIR / "_TO_REVIEW_"
GOOGLE_PHOTOS_DIR = "Google Photos"

# Media file extensions to process
PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.heic', '.heif'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.m4v', '.3gp', '.wmv', '.MP4', '.MP'}
MEDIA_EXTENSIONS = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS

# Month names for directory creation
MONTH_NAMES = [
    "01 January", "02 February", "03 March", "04 April",
    "05 May", "06 June", "07 July", "08 August",
    "09 September", "10 October", "11 November", "12 December"
]

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


def get_metadata_path(media_file):
    """Find the supplemental metadata file for a media file"""
    base_name = media_file.name
    directory = media_file.parent

    # Try exact match first
    exact_match = directory / f"{base_name}.json"
    if exact_match.exists():
        return exact_match

    # Use wildcard to match any JSON with the media filename as prefix
    # Handles all truncation variations
    matches = list(directory.glob(f"{base_name}.*.json"))
    if matches:
        return matches[0]

    return None


def parse_metadata(metadata_path):
    """Parse metadata file and extract photoTakenTime, creationTime, and geoData"""
    try:
        with open(metadata_path, 'r', encoding='utf-8') as f:
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

    except json.JSONDecodeError as e:
        print(f"  Warning: Could not parse metadata {metadata_path}: {e}")

    return None, None, None


def get_date_from_filename(filename):
    """Try to extract date from filename patterns containing YYYYMMDD format"""
    name = filename.stem

    # Look for 8 consecutive digits that form a valid date
    # Matches patterns like: IMG_20200927_123456, P_20240504_113916, 20200927_file, etc.
    match = re.search(r'(\d{8})', name)
    if match:
        date_part = match.group(1)
        try:
            year = int(date_part[0:4])
            month = int(date_part[4:6])
            day = int(date_part[6:8])
            # Validate date is reasonable
            if 1990 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
                return datetime(year, month, day)
        except ValueError:
            pass

    return None


def dates_match(date1, date2):
    """Check if two dates are within 3 months of each other"""
    if date1 is None or date2 is None:
        return True  # If either is None, consider them matching (no conflict)

    # Calculate month difference
    months_diff = abs((date1.year - date2.year) * 12 + (date1.month - date2.month))
    return months_diff < 3


def determine_destination(media_file):
    """
    Determine the year/month destination for a media file.
    Returns: (year, month, metadata_path, needs_review, reason, create_date, modify_date, geo_data, used_filename_date)

    Priority order for date extraction (for performance, filename is checked first):
    1. Filename date pattern (YYYYMMDD) - fastest, no JSON I/O required
    2. JSON metadata (photoTakenTime/creationTime) - only parsed if filename has no date

    Note: metadata_path is always looked up so the file can be deleted after processing.

    create_date and modify_date are used when dates conflict - earlier becomes creation,
    later becomes modification.

    geo_data: dict with latitude/longitude/altitude if available from JSON

    used_filename_date: True if filename provided the date (no EXIF write needed for dates)
    """
    chosen_date = None
    create_date = None
    modify_date = None
    geo_data = None
    needs_review = False
    reason = ""

    # Always look up metadata path so we can delete it after processing
    metadata_path = get_metadata_path(media_file)

    # First, try to extract date from filename (fastest - no JSON parsing required)
    filename_date = get_date_from_filename(media_file)
    if filename_date:
        # Filename date is authoritative when present - skip metadata parsing entirely
        # Return used_filename_date=True so caller knows no date EXIF write needed
        return filename_date.year, filename_date.month, metadata_path, False, "", None, None, None, True

    # Filename didn't have a parseable date, so parse JSON metadata
    if metadata_path:
        photo_taken_date, creation_date, geo_data = parse_metadata(metadata_path)

        # Check if dates conflict (different year/month by 3+ months)
        if photo_taken_date and creation_date:
            if not dates_match(photo_taken_date, creation_date):
                # Use earlier date for organization, store both for EXIF
                if photo_taken_date < creation_date:
                    chosen_date = photo_taken_date
                    create_date = photo_taken_date
                    modify_date = creation_date
                else:
                    chosen_date = creation_date
                    create_date = creation_date
                    modify_date = photo_taken_date
                reason = f"Using earlier date: {create_date.strftime('%Y-%m-%d')} (later: {modify_date.strftime('%Y-%m-%d')})"
            else:
                # Dates match (within 3 months), use photoTakenTime
                chosen_date = photo_taken_date
                create_date = photo_taken_date
        elif photo_taken_date:
            chosen_date = photo_taken_date
            create_date = photo_taken_date
        elif creation_date:
            chosen_date = creation_date
            create_date = creation_date

    # If we still don't have a date, send to review
    if not chosen_date:
        needs_review = True
        reason = "No date in metadata or filename"
        return None, None, metadata_path, needs_review, reason, None, None, None, False

    # JSON provided the date - used_filename_date=False means we need to write EXIF
    return chosen_date.year, chosen_date.month, metadata_path, needs_review, reason, create_date, modify_date, geo_data, False


def create_destination_path(year, month, output_base_dir=OUTPUT_DIR):
    """Create the destination directory path"""
    year_dir = output_base_dir / str(year)
    month_dir = year_dir / MONTH_NAMES[month - 1]
    month_dir.mkdir(parents=True, exist_ok=True)
    return month_dir


def move_file_safely(src, dst_dir, create_date=None, modify_date=None):
    """Move file to destination, handling name conflicts and adding person metadata"""
    base = src.stem
    ext = src.suffix.lower()
    is_media = ext in MEDIA_EXTENSIONS

    original_name = src.name

    # For media files, check if file already exists with any person suffix (first person in wins)
    if is_media:
        # Strip any existing person suffix from the base name
        base_without_suffix = base
        if PERSON_NAME and base.endswith(f"_{PERSON_NAME}"):
            base_without_suffix = base[:-len(PERSON_NAME)-1]
        else:
            # Try to detect other person suffixes (pattern: ends with _Name)
            match = re.match(r'^(.+)_([A-Z][a-z]+)$', base)
            if match:
                base_without_suffix = match.group(1)

        # Check if any file with this base name already exists (with any suffix or no suffix)
        existing_files = list(dst_dir.glob(f"{base_without_suffix}*{ext}"))
        if existing_files:
            # File already exists from another person's import - skip this duplicate
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
    
    Args:
        file_path: Path to the media file
        create_date: datetime for DateTimeOriginal/CreateDate (from JSON metadata)
        modify_date: datetime for ModifyDate (when dates conflicted)
        geo_data: dict with latitude/longitude/altitude (from JSON geoData)
    """
    try:
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

        cmd.append(str(file_path))

        subprocess.run(cmd, capture_output=True, check=False)
    except Exception:
        pass  # Silently fail - metadata is not critical


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
                _, month, _, needs_review, _, _, _, _, _ = determine_destination(file_path)
                if month and not needs_review:
                    months.append(month)

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

    # Try to determine year from folder name
    year = extract_year_from_folder_name(folder_name)

    # If no year in name, try to determine from contents
    if not year:
        for root, dirs, files in os.walk(project_path):
            for filename in files:
                file_path = Path(root) / filename
                ext = file_path.suffix.lower()

                if ext in MEDIA_EXTENSIONS:
                    y, _, _, needs_review, _, _, _, _, _ = determine_destination(file_path)
                    if y and not needs_review:
                        year = y
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


def process_regular_files(takeout_path):
    """Process regular photo files (not in project folders)"""
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
                                # Move metadata too
                                metadata_path = get_metadata_path(file_path)
                                if metadata_path and metadata_path.exists():
                                    shutil.move(str(metadata_path), str(project_folder / metadata_path.name))
                                continue
                            except Exception as e:
                                print(f"  Warning: Could not move edited file {filename}: {e}")

                # Determine destination for regular files
                year, month, metadata_path, needs_review, reason, create_date, modify_date, geo_data, used_filename_date = determine_destination(file_path)

                # Get source folder relative to Google Photos (or _TO_REVIEW_)
                try:
                    if "_TO_REVIEW_" in str(photos_dir):
                        source_folder = "_TO_REVIEW_"
                    else:
                        source_folder = file_path.relative_to(photos_dir).parts[0] if len(file_path.relative_to(photos_dir).parts) > 0 else "root"
                except (ValueError, IndexError):
                    source_folder = "unknown"

                if needs_review:
                    # Move to review directory
                    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
                    success, _ = move_file_safely(file_path, REVIEW_DIR)
                    if success:
                        stats['review'] += 1
                        print(f"  Review: {source_folder}/{file_path.name} ({reason})")

                        # Move metadata too (we need it to figure out the date later)
                        if metadata_path and metadata_path.exists():
                            move_file_safely(metadata_path, REVIEW_DIR)

                elif year and month:
                    # Determine if this is a photo or video
                    is_video = ext in VIDEO_EXTENSIONS
                    output_base = VIDEO_OUTPUT_DIR if is_video else OUTPUT_DIR

                    # Create destination directory
                    dest_dir = create_destination_path(year, month, output_base)

                    # Store original filename before moving
                    original_filename = file_path.name

                    # Write EXIF metadata BEFORE moving (if JSON provided date/geo)
                    if not used_filename_date and (create_date or geo_data):
                        apply_all_metadata(file_path, create_date, modify_date, geo_data)

                    # Move media file
                    success, moved_file = move_file_safely(file_path, dest_dir, create_date, modify_date)
                    if success:
                        stats['moved'] += 1
                        media_type = "video" if is_video else "photo"
                        if reason:
                            print(f"  Moved {media_type}: {source_folder}/{original_filename} -> {year}/{MONTH_NAMES[month-1]} ({reason})")
                        else:
                            print(f"  Moved {media_type}: {source_folder}/{original_filename} -> {year}/{MONTH_NAMES[month-1]}")

                        # Always delete JSON after processing (EXIF already written)
                        if metadata_path and metadata_path.exists():
                            metadata_path.unlink()
                    elif success is False and moved_file is None:
                        # File already exists from another person's import - skip it
                        stats['skipped_existing'] += 1
                        print(f"  Skipped (exists): {source_folder}/{original_filename}")
                        # Also delete the metadata file if it exists
                        if metadata_path and metadata_path.exists():
                            metadata_path.unlink()
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
        epilog='Example: python3 organize_photos.py --person "John Doe"'
    )
    parser.add_argument(
        '--person',
        type=str,
        help='Name of the person whose photos are being imported (for metadata tagging and conflict resolution)'
    )
    parser.add_argument(
        '--input-dir',
        type=str,
        default='TAKEOUT_DATA',
        help='Input directory to process (default: TAKEOUT_DATA)'
    )
    args = parser.parse_args()

    PERSON_NAME = args.person
    BASE_DIR = SCRIPT_DIR / args.input_dir

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

    if is_review_dir:
        # Process _TO_REVIEW_ directly
        stats = process_regular_files(BASE_DIR)
        if stats:
            for key, value in stats.items():
                total_stats[key] += value
    else:
        # Process all Takeout directories found
        for takeout_path, _ in takeout_dirs:
            stats = process_regular_files(takeout_path)
            if stats:
                for key, value in stats.items():
                    total_stats[key] += value

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
