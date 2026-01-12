#!/usr/bin/env python3
"""
Google Takeout Metadata Merger
Merges JSON metadata from Google Takeout into photo/video EXIF data.

This script handles the truncated JSON filenames that Google Takeout creates
and writes photoTakenTime and geoData directly into the media files' EXIF metadata.
"""

import os
import json
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

# Check if exiftool is available
def check_exiftool():
    """Check if exiftool is installed"""
    try:
        result = subprocess.run(['exiftool', '-ver'],
                              capture_output=True,
                              text=True,
                              check=False)
        if result.returncode == 0:
            return True
    except FileNotFoundError:
        pass

    print("\n" + "=" * 80)
    print("ERROR: exiftool is not installed")
    print("=" * 80)
    print("\nPlease install exiftool using one of these methods:")
    print("  macOS:   brew install exiftool")
    print("  Linux:   apt-get install libimage-exiftool-perl")
    print("  Windows: Download from https://exiftool.org/")
    print("\n" + "=" * 80 + "\n")
    return False


def find_matching_json(media_file):
    """
    Find the JSON metadata file for a given media file.
    Handles truncated filenames from Google Takeout.
    """
    media_path = Path(media_file)
    directory = media_path.parent
    base_name = media_path.name

    # Try exact match first
    exact_match = directory / f"{base_name}.json"
    if exact_match.exists():
        return exact_match

    # Use wildcard to match any JSON with the media filename as prefix
    # Handles all truncation variations: .supplemental-metadata.json, .supp.json, etc.
    matches = list(directory.glob(f"{base_name}.*.json"))
    if matches:
        return matches[0]

    return None


def dates_match(date1, date2):
    """Check if two dates are within 3 months of each other"""
    if date1 is None or date2 is None:
        return True  # If either is None, consider them matching (no conflict)

    # Calculate month difference
    months_diff = abs((date1.year - date2.year) * 12 + (date1.month - date2.month))
    return months_diff < 3


def read_google_metadata(json_path):
    """Read and parse Google Takeout JSON metadata"""
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        metadata = {}

        # Extract both photoTakenTime and creationTime
        photo_taken_date = None
        creation_date = None

        if 'photoTakenTime' in data and 'timestamp' in data['photoTakenTime']:
            timestamp = int(data['photoTakenTime']['timestamp'])
            photo_taken_date = datetime.fromtimestamp(timestamp)

        if 'creationTime' in data and 'timestamp' in data['creationTime']:
            timestamp = int(data['creationTime']['timestamp'])
            creation_date = datetime.fromtimestamp(timestamp)

        # Check if dates conflict (differ by 3+ months)
        if photo_taken_date and creation_date:
            if not dates_match(photo_taken_date, creation_date):
                # Dates conflict - use earlier as creation, later as modification
                if photo_taken_date < creation_date:
                    metadata['datetime'] = photo_taken_date
                    metadata['modify_date'] = creation_date
                else:
                    metadata['datetime'] = creation_date
                    metadata['modify_date'] = photo_taken_date
                return metadata

            # Use the earliest date
            metadata['datetime'] = min(photo_taken_date, creation_date)
        elif photo_taken_date:
            metadata['datetime'] = photo_taken_date
        elif creation_date:
            metadata['datetime'] = creation_date

        # Extract geoData
        if 'geoData' in data:
            geo = data['geoData']
            # Only include if coordinates are non-zero
            if geo.get('latitude', 0) != 0 or geo.get('longitude', 0) != 0:
                metadata['latitude'] = geo.get('latitude')
                metadata['longitude'] = geo.get('longitude')
                metadata['altitude'] = geo.get('altitude', 0)

        return metadata
    except Exception as e:
        print(f"  Error reading JSON {json_path}: {e}")
        return None


def extract_date_from_filename(filename):
    """Extract date from common filename patterns"""
    import re

    # Common patterns:
    # IMG_YYYYMMDD_HHMMSS, PXL_YYYYMMDD_HHMMSS, VID_YYYYMMDD_HHMMSS
    # Screenshot_YYYYMMDD-HHMMSS, YYYYMMDD_HHMMSS
    patterns = [
        r'(\d{8})_(\d{6})',  # YYYYMMDD_HHMMSS
        r'(\d{8})-(\d{6})',  # YYYYMMDD-HHMMSS
        r'(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})',  # YYYYMMDD_HHMMSS without separators
    ]

    for pattern in patterns:
        match = re.search(pattern, filename)
        if match:
            try:
                if len(match.groups()) == 2:
                    # Format: YYYYMMDD_HHMMSS or YYYYMMDD-HHMMSS
                    date_part = match.group(1)
                    time_part = match.group(2)
                    year = int(date_part[0:4])
                    month = int(date_part[4:6])
                    day = int(date_part[6:8])
                    hour = int(time_part[0:2])
                    minute = int(time_part[2:4])
                    second = int(time_part[4:6])
                else:
                    # Format: separate groups for each component
                    year = int(match.group(1))
                    month = int(match.group(2))
                    day = int(match.group(3))
                    hour = int(match.group(4))
                    minute = int(match.group(5))
                    second = int(match.group(6))

                # Sanity check the values
                if 1990 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
                    return datetime(year, month, day, hour, minute, second)
            except (ValueError, IndexError):
                continue

    return None


def get_existing_dates(media_file):
    """Read both EXIF DateTimeOriginal and FileModifyDate in a single call for performance"""
    try:
        result = subprocess.run(
            ['exiftool', '-DateTimeOriginal', '-FileModifyDate', '-d', '%Y:%m:%d %H:%M:%S', '-s3', str(media_file)],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split('\n')
            exif_date = None
            file_date = None

            if len(lines) >= 1 and lines[0] and lines[0] != '0000:00:00 00:00:00':
                try:
                    exif_date = datetime.strptime(lines[0], '%Y:%m:%d %H:%M:%S')
                except ValueError:
                    pass

            if len(lines) >= 2 and lines[1]:
                try:
                    file_date = datetime.strptime(lines[1], '%Y:%m:%d %H:%M:%S')
                except ValueError:
                    pass

            return exif_date, file_date
    except Exception:
        pass
    return None, None


def write_exif_metadata(media_file, metadata, preserve_existing=False):
    """
    Write metadata to media file using exiftool.
    Returns True if successful, False otherwise.
    """
    if not metadata:
        return False

    media_path = Path(media_file)

    # Check if both EXIF date and file system date already match
    if 'datetime' in metadata:
        existing_exif_date, existing_file_date = get_existing_dates(media_path)

        # Skip only if both EXIF and file system dates are already correct
        if (existing_exif_date and existing_exif_date == metadata['datetime'] and
            existing_file_date and existing_file_date == metadata['datetime']):
            # Everything already correct, skip write
            return True

    args = ['exiftool']

    # Add datetime if available
    if 'datetime' in metadata:
        dt = metadata['datetime']
        date_str = dt.strftime('%Y:%m:%d %H:%M:%S')

        # Set creation date fields
        args.extend([
            f'-DateTimeOriginal={date_str}',
            f'-CreateDate={date_str}',
            f'-FileCreateDate={date_str}',
        ])

        # If there's a separate modify date (from conflicting metadata), use it
        if 'modify_date' in metadata:
            modify_str = metadata['modify_date'].strftime('%Y:%m:%d %H:%M:%S')
            args.extend([
                f'-ModifyDate={modify_str}',
                f'-FileModifyDate={modify_str}',
            ])
            # For videos with separate modify date
            args.extend([
                f'-TrackCreateDate={date_str}',
                f'-TrackModifyDate={modify_str}',
                f'-MediaCreateDate={date_str}',
                f'-MediaModifyDate={modify_str}',
            ])
        else:
            # No separate modify date, use same date for all
            args.extend([
                f'-ModifyDate={date_str}',
                f'-FileModifyDate={date_str}',
            ])
            # For videos (MP4, MOV, etc.)
            args.extend([
                f'-TrackCreateDate={date_str}',
                f'-TrackModifyDate={date_str}',
                f'-MediaCreateDate={date_str}',
                f'-MediaModifyDate={date_str}',
            ])

    # Add GPS coordinates if available
    if 'latitude' in metadata and 'longitude' in metadata:
        lat = metadata['latitude']
        lon = metadata['longitude']

        # Only write if coordinates are meaningful (not 0,0)
        if abs(lat) > 0.0001 or abs(lon) > 0.0001:
            args.extend([
                f'-GPSLatitude={lat}',
                f'-GPSLongitude={lon}',
            ])

            if 'altitude' in metadata and metadata['altitude'] != 0:
                args.extend([f'-GPSAltitude={metadata["altitude"]}'])

    # Options
    if preserve_existing:
        # Only update if field doesn't already exist
        args.append('-if')
        args.append('not $DateTimeOriginal or $DateTimeOriginal eq "0000:00:00 00:00:00"')

    args.extend([
        '-overwrite_original',  # Don't create _original backup files
        '-quiet',
        str(media_path)
    ])

    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        return result.returncode == 0
    except Exception as e:
        print(f"  Error writing EXIF to {media_path.name}: {e}")
        return False


def process_directory(directory, remove_json=False, preserve_existing=False, recursive=True):
    """
    Process all media files in a directory and merge their JSON metadata.
    """
    directory = Path(directory)

    # Media extensions to process
    media_extensions = {
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.heic', '.heif',
        '.mp4', '.mov', '.avi', '.mkv', '.m4v', '.3gp', '.wmv', '.MP4', '.MP'
    }

    stats = {
        'total': 0,
        'processed': 0,
        'skipped_no_json': 0,
        'skipped_no_metadata': 0,
        'skipped_conflict': 0,
        'failed': 0,
        'removed_json': 0
    }

    # Find all media files
    pattern = '**/*' if recursive else '*'
    for media_file in directory.glob(pattern):
        if media_file.is_file() and media_file.suffix.lower() in media_extensions:
            stats['total'] += 1

            # Find matching JSON
            json_file = find_matching_json(media_file)

            # Read metadata from JSON if available
            metadata = None
            from_filename = False
            if json_file:
                metadata = read_google_metadata(json_file)

            # If no JSON or no usable metadata, try extracting from filename
            if not metadata or ('conflict' not in metadata and 'datetime' not in metadata):
                filename_date = extract_date_from_filename(media_file.name)
                if filename_date:
                    if not metadata:
                        metadata = {}
                    metadata['datetime'] = filename_date
                    from_filename = True
                    if not json_file:
                        stats['skipped_no_json'] += 1
            elif not json_file:
                stats['skipped_no_json'] += 1

            # Skip if still no usable metadata
            if not metadata or 'datetime' not in metadata:
                stats['skipped_no_metadata'] += 1
                continue

            # Build log message with metadata info
            log_parts = [f"Processing: {media_file.name}"]
            if 'datetime' in metadata:
                date_str = metadata['datetime'].strftime('%Y-%m-%d %H:%M:%S')
                source = " (from filename)" if from_filename else ""
                log_parts.append(f"<-- {date_str}{source}")
                if 'modify_date' in metadata:
                    modify_str = metadata['modify_date'].strftime('%Y-%m-%d')
                    log_parts.append(f" (modified: {modify_str})")
                if 'latitude' in metadata and 'longitude' in metadata:
                    log_parts.append(", geodata")

            print(' '.join(log_parts))

            # Write to EXIF
            success = write_exif_metadata(media_file, metadata, preserve_existing)

            if success:
                stats['processed'] += 1
                if remove_json and json_file is not None:
                    try:
                        json_file.unlink()
                        stats['removed_json'] += 1
                    except Exception as e:
                        print(f"  Warning: Could not remove {json_file.name}: {e}")
            else:
                stats['failed'] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Merge Google Takeout JSON metadata into media file EXIF data',
        epilog='Example: python3 merge_metadata.py TAKEOUT_DATA/ --recursive'
    )
    parser.add_argument(
        'directory',
        help='Directory containing media files and JSON metadata'
    )
    parser.add_argument(
        '--recursive', '-r',
        action='store_true',
        help='Process subdirectories recursively'
    )
    parser.add_argument(
        '--remove-json',
        action='store_true',
        help='Remove JSON files after successful merge'
    )
    parser.add_argument(
        '--preserve-existing',
        action='store_true',
        help='Preserve existing EXIF data (default: overwrite with Google metadata)'
    )

    args = parser.parse_args()

    # Check for exiftool
    if not check_exiftool():
        return 1

    directory = Path(args.directory)
    if not directory.exists():
        print(f"Error: Directory not found: {directory}")
        return 1

    print("\n" + "=" * 80)
    print("Google Takeout Metadata Merger")
    print("=" * 80)
    print(f"\nDirectory: {directory}")
    print(f"Recursive: {args.recursive}")
    print(f"Remove JSON after merge: {args.remove_json}")
    print(f"Preserve existing EXIF: {args.preserve_existing}")
    print("\nDate handling:")
    print("  - Uses earliest date between photoTakenTime and creationTime")
    print("  - Skips files where dates differ by 3+ months")
    print("\n" + "=" * 80 + "\n")

    # Process files
    stats = process_directory(
        directory,
        remove_json=args.remove_json,
        preserve_existing=args.preserve_existing,
        recursive=args.recursive
    )

    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80 + "\n")
    print(f"Total media files found: {stats['total']}")
    print(f"Successfully processed: {stats['processed']}")
    print(f"Skipped (no JSON): {stats['skipped_no_json']}")
    print(f"Skipped (no metadata): {stats['skipped_no_metadata']}")
    print(f"Skipped (date conflict): {stats['skipped_conflict']}")
    print(f"Failed: {stats['failed']}")
    if args.remove_json:
        print(f"JSON files removed: {stats['removed_json']}")
    print("\n" + "=" * 80 + "\n")

    return 0


if __name__ == "__main__":
    exit(main())
