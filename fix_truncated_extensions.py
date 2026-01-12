#!/usr/bin/env python3
"""
Fix Truncated Extensions in Google Takeout
Fixes files with truncated extensions (.MP -> .MP4, etc.) caused by filename length limits.
"""

import subprocess
from pathlib import Path
import argparse


def get_file_type(file_path):
    """Use the 'file' command to determine actual file type"""
    try:
        result = subprocess.run(
            ['file', '--mime-type', '-b', str(file_path)],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except Exception as e:
        print(f"  Error checking file type for {file_path.name}: {e}")
        return None


def get_correct_extension(mime_type):
    """Map MIME types to correct file extensions"""
    mime_to_ext = {
        'video/mp4': '.mp4',
        'video/quicktime': '.mov',
        'image/jpeg': '.jpg',
        'image/png': '.png',
        'image/gif': '.gif',
        'image/heic': '.heic',
        'image/heif': '.heif',
        'video/x-msvideo': '.avi',
        'video/x-matroska': '.mkv',
        'video/3gpp': '.3gp',
        'video/x-ms-wmv': '.wmv',
    }
    return mime_to_ext.get(mime_type)


def fix_truncated_extension(file_path, dry_run=False):
    """
    Fix a file with truncated extension by detecting actual type and renaming.
    Returns (success, new_path) tuple.
    """
    # Get the actual MIME type
    mime_type = get_file_type(file_path)
    if not mime_type:
        return False, None

    # Determine correct extension
    correct_ext = get_correct_extension(mime_type)
    if not correct_ext:
        print(f"  Unknown MIME type for {file_path.name}: {mime_type}")
        return False, None

    # Build new filename
    current_ext = file_path.suffix.lower()

    # Check if extension needs fixing
    if current_ext == correct_ext:
        # Already correct
        return True, file_path

    # Create new path with correct extension
    new_path = file_path.with_suffix(correct_ext)

    # Check for conflicts
    if new_path.exists():
        print(f"  Conflict: {new_path.name} already exists, skipping {file_path.name}")
        return False, None

    if dry_run:
        print(f"  Would rename: {file_path.name} -> {new_path.name}")
        return True, new_path
    else:
        try:
            file_path.rename(new_path)
            print(f"  Renamed: {file_path.name} -> {new_path.name}")

            # Also rename associated JSON metadata files
            for json_pattern in [
                f"{file_path.name}.json",
                f"{file_path.name}.supplemental-metadata.json",
                f"{file_path.name}.supplemental-metada.json",
                f"{file_path.name}.supplemental-me.json",
                f"{file_path.name}.supplemental-m.json",
                f"{file_path.name}.supplement.json"
            ]:
                json_path = file_path.parent / json_pattern
                if json_path.exists():
                    new_json_path = new_path.parent / f"{new_path.name}{json_path.name[len(file_path.name):]}"
                    json_path.rename(new_json_path)
                    print(f"    Also renamed: {json_path.name} -> {new_json_path.name}")

            return True, new_path
        except Exception as e:
            print(f"  Error renaming {file_path.name}: {e}")
            return False, None


def scan_and_fix(directory, dry_run=False, check_all=False):
    """Scan directory for files with truncated extensions and fix them"""
    directory = Path(directory)

    # Extensions to check (likely truncations)
    suspicious_extensions = {'.MP', '.mp', '.m', '.M'}  # Known truncations

    stats = {
        'checked': 0,
        'fixed': 0,
        'skipped': 0,
        'failed': 0
    }

    print("\n" + "=" * 80)
    print("Scanning for truncated file extensions...")
    print("=" * 80 + "\n")

    if check_all:
        # Check all media-like files (PXL_, IMG_, VID_ patterns and files with no/short extensions)
        print("Checking all potential media files for correct extensions...\n")

        # Known media file patterns
        patterns = ['PXL_*', 'IMG_*', 'VID_*', 'PANO_*', 'MVIMG_*']

        for pattern in patterns:
            for file_path in directory.rglob(pattern):
                if file_path.is_file() and not file_path.name.endswith('.json'):
                    ext = file_path.suffix.lower()
                    # Check files with no extension, very short extensions, or suspicious ones
                    if not ext or len(ext) <= 3 or ext in suspicious_extensions:
                        stats['checked'] += 1
                        success, new_path = fix_truncated_extension(file_path, dry_run)

                        if success:
                            if new_path and new_path != file_path:
                                stats['fixed'] += 1
                            else:
                                stats['skipped'] += 1
                        else:
                            stats['failed'] += 1
    else:
        # Only check known suspicious extensions
        for ext in suspicious_extensions:
            for file_path in directory.rglob(f"*{ext}"):
                if file_path.is_file() and not file_path.name.endswith('.json'):
                    stats['checked'] += 1
                    success, new_path = fix_truncated_extension(file_path, dry_run)

                    if success:
                        if new_path and new_path != file_path:
                            stats['fixed'] += 1
                        else:
                            stats['skipped'] += 1
                    else:
                        stats['failed'] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Fix truncated file extensions in Google Takeout exports',
        epilog='Example: python3 fix_truncated_extensions.py TAKEOUT_DATA/'
    )
    parser.add_argument(
        'directory',
        help='Directory containing Takeout files with truncated extensions'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be renamed without actually renaming'
    )
    parser.add_argument(
        '--quick',
        action='store_true',
        help='Only check known truncations (.MP files), skip comprehensive media file scan'
    )

    args = parser.parse_args()

    directory = Path(args.directory)
    if not directory.exists():
        print(f"Error: Directory not found: {directory}")
        return 1

    print("\n" + "=" * 80)
    print("Fix Truncated Extensions in Google Takeout")
    print("=" * 80)
    print(f"\nDirectory: {directory}")
    print(f"Dry run: {args.dry_run}")
    print(f"Mode: {'Quick (known truncations only)' if args.quick else 'Comprehensive (all media files)'}")
    print()

    # Scan and fix (check_all is True by default unless --quick is used)
    stats = scan_and_fix(directory, args.dry_run, check_all=not args.quick)

    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80 + "\n")
    print(f"Files checked: {stats['checked']}")
    print(f"Files renamed: {stats['fixed']}")
    print(f"Files already correct: {stats['skipped']}")
    print(f"Failed: {stats['failed']}")
    print("\n" + "=" * 80 + "\n")

    if args.dry_run and stats['fixed'] > 0:
        print("Run without --dry-run to apply changes\n")

    return 0


if __name__ == "__main__":
    exit(main())
