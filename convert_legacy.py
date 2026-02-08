#!/usr/bin/env python3
"""
Legacy Video Format Converter

Scans organized video directories and converts legacy formats (AVI, MTS, M2TS,
WMV, etc.) to H.265/HEVC for better compression and modern compatibility.

This module handles in-place conversion of videos that have already been
organized, unlike camcorder_convert.py which processes from TO_PROCESS/.

Key features:
- Scans Organized_Videos/ recursively for legacy formats
- Converts to H.265 using libx265 (same quality settings as camcorder_convert)
- Replaces original after verifying converted file is valid
- Dry-run mode by default for safety

Legacy formats targeted:
- .AVI (various codecs: DivX, XviD, MJPEG, etc.)
- .MTS/.M2TS (AVCHD from camcorders)
- .WMV (Windows Media Video)
- .MOV (older QuickTime, depending on codec)
- .3GP (mobile phone video)

For workflow orchestration, see workflow_reprocess.py.
"""

import os
import subprocess
import sys
from pathlib import Path

from media_utils import AVCHD_EXTENSIONS, MONTH_FOLDER_NAMES

# ============================================================================
# CONFIGURATION
# ============================================================================

SCRIPT_DIR = Path(__file__).parent
VIDEO_OUTPUT_DIR = SCRIPT_DIR / "Organized_Videos"

# FFmpeg encoding settings (match camcorder_convert.py)
FFMPEG_CRF = 20
FFMPEG_PRESET = "slow"
FFMPEG_AUDIO_BITRATE = "192k"

# Extensions that should always be converted (container implies old codec)
LEGACY_EXTENSIONS = {
    '.avi', '.AVI',
    '.mov', '.MOV',
    '.mts', '.MTS', '.m2ts', '.M2TS',
    '.wmv', '.WMV',
    '.3gp', '.3GP',
    '.asf', '.ASF',
    '.flv', '.FLV',
}

# Extensions that need codec checking (container can have modern or legacy codecs)
CHECK_CODEC_EXTENSIONS = {
    '.mp4', '.MP4',
    '.mkv', '.MKV',
    '.m4v', '.M4V',
}

# Codecs that should be converted
CONVERT_CODECS = {
    'mpeg2video',
    'h264', 'avc',
    'mpeg4',
    'mjpeg',
    'wmv3', 'wmv2', 'wmv1',
    'vc1',
    'msmpeg4v3', 'msmpeg4v2',
    'divx', 'xvid',
    'dvvideo',
    'rawvideo',
    'cinepak',
    'indeo3', 'indeo4', 'indeo5',
}

# Codecs to skip (already efficient)
SKIP_CODECS = {
    'hevc', 'h265',
    'av1',
    'vp9', 'vp8',
}


# ============================================================================
# CODEC DETECTION
# ============================================================================

def get_video_codec(file_path):
    """
    Detect the video codec of a file using ffprobe.

    Args:
        file_path: Path to the video file

    Returns:
        str: Codec name (lowercase), or None if detection failed
    """
    try:
        result = subprocess.run(
            [
                'ffprobe', '-v', 'quiet',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=codec_name',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                str(file_path)
            ],
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().lower()

        return None

    except Exception:
        return None


def get_video_duration(file_path):
    """
    Get video duration in seconds using ffprobe.

    Args:
        file_path: Path to the video file

    Returns:
        float: Duration in seconds, or None if detection failed
    """
    try:
        result = subprocess.run(
            [
                'ffprobe', '-v', 'quiet',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                str(file_path)
            ],
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())

        return None

    except Exception:
        return None


def needs_conversion(file_path):
    """
    Determine if a video file needs to be converted to H.265.

    Args:
        file_path: Path to the video file

    Returns:
        tuple: (needs_conversion: bool, reason: str)
    """
    ext = file_path.suffix.lower()

    # Legacy extensions always need conversion
    if ext in {e.lower() for e in LEGACY_EXTENSIONS}:
        codec = get_video_codec(file_path)

        if codec and codec in SKIP_CODECS:
            return False, f"already {codec.upper()} (unusual for {ext})"

        return True, f"legacy format ({ext})"

    # Check-codec extensions need codec analysis
    if ext in {e.lower() for e in CHECK_CODEC_EXTENSIONS}:
        codec = get_video_codec(file_path)

        if codec is None:
            return False, "could not detect codec"

        if codec in SKIP_CODECS:
            return False, f"already {codec.upper()}"

        if codec in CONVERT_CODECS:
            return True, f"{codec.upper()} codec"

        return False, f"unknown codec ({codec}) - skipping to be safe"

    return False, "not a target format"


# ============================================================================
# VIDEO CONVERSION
# ============================================================================

def convert_to_h265(input_path, output_path, dry_run=False):
    """
    Convert video to H.265/HEVC using libx265.

    Uses same quality settings as camcorder_convert.py for consistency.

    Args:
        input_path: Path to source video file
        output_path: Path for output .mp4 file
        dry_run: If True, show command but don't execute

    Returns:
        bool: True if successful, False otherwise
    """
    cmd = [
        'ffmpeg',
        '-i', str(input_path),
        '-c:v', 'libx265',
        '-crf', str(FFMPEG_CRF),
        '-preset', FFMPEG_PRESET,
        '-tag:v', 'hvc1',
        '-c:a', 'aac',
        '-b:a', FFMPEG_AUDIO_BITRATE,
        '-movflags', '+faststart',
        '-n',  # Don't overwrite
        '-loglevel', 'warning',
        '-stats',
        str(output_path)
    ]

    if dry_run:
        print(f"    [DRY RUN] Would convert: {input_path.name}")
        return True

    try:
        print(f"    Converting with libx265 (CRF {FFMPEG_CRF}, preset {FFMPEG_PRESET})...")
        result = subprocess.run(cmd, check=False)

        if result.returncode != 0:
            print(f"    ERROR: ffmpeg returned code {result.returncode}")
            return False

        return True

    except Exception as e:
        print(f"    ERROR: Conversion failed: {e}")
        return False


def verify_conversion(original_path, converted_path, duration_tolerance=1.0):
    """
    Verify that the converted file is valid and matches the original duration.

    Args:
        original_path: Path to original video
        converted_path: Path to converted video
        duration_tolerance: Max allowed duration difference in seconds

    Returns:
        tuple: (is_valid: bool, message: str)
    """
    if not converted_path.exists():
        return False, "converted file does not exist"

    converted_size = converted_path.stat().st_size

    if converted_size == 0:
        return False, "converted file is empty"

    # Check duration matches
    original_duration = get_video_duration(original_path)
    converted_duration = get_video_duration(converted_path)

    if original_duration is None or converted_duration is None:
        return False, "could not verify duration"

    duration_diff = abs(original_duration - converted_duration)

    if duration_diff > duration_tolerance:
        return False, f"duration mismatch: {duration_diff:.1f}s difference"

    # Verify codec is HEVC
    codec = get_video_codec(converted_path)

    if codec not in {'hevc', 'h265'}:
        return False, f"unexpected codec: {codec}"

    return True, "conversion verified"


# ============================================================================
# SCANNING
# ============================================================================

def find_legacy_videos(base_dir, check_all_codecs=False):
    """
    Find all legacy format videos in the organized directory structure.

    Args:
        base_dir: Base directory to scan (usually Organized_Videos/)
        check_all_codecs: If True, also check MP4/MOV files for legacy codecs

    Returns:
        list: List of (file_path, reason) tuples for files needing conversion
    """
    results = []
    base_path = Path(base_dir)

    if not base_path.exists():
        print(f"ERROR: Directory not found: {base_dir}")
        return results

    # Collect extensions to scan
    target_extensions = set(LEGACY_EXTENSIONS)

    if check_all_codecs:
        target_extensions |= CHECK_CODEC_EXTENSIONS

    # Normalize to lowercase for matching
    target_ext_lower = {e.lower() for e in target_extensions}

    print(f"Scanning {base_dir} for legacy video formats...")
    print(f"  Target extensions: {sorted(target_ext_lower)}")

    if check_all_codecs:
        print("  Also checking MP4/MOV/MKV for legacy codecs (slower)")

    file_count = 0
    legacy_count = 0

    for file_path in sorted(base_path.rglob('*')):
        if not file_path.is_file():
            continue

        ext = file_path.suffix.lower()

        if ext not in target_ext_lower:
            continue

        file_count += 1

        # Check if conversion needed
        should_convert, reason = needs_conversion(file_path)

        if should_convert:
            results.append((file_path, reason))
            legacy_count += 1

    print(f"\nFound {legacy_count} legacy videos out of {file_count} scanned")

    return results


# ============================================================================
# MAIN PROCESSING
# ============================================================================

def process_legacy_videos(dry_run=True, check_all_codecs=False, delete_original=True):
    """
    Find and convert all legacy format videos in Organized_Videos/.

    Args:
        dry_run: If True, show what would be done without making changes
        check_all_codecs: If True, also check MP4/MOV for legacy codecs
        delete_original: If True, delete original after successful conversion

    Returns:
        dict: Statistics about processing
    """
    stats = {
        'found': 0,
        'converted': 0,
        'skipped': 0,
        'failed': 0,
        'space_saved': 0,
    }

    # Find legacy videos
    legacy_videos = find_legacy_videos(VIDEO_OUTPUT_DIR, check_all_codecs)
    stats['found'] = len(legacy_videos)

    if not legacy_videos:
        print("\nNo legacy videos found.")
        return stats

    print(f"\n{'=' * 70}")
    print(f"Processing {len(legacy_videos)} legacy videos")
    print('=' * 70)

    if dry_run:
        print("\n*** DRY RUN MODE - No changes will be made ***\n")

    for file_path, reason in legacy_videos:
        # Determine output path - always use .h265.mp4 to indicate codec in filename
        # This makes it easy to identify converted files without checking metadata
        output_path = file_path.with_suffix('.h265.mp4')

        # Handle case where output already exists
        if output_path.exists():
            print(f"\n  {file_path.name}")
            print(f"    SKIPPED: Output already exists: {output_path.name}")
            stats['skipped'] += 1
            continue

        rel_path = file_path.relative_to(VIDEO_OUTPUT_DIR)
        print(f"\n  {rel_path}")
        print(f"    Reason: {reason}")

        original_size = file_path.stat().st_size

        if dry_run:
            print(f"    [DRY RUN] Would convert to: {output_path.name}")
            print(f"    [DRY RUN] Would delete original: {file_path.name}")
            stats['converted'] += 1
            continue

        # Convert
        success = convert_to_h265(file_path, output_path, dry_run=False)

        if not success:
            print(f"    FAILED: Conversion error")
            stats['failed'] += 1

            # Clean up partial output
            if output_path.exists():
                output_path.unlink()

            continue

        # Verify conversion
        is_valid, message = verify_conversion(file_path, output_path)

        if not is_valid:
            print(f"    FAILED: Verification failed - {message}")
            stats['failed'] += 1

            # Clean up bad output
            if output_path.exists():
                output_path.unlink()

            continue

        converted_size = output_path.stat().st_size
        space_saved = original_size - converted_size
        stats['space_saved'] += space_saved

        reduction_pct = ((original_size - converted_size) / original_size * 100) if original_size > 0 else 0
        print(f"    Converted: {original_size / 1024 / 1024:.1f}MB → {converted_size / 1024 / 1024:.1f}MB ({reduction_pct:.0f}% reduction)")

        if delete_original:
            file_path.unlink()
            print(f"    Deleted original: {file_path.name}")

        stats['converted'] += 1

    return stats


def print_summary(stats, dry_run=True):
    """Print processing summary."""
    print(f"\n{'=' * 70}")
    print("Summary")
    print('=' * 70)

    print(f"\n  Legacy videos found:  {stats['found']}")
    print(f"  Successfully converted: {stats['converted']}")
    print(f"  Skipped (exists):     {stats['skipped']}")
    print(f"  Failed:               {stats['failed']}")

    if stats['space_saved'] > 0:
        saved_mb = stats['space_saved'] / 1024 / 1024
        saved_gb = stats['space_saved'] / 1024 / 1024 / 1024

        if saved_gb >= 1:
            print(f"  Space saved:          {saved_gb:.2f} GB")
        else:
            print(f"  Space saved:          {saved_mb:.1f} MB")

    if dry_run:
        print(f"\n  Run without --dry-run to convert {stats['converted']} files")


# ============================================================================
# DIRECT EXECUTION (for testing)
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert legacy video formats in Organized_Videos/ to H.265"
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        default=True,
        help="Show what would be done without making changes (default)"
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help="Actually perform conversions (disables dry-run)"
    )
    parser.add_argument(
        '--check-all-codecs',
        action='store_true',
        help="Also check MP4/MOV/MKV files for legacy codecs (slower)"
    )
    parser.add_argument(
        '--keep-original',
        action='store_true',
        help="Keep original files after conversion (default: delete)"
    )

    args = parser.parse_args()

    dry_run = not args.execute

    stats = process_legacy_videos(
        dry_run=dry_run,
        check_all_codecs=args.check_all_codecs,
        delete_original=not args.keep_original
    )

    print_summary(stats, dry_run=dry_run)
