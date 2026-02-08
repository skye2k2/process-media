#!/usr/bin/env python3
"""
Camcorder AVCHD to H.265 Conversion Module

Core conversion logic for processing AVCHD (.MTS/.M2TS) files from camcorders
that use unhelpful sequential naming (00000.MTS, 00001.MTS, etc.).

This module provides:
- Date extraction from EXIF metadata (exiftool, ffprobe, file mtime fallback)
- Video codec detection via ffprobe
- H.265/HEVC conversion using libx265 software encoding
- File organization into YYYY/MM MonthName/ structure
- EXIF metadata writing to output files

For workflow orchestration (argument parsing, user prompts, timing, summary),
see workflow_camcorder.py.

Direct usage (for testing individual functions):
    python3 camcorder_convert.py [input_dir]
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from build_file_index import build_file_index
from conversion_index import (
    add_to_index,
    load_index,
    lookup_in_index,
    print_index_summary,
    save_index,
)
from media_utils import AVCHD_EXTENSIONS, ALL_VIDEO_EXTENSIONS, MONTH_NAMES

# ============================================================================
# CONFIGURATION
# ============================================================================

SCRIPT_DIR = Path(__file__).parent
DEFAULT_INPUT_DIR = SCRIPT_DIR / "TO_PROCESS"
VIDEO_OUTPUT_DIR = SCRIPT_DIR / "Organized_Videos"

# FFmpeg encoding settings for archival quality
# CRF 26 balances quality and file size (was 20, but produced bloated files)
# Preset "slow" trades encoding time for better compression
FFMPEG_CRF = 26
FFMPEG_PRESET = "slow"
FFMPEG_AUDIO_BITRATE = "192k"

# Noise detection threshold for encoder selection
# Videos with bits-per-pixel-per-frame above this use libx265 (better noise handling)
# Videos below this use VideoToolbox for faster encoding with similar quality
# Based on benchmark: 0.177 bpp showed visible VideoToolbox artifacting (SSIM 0.899)
# while 0.160 bpp was acceptable (SSIM 0.906). Threshold set conservatively.
NOISE_THRESHOLD_BPP = 0.17

# Codecs that should be converted (older/larger formats)
# Files with these codecs will be transcoded to H.265
CONVERT_CODECS = {
    'mpeg2video',    # AVCHD uses H.264 in MPEG-2 TS, but some older camcorders use MPEG-2
    'h264',          # H.264/AVC - the main target for conversion
    'avc',           # Alternative name for H.264
    'mpeg4',         # MPEG-4 Part 2 (older than H.264)
    'mjpeg',         # Motion JPEG (very large files)
    'wmv3',          # Windows Media Video 9
    'vc1',           # VC-1 (used in some Blu-ray)
}

# Codecs to skip (already efficient or modern)
SKIP_CODECS = {
    'hevc',          # H.265/HEVC - already what we want
    'h265',          # Alternative name for HEVC
    'av1',           # AV1 - even newer than HEVC
    'vp9',           # VP9 - efficient, no need to convert
}


# ============================================================================
# DATE EXTRACTION
# ============================================================================

def get_creation_date_exiftool(file_path):
    """
    Extract creation date from AVCHD file using exiftool.

    AVCHD files typically store the recording date in DateTimeOriginal
    or CreateDate tags. Exiftool handles the AVCHD metadata containers well.

    Args:
        file_path: Path to the .MTS/.M2TS file

    Returns:
        datetime object if found, None otherwise
    """
    try:
        # Try DateTimeOriginal first, then CreateDate, then MediaCreateDate
        result = subprocess.run(
            [
                'exiftool', '-s', '-s', '-s',
                '-DateTimeOriginal',
                '-CreateDate',
                '-MediaCreateDate',
                str(file_path)
            ],
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode != 0 or not result.stdout.strip():
            return None

        # Exiftool returns multiple values separated by newlines
        # Take the first non-empty one
        for line in result.stdout.strip().split('\n'):
            date_str = line.strip()

            if not date_str:
                continue

            # Strip timezone info if present (e.g., "-07:00 DST", "+00:00")
            # Format: "2019:03:14 16:54:23-07:00 DST" -> "2019:03:14 16:54:23"
            if len(date_str) > 19:
                date_str = date_str[:19]

            # Handle "YYYY:MM:DD HH:MM:SS" format from exiftool
            try:
                return datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
            except ValueError:
                # Try alternate format without seconds
                try:
                    return datetime.strptime(date_str, "%Y:%m:%d %H:%M")
                except ValueError:
                    continue

        return None

    except FileNotFoundError:
        print("  ERROR: exiftool not found. Please install: brew install exiftool")
        sys.exit(1)
    except Exception as e:
        print(f"  Warning: Could not extract date from {file_path.name}: {e}")
        return None


def get_creation_date_ffprobe(file_path):
    """
    Fallback: Extract creation date using ffprobe.

    Some AVCHD files store creation_time in the format container metadata.

    Args:
        file_path: Path to the video file

    Returns:
        datetime object if found, None otherwise
    """
    try:
        result = subprocess.run(
            [
                'ffprobe', '-v', 'quiet',
                '-show_entries', 'format_tags=creation_time',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                str(file_path)
            ],
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode != 0 or not result.stdout.strip():
            return None

        date_str = result.stdout.strip()

        # FFprobe returns ISO format: "2024-05-04T11:39:16.000000Z"
        try:
            # Handle microseconds and timezone
            if '.' in date_str:
                date_str = date_str.split('.')[0]

            if date_str.endswith('Z'):
                date_str = date_str[:-1]

            return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")

        except ValueError:
            return None

    except Exception:
        return None


def get_creation_date(file_path):
    """
    Get creation date from video file, trying multiple methods.

    Priority:
    1. exiftool (most reliable for AVCHD)
    2. ffprobe (fallback for container metadata)
    3. File modification time (last resort, often inaccurate)

    Args:
        file_path: Path to the video file

    Returns:
        tuple: (datetime, source_string) where source indicates how date was found
    """
    # Try exiftool first (most reliable for AVCHD)
    date = get_creation_date_exiftool(file_path)

    if date:
        return date, "exiftool"

    # Fallback to ffprobe
    date = get_creation_date_ffprobe(file_path)

    if date:
        return date, "ffprobe"

    # Last resort: file modification time (unreliable but better than nothing)
    try:
        mtime = os.path.getmtime(file_path)
        return datetime.fromtimestamp(mtime), "file_mtime (unreliable)"
    except Exception:
        return None, None


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


def get_video_info(file_path):
    """
    Get video resolution, bitrate, and duration via ffprobe.

    Args:
        file_path: Path to the video file

    Returns:
        dict: {width, height, bitrate, duration} or None if detection failed
    """
    try:
        result = subprocess.run(
            [
                'ffprobe', '-v', 'quiet',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height,bit_rate:format=duration,bit_rate',
                '-of', 'json',
                str(file_path)
            ],
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode != 0:
            return None

        import json
        data = json.loads(result.stdout)

        info = {}

        # Get resolution from stream
        if data.get('streams'):
            stream = data['streams'][0]
            info['width'] = int(stream.get('width', 0))
            info['height'] = int(stream.get('height', 0))
            # Stream bitrate may be available
            if stream.get('bit_rate'):
                info['bitrate'] = int(stream['bit_rate'])

        # Get duration and overall bitrate from format
        if data.get('format'):
            fmt = data['format']
            if fmt.get('duration'):
                info['duration'] = float(fmt['duration'])
            # Use format bitrate if stream bitrate not available
            if 'bitrate' not in info and fmt.get('bit_rate'):
                info['bitrate'] = int(fmt['bit_rate'])

        # Estimate bitrate from file size if not available
        if 'bitrate' not in info and 'duration' in info and info['duration'] > 0:
            file_size = file_path.stat().st_size
            info['bitrate'] = int((file_size * 8) / info['duration'])

        return info if info.get('width') and info.get('height') else None

    except Exception:
        return None


def is_noisy_video(file_path, video_info=None):
    """
    Detect if video has high noise/grain that requires software encoding.

    Uses bits-per-pixel-per-frame metric: noisy videos have higher bitrates
    relative to their resolution because noise doesn't compress well.

    Args:
        file_path: Path to the video file
        video_info: Optional pre-fetched video info dict

    Returns:
        tuple: (is_noisy: bool, bpp: float, reason: str)
    """
    if video_info is None:
        video_info = get_video_info(file_path)

    if not video_info or not video_info.get('bitrate'):
        # Can't determine - assume not noisy (use faster encoder)
        return False, 0.0, "could not analyze"

    pixels = video_info['width'] * video_info['height']
    fps = 30  # Assume 30fps for camcorder footage

    # Bits per pixel per frame
    bpp = video_info['bitrate'] / pixels / fps

    if bpp > NOISE_THRESHOLD_BPP:
        return True, bpp, f"high complexity ({bpp:.3f} bpp > {NOISE_THRESHOLD_BPP})"
    else:
        return False, bpp, f"normal complexity ({bpp:.3f} bpp)"


def needs_conversion(file_path):
    """
    Determine if a video file needs to be converted to H.265.

    Checks the video codec and returns whether conversion is needed.
    AVCHD (.MTS/.M2TS) files always need conversion.
    Other video files are checked for their codec.

    Args:
        file_path: Path to the video file

    Returns:
        tuple: (needs_conversion: bool, reason: str)
    """
    ext = file_path.suffix.lower()

    # MTS/M2TS files are always AVCHD and need conversion
    if ext in {'.mts', '.m2ts'}:
        return True, "AVCHD format"

    # For other formats, check the codec
    codec = get_video_codec(file_path)

    if codec is None:
        return False, "could not detect codec"

    if codec in SKIP_CODECS:
        return False, f"already {codec.upper()}"

    if codec in CONVERT_CODECS:
        return True, f"{codec.upper()} codec"

    # Unknown codec - skip to be safe
    return False, f"unknown codec ({codec})"


# ============================================================================
# VIDEO CONVERSION
# ============================================================================

def convert_to_h265(input_path, output_path, creation_date=None, dry_run=False,
                   crf=FFMPEG_CRF, preset=FFMPEG_PRESET):
    """
    Convert video to H.265/HEVC using libx265 for archival quality.

    Uses software encoding (libx265) rather than hardware (VideoToolbox)
    for better compression ratios and quality, at the cost of encoding speed.
    Threading is configured to use all available CPU cores.

    Args:
        input_path: Path to source .MTS file
        output_path: Path for output .h265.mp4 file
        creation_date: Optional datetime to embed as creation timestamp
        dry_run: If True, show command but don't execute
        crf: H.265 CRF value (lower = better quality)
        preset: x265 encoding preset

    Returns:
        bool: True if successful, False otherwise
    """
    # Build ffmpeg command
    # -movflags +faststart: Moves moov atom to beginning for streaming
    # -tag:v hvc1: Apple-compatible HEVC tag for QuickTime/Safari
    # x265-params pools/frame-threads: Use all CPU cores for encoding
    cmd = [
        'ffmpeg',
        '-i', str(input_path),
        '-c:v', 'libx265',
        '-crf', str(crf),
        '-preset', preset,
        '-x265-params', 'pools=*:frame-threads=0',  # Auto-detect optimal threading
        '-tag:v', 'hvc1',
        '-c:a', 'aac',
        '-b:a', FFMPEG_AUDIO_BITRATE,
        '-movflags', '+faststart',
    ]

    # Embed creation date in output metadata if available
    if creation_date:
        # FFmpeg expects ISO format for metadata
        date_str = creation_date.strftime("%Y-%m-%dT%H:%M:%S")
        cmd.extend(['-metadata', f'creation_time={date_str}'])

    # Don't prompt for overwrite, log level warning only
    cmd.extend(['-n', '-loglevel', 'warning', '-stats'])
    cmd.append(str(output_path))

    if dry_run:
        print(f"    [DRY RUN] Would execute: {' '.join(cmd)}")
        return True

    try:
        print(f"    Converting with libx265 (CRF {crf}, preset {preset})...")
        result = subprocess.run(cmd, check=False)

        if result.returncode != 0:
            print(f"    ERROR: ffmpeg conversion failed (exit code {result.returncode})")
            return False

        return True

    except FileNotFoundError:
        print("  ERROR: ffmpeg not found. Please install: brew install ffmpeg")
        sys.exit(1)
    except Exception as e:
        print(f"    ERROR: Conversion failed: {e}")
        return False


def convert_to_h265_videotoolbox(input_path, output_path, creation_date=None, dry_run=False):
    """
    Convert video to H.265/HEVC using Apple VideoToolbox hardware encoding.

    Uses hardware encoding for dramatically faster conversion (~10x faster than libx265)
    with good quality for clean video content. Less effective on noisy/grainy footage.

    Args:
        input_path: Path to source video file
        output_path: Path for output .h265.mp4 file
        creation_date: Optional datetime to embed as creation timestamp
        dry_run: If True, show command but don't execute

    Returns:
        bool: True if successful, False otherwise
    """
    # Build ffmpeg command
    # -q:v 50: Quality setting (0-100, higher = better quality)
    # -tag:v hvc1: Apple-compatible HEVC tag for QuickTime/Safari
    cmd = [
        'ffmpeg',
        '-i', str(input_path),
        '-c:v', 'hevc_videotoolbox',
        '-q:v', '50',
        '-tag:v', 'hvc1',
        '-c:a', 'aac',
        '-b:a', FFMPEG_AUDIO_BITRATE,
        '-movflags', '+faststart',
    ]

    # Embed creation date in output metadata if available
    if creation_date:
        date_str = creation_date.strftime("%Y-%m-%dT%H:%M:%S")
        cmd.extend(['-metadata', f'creation_time={date_str}'])

    # Don't prompt for overwrite, log level warning only
    cmd.extend(['-n', '-loglevel', 'warning', '-stats'])
    cmd.append(str(output_path))

    if dry_run:
        print(f"    [DRY RUN] Would execute: {' '.join(cmd)}")
        return True

    try:
        print("    Converting with VideoToolbox (hardware accelerated)...")
        result = subprocess.run(cmd, check=False)

        if result.returncode != 0:
            print(f"    ERROR: ffmpeg conversion failed (exit code {result.returncode})")
            return False

        return True

    except FileNotFoundError:
        print("  ERROR: ffmpeg not found. Please install: brew install ffmpeg")
        sys.exit(1)
    except Exception as e:
        print(f"    ERROR: Conversion failed: {e}")
        return False


def apply_exif_date(file_path, creation_date, dry_run=False):
    """
    Write creation date to output file's EXIF and filesystem metadata.

    Ensures the date is preserved in:
    1. EXIF metadata (CreateDate, ModifyDate, MediaCreateDate, etc.)
    2. Filesystem modification time (for Finder display)

    Args:
        file_path: Path to the video file
        creation_date: datetime to write
        dry_run: If True, skip actual write

    Returns:
        bool: True if successful
    """
    if dry_run:
        print(f"    [DRY RUN] Would write EXIF date: {creation_date}")
        return True

    exif_date = creation_date.strftime("%Y:%m:%d %H:%M:%S")

    try:
        # Write EXIF metadata
        result = subprocess.run(
            [
                'exiftool', '-overwrite_original', '-q',
                f'-DateTimeOriginal={exif_date}',
                f'-CreateDate={exif_date}',
                f'-ModifyDate={exif_date}',
                f'-MediaCreateDate={exif_date}',
                f'-MediaModifyDate={exif_date}',
                str(file_path)
            ],
            capture_output=True,
            text=True,
            check=False
        )

        exif_success = result.returncode == 0

        # Set filesystem modification time for Finder display
        timestamp = creation_date.timestamp()
        os.utime(str(file_path), (timestamp, timestamp))

        return exif_success

    except Exception as e:
        print(f"    Warning: Could not write EXIF date: {e}")
        return False


# ============================================================================
# FILE ORGANIZATION
# ============================================================================

def get_output_filename(creation_date, suffix="_CAM.h265.mp4"):
    """
    Generate output filename from creation date.

    Format: YYYYMMDD_HHMMSS_CAM.h265.mp4
    The _CAM suffix distinguishes camcorder-sourced videos from phone/Takeout videos.

    Args:
        creation_date: datetime object
        suffix: File suffix (default: "_CAM.h265.mp4")

    Returns:
        str: Formatted filename
    """
    return creation_date.strftime("%Y%m%d_%H%M%S") + suffix


def get_destination_folder(creation_date):
    """
    Determine destination folder based on creation date.

    Structure: Organized_Videos/YYYY/MM MonthName/

    Args:
        creation_date: datetime object

    Returns:
        Path: Destination directory
    """
    year = creation_date.year
    month_folder = MONTH_NAMES[creation_date.month - 1]

    return VIDEO_OUTPUT_DIR / str(year) / month_folder


def check_duplicate(filename, file_index):
    """
    Check if a file with this name already exists in organized folders.

    Args:
        filename: The target filename (e.g., "20240504_113916.h265.mp4")
        file_index: Index from build_file_index()

    Returns:
        Path if duplicate exists, None otherwise
    """
    # Extract base name without suffix for index lookup
    # "20240504_113916.h265.mp4" -> base="20240504_113916.h265", ext=".mp4"
    stem = Path(filename).stem  # "20240504_113916.h265"
    ext = Path(filename).suffix.lower()  # ".mp4"

    # Index key format: (base_name, ext, is_edited)
    index_key = (stem, ext, False)

    if index_key in file_index:
        return file_index[index_key][0]

    return None


def find_existing_by_date(creation_date, original_size, file_index):
    """
    Find existing files in organized folders that match the creation date.

    Handles multiple naming conventions:
    - Camcorder format: YYYYMMDD_HHMMSS.h265.mp4
    - Takeout format: VID_YYYYMMDD_HHMMSSMMM_PersonName.mp4

    Uses date+size matching for content identification, with tolerance for
    size differences (same date, similar size = likely same content).

    Args:
        creation_date: datetime of the source file
        original_size: Size of source file in bytes
        file_index: Index from build_file_index()

    Returns:
        tuple: (existing_path, already_h265) or (None, False) if no match
               existing_path: Path to the matching file
               already_h265: True if the existing file is already H.265 encoded
    """
    # Build date patterns to search for
    # Camcorder: 20260109_210429 or 20260109_210429_CAM
    date_prefix = creation_date.strftime("%Y%m%d_%H%M%S")
    # Takeout: VID_20260109_210429 (plus milliseconds, but we match prefix)
    takeout_prefix = f"VID_{creation_date.strftime('%Y%m%d_%H%M%S')}"

    # Size tolerance: 5% to account for minor metadata differences
    # (same content from different sources might have slight size variations)
    size_tolerance = 0.05
    min_size = original_size * (1 - size_tolerance)
    max_size = original_size * (1 + size_tolerance)

    # Search the file index for matching patterns
    for (base_name, ext, is_edited), paths in file_index.items():
        # Skip edited versions
        if is_edited:
            continue

        # Skip non-video extensions
        if ext not in {'.mp4', '.mov', '.m4v'}:
            continue

        # Check if filename matches either date pattern
        matches_camcorder = base_name.startswith(date_prefix)
        matches_takeout = base_name.startswith(takeout_prefix)

        if not (matches_camcorder or matches_takeout):
            continue

        # Found a date match - check the file
        existing_path = paths[0]

        if not existing_path.exists():
            continue

        # Check size similarity (for same-content detection)
        existing_size = existing_path.stat().st_size

        # If it's already an H.265 file, size will be smaller - skip size check for those
        is_h265 = '.h265' in base_name.lower() or base_name.lower().endswith('.hevc')

        if is_h265:
            # Already converted - this is a match regardless of size
            return existing_path, True

        # For non-H.265, check size similarity
        if min_size <= existing_size <= max_size:
            # Same date, similar size = same content (H.264 original from Takeout)
            return existing_path, False

    return None, False


def move_to_destination(file_path, dest_folder, filename, dry_run=False):
    """
    Move converted file to its destination folder.

    Creates destination directory if needed. Handles filename collisions
    by appending a counter.

    Args:
        file_path: Current path of the converted file
        dest_folder: Target directory
        filename: Target filename
        dry_run: If True, don't actually move

    Returns:
        Path: Final destination path, or None if failed
    """
    if dry_run:
        dest_path = dest_folder / filename
        print(f"    [DRY RUN] Would move to: {dest_path}")
        return dest_path

    try:
        dest_folder.mkdir(parents=True, exist_ok=True)
        dest_path = dest_folder / filename

        # Handle collision
        if dest_path.exists():
            stem = Path(filename).stem
            ext = Path(filename).suffix
            counter = 1

            while dest_path.exists():
                new_name = f"{stem}_{counter}{ext}"
                dest_path = dest_folder / new_name
                counter += 1

            print(f"    Collision resolved: {filename} -> {dest_path.name}")

        shutil.move(str(file_path), str(dest_path))
        return dest_path

    except Exception as e:
        print(f"    ERROR: Could not move file: {e}")
        return None


# ============================================================================
# MAIN PROCESSING
# ============================================================================

def scan_video_files(input_dir):
    """
    Scan directory for all video files that might need conversion.

    Scans for both AVCHD files (.MTS/.M2TS) and standard video formats.
    Codec detection happens during processing to determine if conversion is needed.

    Args:
        input_dir: Directory to scan (recursively)

    Returns:
        list: Sorted list of Path objects for video files
    """
    files = []

    # Scan for all video extensions (AVCHD + standard formats)
    for ext in ALL_VIDEO_EXTENSIONS:
        files.extend(input_dir.rglob(f"*{ext}"))

    # Sort by name for predictable processing order
    return sorted(files, key=lambda p: p.name.lower())


def process_file(file_path, file_index, conversion_index, dry_run=False, keep_original=False,
                 crf=FFMPEG_CRF, preset=FFMPEG_PRESET, force_software=False):
    """
    Process a single video file: check codec, extract date, convert if needed, organize.

    Automatically selects encoder based on video complexity:
    - Noisy/grainy videos use libx265 (better quality preservation)
    - Clean videos use VideoToolbox (faster with similar quality)

    Args:
        file_path: Path to video file
        file_index: In-memory index for filename-based duplicate detection
        conversion_index: Persistent index for content-based deduplication (date+size)
        dry_run: If True, don't make changes
        keep_original: If True, don't delete source after conversion
        crf: H.265 CRF value for libx265 encoding
        preset: x265 encoding preset
        force_software: If True, always use libx265 regardless of noise detection

    Returns:
        tuple: (result: str, output_path: Path or None, creation_date: datetime or None, encoder_info: dict or None)
        result is one of: 'converted', 'skipped_codec', 'skipped_indexed', 'skipped_duplicate', 'failed'
        encoder_info contains: {'encoder': 'libx265'|'videotoolbox', 'duration': float, 'bpp': float}
    """
    print(f"\n  Processing: {file_path.name}")

    # Step 0: Check if conversion is needed based on codec
    should_convert, reason = needs_conversion(file_path)

    if not should_convert:
        print(f"    SKIPPED: {reason}")
        return 'skipped_codec', None, None, None

    print(f"    Needs conversion: {reason}")
    original_size = file_path.stat().st_size  # bytes for index
    original_size_mb = original_size / (1024 * 1024)
    print(f"    Original size: {original_size_mb:.1f} MB")

    # Step 0.5: Analyze video complexity for encoder selection
    video_info = get_video_info(file_path)
    is_noisy, bpp, noise_reason = is_noisy_video(file_path, video_info)
    duration = video_info.get('duration', 0) if video_info else 0

    if force_software:
        use_software = True
        encoder_name = 'libx265'
        print(f"    Encoder: libx265 (forced)")
    elif is_noisy:
        use_software = True
        encoder_name = 'libx265'
        print(f"    Encoder: libx265 ({noise_reason})")
    else:
        use_software = False
        encoder_name = 'videotoolbox'
        print(f"    Encoder: VideoToolbox ({noise_reason})")

    # Build encoder_info for statistics tracking
    encoder_info = {
        'encoder': encoder_name,
        'duration': duration,
        'bpp': bpp,
        'size_mb': original_size_mb
    }

    # Step 1: Extract creation date
    creation_date, date_source = get_creation_date(file_path)

    if not creation_date:
        print("    ERROR: Could not determine creation date. Skipping.")
        return 'failed', None, None, encoder_info

    print(f"    Creation date: {creation_date} (from {date_source})")

    # Step 1.5: Check persistent index for content-based duplicate
    # This catches the same video from different backup sources
    existing_entry = lookup_in_index(conversion_index, creation_date, original_size)

    if existing_entry:
        print(f"    SKIPPED: Already converted (from {existing_entry['original_name']})")
        print(f"             Output: {existing_entry['output_path']}")
        return 'skipped_indexed', Path(VIDEO_OUTPUT_DIR) / existing_entry['output_path'], creation_date, None

    # Step 1.6: Check for existing content by date+size in organized folders
    # This catches videos processed by Takeout workflow (different naming pattern)
    existing_by_date, already_h265 = find_existing_by_date(creation_date, original_size, file_index)

    if existing_by_date:
        if already_h265:
            print(f"    SKIPPED: Already exists as H.265 -> {existing_by_date.name}")
            return 'skipped_duplicate', existing_by_date, creation_date, None
        else:
            # H.264 original exists from Takeout - could convert, but it's the same content
            print(f"    SKIPPED: Same content already organized -> {existing_by_date.name}")
            print(f"             (Run separately on Organized_Videos/ to convert existing H.264 files)")
            return 'skipped_duplicate', existing_by_date, creation_date, None

    # Step 2: Generate output filename and check for filename duplicates
    output_filename = get_output_filename(creation_date)
    dest_folder = get_destination_folder(creation_date)

    existing = check_duplicate(output_filename, file_index)

    if existing:
        print(f"    SKIPPED: Already processed -> {existing}")
        return 'skipped_duplicate', existing, creation_date, None

    # Step 3: Convert to H.265
    # Create temp output in same directory as source
    temp_output = file_path.parent / output_filename

    if temp_output.exists() and not dry_run:
        print(f"    Temp output exists, removing: {temp_output}")
        temp_output.unlink()

    start_time = time.time()

    # Select encoder based on video complexity analysis
    if use_software:
        success = convert_to_h265(file_path, temp_output, creation_date, dry_run,
                                  crf=crf, preset=preset)
    else:
        success = convert_to_h265_videotoolbox(file_path, temp_output, creation_date, dry_run)

    if not success:
        return 'failed', None, creation_date, encoder_info

    if not dry_run:
        elapsed = time.time() - start_time
        new_size = temp_output.stat().st_size / (1024 * 1024)
        compression = (1 - new_size / original_size_mb) * 100
        print(f"    Converted: {new_size:.1f} MB ({compression:.1f}% smaller) in {elapsed:.1f}s")

    # Step 4: Write EXIF metadata
    if not dry_run:
        apply_exif_date(temp_output, creation_date)

    # Step 5: Move to destination
    final_path = move_to_destination(temp_output, dest_folder, output_filename, dry_run)

    if not final_path:
        return 'failed', None, creation_date, encoder_info

    # Step 6: Add to persistent index for future deduplication
    if not dry_run:
        # Store relative path from Organized_Videos for portability
        relative_output = final_path.relative_to(VIDEO_OUTPUT_DIR)
        add_to_index(conversion_index, creation_date, original_size, file_path, relative_output)

    # Step 7: Delete original if requested
    if not keep_original and not dry_run:
        try:
            file_path.unlink()
            print(f"    Deleted original: {file_path.name}")
        except Exception as e:
            print(f"    Warning: Could not delete original: {e}")

    return 'converted', final_path, creation_date, encoder_info


# ============================================================================
# DIRECT EXECUTION (for testing)
# ============================================================================

if __name__ == "__main__":
    """
    Direct execution mode for testing. For full workflow with user prompts,
    timing, and summary statistics, use workflow_camcorder.py instead.
    """
    # Simple test: process a single file or directory
    if len(sys.argv) < 2:
        print("Usage: python3 camcorder_convert.py <file_or_directory>")
        print("\nFor full workflow with prompts and summary, use:")
        print("  python3 workflow_camcorder.py")
        sys.exit(1)

    target = Path(sys.argv[1])

    if not target.exists():
        print(f"ERROR: Not found: {target}")
        sys.exit(1)

    # Build indexes
    file_index = build_file_index(video_dir=VIDEO_OUTPUT_DIR)
    conversion_index = load_index()

    if target.is_file():
        # Process single file
        result, output, _, encoder_info = process_file(target, file_index, conversion_index,
                                          dry_run=False, keep_original=True)
        print(f"\nResult: {result}")

        if output:
            print(f"Output: {output}")

        save_index(conversion_index)

    else:
        # Process directory
        files = scan_video_files(target)
        print(f"Found {len(files)} video files")

        for file_path in files:
            result, output, _, encoder_info = process_file(file_path, file_index, conversion_index,
                                              dry_run=False, keep_original=True)
            print(f"  {file_path.name}: {result}")

        save_index(conversion_index)
