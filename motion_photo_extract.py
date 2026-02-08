#!/usr/bin/env python3
"""
Motion Photo Extraction Script

Handles Google Pixel "Motion Photo" files – short video clips that embed a
full-resolution still image as a second video stream. These dual-stream files
cause issues with macOS QuickLook/Preview (won't play), though dedicated video
players handle them fine.

This script can:
1. Scan for Motion Photos (videos with multiple video streams)
2. Extract the embedded still image to a separate photo file
3. Delete the low-value video clips after extraction
4. Or: Strip the embedded still to make QuickLook-compatible videos

Motion Photo Detection:
- Two HEVC video streams in MP4 container
- First stream: 1440x1080 or similar (the video clip, typically 2-3 seconds)
- Second stream: Higher resolution (2048x1536, the still photo)
- Sometimes have 'mett' metadata tracks

Usage:
    # Scan for Motion Photos (dry run)
    python3 motion_photo_extract.py --scan

    # Extract stills and delete videos
    python3 motion_photo_extract.py --extract --delete-video

    # Make videos QuickLook-compatible (strip embedded still)
    python3 motion_photo_extract.py --fix-quicklook

    # Process specific directory
    python3 motion_photo_extract.py --scan /path/to/videos

    # Actually perform changes (default is dry run)
    python3 motion_photo_extract.py --extract --delete-video --execute
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

# ============================================================================
# CONFIGURATION
# ============================================================================

SCRIPT_DIR = Path(__file__).parent
VIDEO_OUTPUT_DIR = SCRIPT_DIR / "Organized_Videos"
PHOTO_OUTPUT_DIR = SCRIPT_DIR / "Organized_Photos"
DEFAULT_INPUT_DIR = SCRIPT_DIR / "TO_PROCESS"

# Video extensions to scan
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.m4v'}


# ============================================================================
# DETECTION
# ============================================================================

def get_video_streams(file_path):
    """
    Get detailed stream information for a video file.

    Args:
        file_path: Path to the video file

    Returns:
        list: List of stream info dicts, or empty list on error
    """
    try:
        result = subprocess.run(
            [
                'ffprobe', '-v', 'error',
                '-show_streams',
                '-print_format', 'json',
                str(file_path)
            ],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            return []

        data = json.loads(result.stdout)
        return data.get('streams', [])

    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return []


def is_motion_photo(file_path):
    """
    Detect if a video file is a Google Motion Photo.

    Motion Photos have:
    - Two video streams (clip + embedded still)
    - Both streams are typically HEVC
    - Second video stream has 0 duration (it's a single frame)

    Args:
        file_path: Path to the video file

    Returns:
        tuple: (is_motion_photo, video_stream_info, still_stream_info) or (False, None, None)
    """
    streams = get_video_streams(file_path)

    if not streams:
        return False, None, None

    # Find video streams
    video_streams = [s for s in streams if s.get('codec_type') == 'video']

    if len(video_streams) < 2:
        return False, None, None

    # Motion Photo pattern: first stream is video, second is still image
    # The still typically has duration=0 or very short duration
    primary = video_streams[0]
    secondary = video_streams[1]

    # Check if secondary looks like an embedded still (0 duration, higher resolution)
    secondary_duration = float(secondary.get('duration', 0) or 0)
    primary_pixels = int(primary.get('width', 0)) * int(primary.get('height', 0))
    secondary_pixels = int(secondary.get('width', 0)) * int(secondary.get('height', 0))

    # Motion Photo criteria:
    # - Secondary has 0 or near-0 duration
    # - Secondary is higher resolution OR same codec (both HEVC)
    is_still_embedded = (
        secondary_duration < 0.1 and
        (secondary_pixels >= primary_pixels or
         secondary.get('codec_name') == primary.get('codec_name'))
    )

    if is_still_embedded:
        return True, primary, secondary

    return False, None, None


def scan_for_motion_photos(directory, recursive=True):
    """
    Scan directory for Motion Photo files.

    Args:
        directory: Path to scan
        recursive: Whether to scan subdirectories

    Returns:
        list: List of (file_path, video_info, still_info) tuples
    """
    directory = Path(directory)
    motion_photos = []

    if recursive:
        files = directory.rglob('*')
    else:
        files = directory.glob('*')

    video_files = [f for f in files if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS]

    print(f"Scanning {len(video_files)} video files...")

    for i, file_path in enumerate(video_files, 1):
        if i % 50 == 0:
            print(f"  Checked {i}/{len(video_files)} files...")

        is_mp, video_info, still_info = is_motion_photo(file_path)

        if is_mp:
            motion_photos.append((file_path, video_info, still_info))

    return motion_photos


# ============================================================================
# EXTRACTION AND FIXING
# ============================================================================

def find_highres_photo(video_path):
    """
    Check if a high-res photo already exists for this Motion Photo.

    Google Pixel exports Motion Photos as a video + separate high-res JPEG (4080x3072).
    The high-res photo typically has '.MP' in the filename before the suffix:
      - PXL_20260117_023418623.MP_Clif.jpg (4080x3072, ~6MB)
      - PXL_20260117_023418623_Clif.mp4 (motion video with embedded 2048x1536 still)

    Args:
        video_path: Path to the Motion Photo video

    Returns:
        Path: Path to high-res photo if found, None otherwise
    """
    video_path = Path(video_path)
    video_str = str(video_path)

    # Determine the photo directory (swap Organized_Videos → Organized_Photos)
    if 'Organized_Videos' in video_str:
        photo_dir = Path(video_str.replace('Organized_Videos', 'Organized_Photos')).parent
    else:
        photo_dir = video_path.parent

    if not photo_dir.exists():
        return None

    # Extract the base timestamp from filename (PXL_20260117_023418623)
    # Video: PXL_20260117_023418623_Clif.mp4
    # Photo: PXL_20260117_023418623.MP_Clif.jpg
    stem = video_path.stem  # PXL_20260117_023418623_Clif

    # Find timestamp portion (first 3 underscore-separated parts for PXL files)
    parts = stem.split('_')

    if len(parts) >= 3 and parts[0] == 'PXL':
        timestamp = '_'.join(parts[:3])  # PXL_20260117_023418623

        # Look for high-res versions with .MP in name
        for photo in photo_dir.glob(f"{timestamp}.MP*"):
            if photo.suffix.lower() in ['.jpg', '.jpeg']:
                # Verify it's actually high-res (> 3MB is a good indicator)
                if photo.stat().st_size > 3 * 1024 * 1024:
                    return photo

    return None


def extract_still_image(video_path, output_path=None, dry_run=True):
    """
    Extract the embedded still image from a Motion Photo.

    The still is stored as the second video stream (index 0:v:1) as a single HEVC frame
    with zero duration. ffmpeg's MOV demuxer discards zero-duration streams by default,
    so we use a two-step extraction:
    1. Copy raw HEVC stream to temp file (bypasses discard)
    2. Decode HEVC to JPEG

    Args:
        video_path: Path to the Motion Photo
        output_path: Where to save the still (default: Organized_Photos with matching year/month)
        dry_run: If True, only print what would happen

    Returns:
        Path: Path to extracted still, or None on failure
    """
    video_path = Path(video_path)

    if output_path is None:
        # Route to Organized_Photos instead of Organized_Videos, preserving year/month structure
        # e.g., Organized_Videos/2025/03 March/file.mp4 → Organized_Photos/2025/03 March/file.jpg
        video_str = str(video_path)

        if 'Organized_Videos' in video_str:
            photo_str = video_str.replace('Organized_Videos', 'Organized_Photos')
            output_path = Path(photo_str).with_suffix('.jpg')
        else:
            # Fallback: same directory with .jpg extension
            output_path = video_path.with_suffix('.jpg')

    output_path = Path(output_path)

    if dry_run:
        print(f"  [DRY RUN] Would extract still: {video_path.name} → {output_path}")
        return output_path

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Two-step extraction to bypass ffmpeg's zero-duration stream discard:
    # Step 1: Copy raw HEVC stream to temp file
    temp_hevc = output_path.with_suffix('.tmp.hevc')

    try:
        result = subprocess.run(
            [
                'ffmpeg', '-v', 'warning',
                '-i', str(video_path),
                '-map', '0:v:1',           # Select second video stream (the still)
                '-c:v', 'copy',            # Copy without decode (bypasses discard)
                '-f', 'hevc',              # Raw HEVC format
                '-y',
                str(temp_hevc)
            ],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode != 0 or not temp_hevc.exists():
            print(f"  ERROR extracting HEVC stream from {video_path.name}: {result.stderr}")
            temp_hevc.unlink(missing_ok=True)
            return None

        # Step 2: Decode HEVC to JPEG
        result = subprocess.run(
            [
                'ffmpeg', '-v', 'warning',
                '-i', str(temp_hevc),
                '-frames:v', '1',          # Extract 1 frame
                '-q:v', '2',               # High quality JPEG
                '-y',
                str(output_path)
            ],
            capture_output=True,
            text=True,
            timeout=60
        )

        # Clean up temp file
        temp_hevc.unlink(missing_ok=True)

        if result.returncode == 0 and output_path.exists():
            print(f"  Extracted still: {video_path.name} → {output_path}")
            return output_path
        else:
            print(f"  ERROR decoding still from {video_path.name}: {result.stderr}")
            return None

    except subprocess.TimeoutExpired:
        print(f"  ERROR: Timeout extracting still from {video_path.name}")
        temp_hevc.unlink(missing_ok=True)
        return None


def fix_for_quicklook(video_path, output_path=None, dry_run=True):
    """
    Create a QuickLook-compatible version by keeping only the primary video stream.

    This strips the embedded still image, leaving a single-stream video that
    macOS Preview/QuickLook can play.

    Args:
        video_path: Path to the Motion Photo
        output_path: Where to save (default: overwrites original)
        dry_run: If True, only print what would happen

    Returns:
        bool: True on success
    """
    video_path = Path(video_path)

    # Create temp file, then replace original
    temp_path = video_path.with_suffix('.tmp.mp4')

    if output_path is None:
        output_path = video_path

    output_path = Path(output_path)

    if dry_run:
        print(f"  [DRY RUN] Would fix for QuickLook: {video_path.name}")
        return True

    try:
        # Re-mux keeping only first video stream and all audio
        result = subprocess.run(
            [
                'ffmpeg', '-v', 'warning',
                '-i', str(video_path),
                '-map', '0:v:0',           # First video stream only
                '-map', '0:a?',            # All audio streams (if any)
                '-c', 'copy',              # No re-encoding
                '-y',
                str(temp_path)
            ],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode != 0:
            print(f"  ERROR fixing {video_path.name}: {result.stderr}")
            temp_path.unlink(missing_ok=True)
            return False

        # Replace original with fixed version
        temp_path.replace(output_path)
        print(f"  Fixed for QuickLook: {output_path.name}")
        return True

    except subprocess.TimeoutExpired:
        print(f"  ERROR: Timeout fixing {video_path.name}")
        temp_path.unlink(missing_ok=True)
        return False


def delete_video(video_path, dry_run=True):
    """
    Delete a video file.

    Args:
        video_path: Path to delete
        dry_run: If True, only print what would happen

    Returns:
        bool: True on success
    """
    video_path = Path(video_path)

    if dry_run:
        print(f"  [DRY RUN] Would delete: {video_path.name}")
        return True

    try:
        video_path.unlink()
        print(f"  Deleted: {video_path.name}")
        return True
    except OSError as e:
        print(f"  ERROR deleting {video_path.name}: {e}")
        return False


# ============================================================================
# BATCH OPERATIONS
# ============================================================================

def process_motion_photos(motion_photos, action, dry_run=True):
    """
    Process a list of Motion Photos with the specified action.

    Args:
        motion_photos: List of (file_path, video_info, still_info) tuples
        action: 'extract', 'fix-quicklook', 'extract-delete'
        dry_run: If True, only print what would happen

    Returns:
        dict: Statistics about the operation
    """
    stats = {
        'processed': 0,
        'extracted': 0,
        'skipped_highres': 0,  # Skipped extraction because high-res exists
        'lowres_deleted': 0,   # Low-res extractions deleted (had high-res version)
        'fixed': 0,
        'deleted': 0,
        'errors': 0
    }

    for file_path, video_info, still_info in motion_photos:
        stats['processed'] += 1

        if action == 'extract':
            result = extract_still_image(file_path, dry_run=dry_run)
            if result:
                stats['extracted'] += 1
            else:
                stats['errors'] += 1

        elif action == 'fix-quicklook':
            result = fix_for_quicklook(file_path, dry_run=dry_run)
            if result:
                stats['fixed'] += 1
            else:
                stats['errors'] += 1

        elif action == 'extract-delete':
            # Check if high-res version already exists
            highres = find_highres_photo(file_path)

            if highres:
                # High-res exists - no need to extract low-res embedded still
                if dry_run:
                    print(f"  [DRY RUN] Skipping extraction (high-res exists): {highres.name}")
                else:
                    print(f"  Skipped extraction (high-res exists): {highres.name}")
                stats['skipped_highres'] += 1

                # Delete the video since we already have the high-res photo
                if delete_video(file_path, dry_run=dry_run):
                    stats['deleted'] += 1
                else:
                    stats['errors'] += 1

                # Check if a low-res extraction was previously created and delete it
                video_str = str(file_path)

                if 'Organized_Videos' in video_str:
                    lowres_path = Path(video_str.replace('Organized_Videos', 'Organized_Photos')).with_suffix('.jpg')
                else:
                    lowres_path = file_path.with_suffix('.jpg')

                # Only delete if it's actually smaller than the high-res (crude check)
                if lowres_path.exists() and lowres_path.stat().st_size < highres.stat().st_size:
                    if dry_run:
                        print(f"  [DRY RUN] Would delete low-res duplicate: {lowres_path.name}")
                    else:
                        lowres_path.unlink()
                        print(f"  Deleted low-res duplicate: {lowres_path.name}")
                    stats['lowres_deleted'] += 1

            else:
                # No high-res - extract the embedded still
                result = extract_still_image(file_path, dry_run=dry_run)

                if result:
                    stats['extracted'] += 1

                    # Then delete video
                    if delete_video(file_path, dry_run=dry_run):
                        stats['deleted'] += 1
                    else:
                        stats['errors'] += 1
                else:
                    stats['errors'] += 1

    return stats


# ============================================================================
# MAIN
# ============================================================================

def print_summary(motion_photos):
    """Print summary of found Motion Photos."""
    print()
    print("=" * 70)
    print(f"Found {len(motion_photos)} Motion Photo(s)")
    print("=" * 70)

    if not motion_photos:
        return

    # Group by directory for readability
    by_dir = {}

    for file_path, video_info, still_info in motion_photos:
        dir_path = file_path.parent
        if dir_path not in by_dir:
            by_dir[dir_path] = []
        by_dir[dir_path].append((file_path, video_info, still_info))

    for dir_path, files in sorted(by_dir.items()):
        print(f"\n{dir_path}/")

        for file_path, video_info, still_info in files:
            video_res = f"{video_info.get('width', '?')}x{video_info.get('height', '?')}"
            still_res = f"{still_info.get('width', '?')}x{still_info.get('height', '?')}"
            duration = float(video_info.get('duration', 0))
            size_mb = file_path.stat().st_size / (1024 * 1024)
            print(f"  {file_path.name}: {duration:.1f}s video ({video_res}), still ({still_res}), {size_mb:.1f}MB")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Handle Google Pixel Motion Photo files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Actions:
  --scan             Scan and report Motion Photos (default action)
  --extract          Extract embedded still images to separate files
  --delete-video     Delete video files after extraction (requires --extract)
  --fix-quicklook    Strip embedded still to make QuickLook-compatible

Examples:
  %(prog)s --scan                           # Find Motion Photos in Organized_Videos/
  %(prog)s --scan TO_PROCESS/               # Scan specific directory
  %(prog)s --extract --execute              # Extract stills (actually do it)
  %(prog)s --extract --delete-video --execute  # Extract stills and delete videos
  %(prog)s --fix-quicklook --execute        # Make videos QuickLook-compatible
        """
    )

    parser.add_argument(
        'directory',
        nargs='?',
        default=None,
        help="Directory to process (default: Organized_Videos/)"
    )
    parser.add_argument(
        '--scan',
        action='store_true',
        help="Scan for Motion Photos and report findings"
    )
    parser.add_argument(
        '--extract',
        action='store_true',
        help="Extract embedded still images"
    )
    parser.add_argument(
        '--delete-video',
        action='store_true',
        help="Delete video files after extracting stills (requires --extract)"
    )
    parser.add_argument(
        '--fix-quicklook',
        action='store_true',
        help="Strip embedded still to make videos QuickLook-compatible"
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help="Actually perform changes (default is dry run)"
    )
    parser.add_argument(
        '--no-recursive',
        action='store_true',
        help="Don't scan subdirectories"
    )

    args = parser.parse_args()

    # Determine directory to scan
    if args.directory:
        scan_dir = Path(args.directory)
    else:
        scan_dir = VIDEO_OUTPUT_DIR

    if not scan_dir.exists():
        print(f"ERROR: Directory not found: {scan_dir}")
        sys.exit(1)

    # Validate argument combinations
    if args.delete_video and not args.extract:
        print("ERROR: --delete-video requires --extract")
        sys.exit(1)

    if args.fix_quicklook and args.extract:
        print("ERROR: Cannot use --fix-quicklook with --extract (choose one)")
        sys.exit(1)

    # Default to scan if no action specified
    if not any([args.scan, args.extract, args.fix_quicklook]):
        args.scan = True

    dry_run = not args.execute

    # Header
    print()
    print("=" * 70)
    print("Motion Photo Handler")
    print("=" * 70)
    print(f"Scanning: {scan_dir}")

    if dry_run and (args.extract or args.fix_quicklook):
        print("\n*** DRY RUN MODE - use --execute to make changes ***")

    print()

    # Scan for Motion Photos
    motion_photos = scan_for_motion_photos(scan_dir, recursive=not args.no_recursive)

    if args.scan:
        print_summary(motion_photos)

        if motion_photos:
            print("\nNext steps:")
            print("  --extract --execute          Extract stills to separate files")
            print("  --extract --delete-video --execute  Extract stills, delete videos")
            print("  --fix-quicklook --execute    Make videos QuickLook-compatible")

        sys.exit(0)

    if not motion_photos:
        print("No Motion Photos found.")
        sys.exit(0)

    # Determine action
    if args.extract and args.delete_video:
        action = 'extract-delete'
    elif args.extract:
        action = 'extract'
    elif args.fix_quicklook:
        action = 'fix-quicklook'
    else:
        action = 'extract'

    print(f"\nProcessing {len(motion_photos)} Motion Photo(s)...")
    print()

    stats = process_motion_photos(motion_photos, action, dry_run=dry_run)

    # Summary
    print()
    print("-" * 40)
    print("Results:")
    print(f"  Processed: {stats['processed']}")
    if stats['extracted']:
        print(f"  Stills extracted: {stats['extracted']}")
    if stats.get('skipped_highres'):
        print(f"  Skipped (high-res exists): {stats['skipped_highres']}")
    if stats.get('lowres_deleted'):
        print(f"  Low-res duplicates deleted: {stats['lowres_deleted']}")
    if stats['fixed']:
        print(f"  Fixed for QuickLook: {stats['fixed']}")
    if stats['deleted']:
        print(f"  Videos deleted: {stats['deleted']}")
    if stats['errors']:
        print(f"  Errors: {stats['errors']}")

    if dry_run:
        print("\n*** DRY RUN - no changes made. Use --execute to apply. ***")


if __name__ == "__main__":
    main()
