#!/usr/bin/env python3 -u
"""
Photo Triage Tool

Intelligent photo organization that provides context for batch decisions.
Uses analysis from analyze_photo_quality.py to identify candidates,
then groups them with surrounding photos for informed review.

Key insight: A blurry photo can be deleted if a sharp version from the
same moment exists. This tool surfaces that context automatically.

Use cases:
- Review blurry photos alongside their burst-mates
- Identify and handle exact duplicates with undo capability
- Summarize issues by folder for quick scanning
- Auto-triage high-confidence cases (very blurry, exact dupes)

Usage:
    # Analyze and show summary by folder
    python3 photo_triage.py summary Organized_Photos/

    # Show blurry photos with context (surrounding photos)
    python3 photo_triage.py blurry Organized_Photos/ --with-context

    # Auto-move high-confidence issues to review folder
    python3 photo_triage.py auto-triage Organized_Photos/ --dry-run

    # Undo previous auto-triage moves
    python3 photo_triage.py undo --manifest .triage_manifest.json
"""

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta
from multiprocessing import cpu_count
from pathlib import Path

# ============================================================================
# CONFIGURATION
# ============================================================================

# Import from analyze_photo_quality for consistency
try:
    from analyze_photo_quality import (
        ANALYSIS_CACHE_FILE,
        BLUR_THRESHOLD_BLURRY,
        BLUR_THRESHOLD_VERY_BLURRY,
        calculate_blur_score,
        calculate_edge_density,
        get_analysis_cache,
        IMAGE_EXTENSIONS,
        interpret_blur_score,
        is_photo_blurry,
        LOW_TEXTURE_EDGE_DENSITY,
        MAX_PARALLEL_WORKERS,
        OPENCV_AVAILABLE,
        read_image_opencv,
        save_all_caches,
        scan_for_duplicates,
    )
except ImportError:
    print("ERROR: analyze_photo_quality.py must be in the same directory")
    sys.exit(1)

# Triage settings
BURST_WINDOW_SECONDS = 5  # Photos within this window are considered a burst
VERY_BLURRY_THRESHOLD = 30  # Auto-triage threshold (stricter than "blurry")
SHARP_NEIGHBOR_MAX_SECONDS = 300  # 5 minutes - sharp photos farther than this don't count as neighbors
MANIFEST_FILE = ".triage_manifest.json"

# Review folder structure
REVIEW_BASE = "_TO_REVIEW_"
REVIEW_BLURRY = "Blurry"
REVIEW_DUPLICATES = "Duplicates"

# Default directory (relative to script location)
DEFAULT_DIRECTORY = "Organized_Photos"

# Progress logging interval
PROGRESS_INTERVAL = 100  # Log every N photos processed


def get_exif_date(file_path):
    """
    Read the EXIF DateTimeOriginal from a photo file, using persistent cache.

    Checks the per-directory analysis cache first (populated by batch_extract_exif_dates
    or previous runs). Falls back to single-file exiftool call if not cached.

    Args:
        file_path: Path to the photo file

    Returns:
        datetime if found, None otherwise
    """
    file_path = Path(file_path)

    # Check persistent analysis cache first
    cache = get_analysis_cache(file_path.parent)
    cached_ts = cache.get_exif_date(file_path)

    if cached_ts is not None:
        # 0 means "checked but no EXIF date found"
        if cached_ts == 0:
            return None
        return datetime.fromtimestamp(cached_ts)

    # Single-file fallback (should rarely be used if batch extraction runs first)
    try:
        result = subprocess.run(
            ['exiftool', '-DateTimeOriginal', '-CreateDate', '-s', '-s', '-s', str(file_path)],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            cache.set_exif_date(file_path, 0)  # Mark as "no EXIF date"
            return None

        # exiftool outputs one date per line; we prefer DateTimeOriginal, then CreateDate
        lines = result.stdout.strip().split('\n')

        for line in lines:
            if not line.strip():
                continue

            # Parse EXIF date format: "YYYY:MM:DD HH:MM:SS"
            try:
                dt = datetime.strptime(line.strip(), '%Y:%m:%d %H:%M:%S')
                cache.set_exif_date(file_path, dt.timestamp())
                return dt
            except ValueError:
                continue

        cache.set_exif_date(file_path, 0)  # Mark as "no EXIF date"
        return None

    except (subprocess.TimeoutExpired, FileNotFoundError):
        cache.set_exif_date(file_path, 0)
        return None


def batch_extract_exif_dates(photo_paths, show_progress=True):
    """
    Extract EXIF dates for multiple photos using batch exiftool calls.

    Uses the persistent per-directory analysis cache. On subsequent runs,
    already-cached photos are skipped entirely, making re-runs nearly instant.

    This is MUCH faster than calling exiftool once per file. A single exiftool
    process reading 500 files is ~100x faster than 500 separate processes.

    Args:
        photo_paths: List of Path objects to extract dates from
        show_progress: Whether to print progress updates

    Returns:
        Dict mapping path string to timestamp (or 0 if no EXIF date)
    """
    if not photo_paths:
        return {}

    # Group photos by directory for cache access
    by_directory = {}
    for p in photo_paths:
        p = Path(p)
        dir_key = str(p.parent)
        if dir_key not in by_directory:
            by_directory[dir_key] = []
        by_directory[dir_key].append(p)

    # Check persistent cache for each photo
    uncached = []
    cached_count = 0

    for dir_path, photos in by_directory.items():
        cache = get_analysis_cache(dir_path)
        for p in photos:
            if cache.get_exif_date(p) is None:
                uncached.append(p)
            else:
                cached_count += 1

    if not uncached:
        if show_progress:
            print(f"    All {len(photo_paths)} photos already in persistent cache")
        return {}

    if show_progress:
        if cached_count > 0:
            print(f"    {cached_count} photos already cached, extracting EXIF for {len(uncached)}...", flush=True)
        else:
            print(f"    Extracting EXIF dates for {len(uncached)} photos...", flush=True)

    results = {}

    # Process in batches to avoid command line length limits and show progress
    BATCH_SIZE = 500
    total_batches = (len(uncached) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_idx in range(total_batches):
        batch_start = batch_idx * BATCH_SIZE
        batch_end = min(batch_start + BATCH_SIZE, len(uncached))
        batch = uncached[batch_start:batch_end]

        if show_progress and total_batches > 1:
            print(f"      Batch {batch_idx + 1}/{total_batches} ({batch_end}/{len(uncached)} photos)...", flush=True)

        try:
            # Use JSON output for reliable parsing of multiple files
            cmd = ['exiftool', '-json', '-DateTimeOriginal', '-CreateDate'] + [str(p) for p in batch]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120  # 2 minutes for batch
            )

            if result.returncode == 0 and result.stdout.strip():
                import json
                try:
                    data = json.loads(result.stdout)
                    for item in data:
                        source_file = item.get('SourceFile', '')
                        source_path = Path(source_file)
                        date_str = item.get('DateTimeOriginal') or item.get('CreateDate')

                        cache = get_analysis_cache(source_path.parent)

                        if date_str and date_str != '0000:00:00 00:00:00':
                            try:
                                dt = datetime.strptime(date_str, '%Y:%m:%d %H:%M:%S')
                                timestamp = dt.timestamp()
                                results[source_file] = timestamp
                                cache.set_exif_date(source_path, timestamp)
                            except ValueError:
                                results[source_file] = 0
                                cache.set_exif_date(source_path, 0)
                        else:
                            results[source_file] = 0
                            cache.set_exif_date(source_path, 0)
                except json.JSONDecodeError:
                    # Fall back to marking all as "no date"
                    for p in batch:
                        results[str(p)] = 0
                        cache = get_analysis_cache(p.parent)
                        cache.set_exif_date(p, 0)
            else:
                # exiftool failed, mark all as "no date"
                for p in batch:
                    results[str(p)] = 0
                    cache = get_analysis_cache(p.parent)
                    cache.set_exif_date(p, 0)

        except subprocess.TimeoutExpired:
            print(f"      Warning: EXIF batch {batch_idx + 1} timed out", flush=True)
            for p in batch:
                results[str(p)] = 0
                cache = get_analysis_cache(p.parent)
                cache.set_exif_date(p, 0)
        except FileNotFoundError:
            print("      Warning: exiftool not found, skipping EXIF extraction", flush=True)
            for p in batch:
                results[str(p)] = 0
                cache = get_analysis_cache(p.parent)
                cache.set_exif_date(p, 0)
            break

    if show_progress:
        with_dates = sum(1 for v in results.values() if v > 0)
        print(f"    Found EXIF dates for {with_dates}/{len(uncached)} photos", flush=True)

    return results


def find_default_directory():
    """
    Find the default Organized_Photos directory.

    Checks:
    1. ./Organized_Photos (relative to cwd)
    2. ../Organized_Photos (one level up)
    3. Script directory / Organized_Photos

    Returns:
        Path or None if not found
    """
    candidates = [
        Path.cwd() / DEFAULT_DIRECTORY,
        Path.cwd().parent / DEFAULT_DIRECTORY,
        Path(__file__).parent / DEFAULT_DIRECTORY,
    ]

    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate

    return None


def find_review_base(directory):
    """
    Find the appropriate review base directory.

    Walks up the directory tree looking for:
    1. An existing _TO_REVIEW_ folder
    2. A directory that looks like "Organized_Photos" (contains year folders)

    Args:
        directory: Starting directory

    Returns:
        Path: The review base directory (e.g., Organized_Photos/_TO_REVIEW_/)
    """
    directory = Path(directory).resolve()

    # Walk up looking for existing _TO_REVIEW_ or a root with year folders
    current = directory

    while current != current.parent:
        # Check if _TO_REVIEW_ already exists here
        review_path = current / REVIEW_BASE

        if review_path.exists():
            return review_path

        # Check if this looks like the organized photos root (has year folders)
        children = [c.name for c in current.iterdir() if c.is_dir()]
        year_folders = [c for c in children if c.isdigit() and len(c) == 4]

        if year_folders:
            # This is likely the root - use _TO_REVIEW_ here
            return current / REVIEW_BASE

        current = current.parent

    # Fallback: use the original directory
    return directory / REVIEW_BASE


# ============================================================================
# TIMESTAMP EXTRACTION
# ============================================================================

def extract_timestamp_from_filename(filename):
    """
    Extract datetime from common filename patterns.

    Patterns supported:
        IMG_20180404_191624402.jpg
        VID_20210526_162641.mp4
        PXL_20210526_162641123.jpg
        20180404_191624.jpg
        2018-04-04_19-16-24.jpg

    Args:
        filename: Filename (not full path)

    Returns:
        datetime or None if no pattern matches
    """
    stem = Path(filename).stem

    patterns = [
        # IMG_20180404_191624402 or VID_20210526_162641 or PXL_20210526_162641123
        (r'(?:IMG|VID|PXL)_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})', '%Y%m%d_%H%M%S'),
        # 20180404_191624
        (r'^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})', '%Y%m%d_%H%M%S'),
        # 2018-04-04_19-16-24 or 2018-04-04-19-16-24
        (r'(\d{4})-(\d{2})-(\d{2})[-_](\d{2})-(\d{2})-(\d{2})', '%Y-%m-%d_%H-%M-%S'),
    ]

    for pattern, _ in patterns:
        match = re.search(pattern, stem)

        if match:
            try:
                groups = match.groups()
                dt = datetime(
                    int(groups[0]), int(groups[1]), int(groups[2]),
                    int(groups[3]), int(groups[4]), int(groups[5])
                )
                return dt
            except (ValueError, IndexError):
                continue

    return None


# ============================================================================
# BURST DETECTION
# ============================================================================

def detect_bursts(image_paths, window_seconds=BURST_WINDOW_SECONDS):
    """
    Group photos taken within a time window into bursts.

    Args:
        image_paths: List of image file paths
        window_seconds: Max seconds between photos in same burst

    Returns:
        list: List of burst groups, each is list of (path, timestamp, blur_score)
    """
    # Extract timestamps and blur scores
    photos = []

    for path in image_paths:
        path = Path(path)
        timestamp = extract_timestamp_from_filename(path.name)

        if timestamp:
            blur = calculate_blur_score(path)
            photos.append({
                'path': path,
                'timestamp': timestamp,
                'blur': blur
            })

    # Sort by timestamp
    photos.sort(key=lambda x: x['timestamp'])

    # Group into bursts
    bursts = []
    current_burst = []

    for photo in photos:
        if not current_burst:
            current_burst.append(photo)
        else:
            time_diff = (photo['timestamp'] - current_burst[-1]['timestamp']).total_seconds()

            if time_diff <= window_seconds:
                current_burst.append(photo)
            else:
                if len(current_burst) > 1:
                    bursts.append(current_burst)

                current_burst = [photo]

    # Don't forget last burst
    if len(current_burst) > 1:
        bursts.append(current_burst)

    return bursts


def analyze_burst(burst):
    """
    Analyze a burst to find best and worst photos.

    Args:
        burst: List of photo dicts with 'path', 'timestamp', 'blur'

    Returns:
        dict: Analysis with 'best', 'worst', 'deletable' recommendations
    """
    # Sort by blur score (highest = sharpest)
    sorted_burst = sorted(burst, key=lambda x: x['blur'] or 0, reverse=True)

    best = sorted_burst[0]
    worst = sorted_burst[-1]

    # Deletable: very blurry AND a sharp version exists in burst
    deletable = []

    if best['blur'] and best['blur'] >= BLUR_THRESHOLD_BLURRY:
        # We have at least one sharp photo
        for photo in sorted_burst[1:]:  # Skip the best
            if photo['blur'] and photo['blur'] < VERY_BLURRY_THRESHOLD:
                deletable.append(photo)

    return {
        'photos': burst,
        'best': best,
        'worst': worst,
        'deletable': deletable,
        'count': len(burst)
    }


# ============================================================================
# CONTEXT-AWARE BLURRY PHOTO REVIEW
# ============================================================================

def get_surrounding_photos(blurry_path, all_photos, count=3, blur_cache=None, max_seconds=300):
    """
    Get photos taken around the same time as a blurry photo.

    Args:
        blurry_path: Path to the blurry photo
        all_photos: List of all photo paths in same directory
        count: Number of surrounding photos to return on each side
        blur_cache: Optional dict of path -> blur score to avoid recomputation
        max_seconds: Maximum time difference in seconds (default: 300 = 5 minutes)

    Returns:
        list: Surrounding photos with blur scores and position (before/after)
    """
    blurry_path = Path(blurry_path)
    blurry_ts = extract_timestamp_from_filename(blurry_path.name)

    if not blurry_ts:
        return []

    # Get timestamps for all photos
    photos_with_ts = []

    for path in all_photos:
        path = Path(path)

        if path == blurry_path:
            continue

        ts = extract_timestamp_from_filename(path.name)

        if ts:
            # Calculate signed difference (negative = before, positive = after)
            diff = (ts - blurry_ts).total_seconds()
            abs_diff = abs(diff)

            # Skip photos outside the time window
            if abs_diff > max_seconds:
                continue

            photos_with_ts.append({
                'path': path,
                'timestamp': ts,
                'diff': diff,
                'abs_diff': abs_diff
            })

    # Sort by absolute time difference
    photos_with_ts.sort(key=lambda x: x['abs_diff'])

    # Get closest photos
    surrounding = []

    for photo in photos_with_ts[:count * 2]:
        # Use cache if available, otherwise compute
        if blur_cache and photo['path'] in blur_cache:
            blur = blur_cache[photo['path']]
        else:
            blur = calculate_blur_score(photo['path'])

        surrounding.append({
            'path': photo['path'],
            'timestamp': photo['timestamp'],
            'blur': blur,
            'interpretation': interpret_blur_score(blur),
            'diff_seconds': photo['abs_diff'],
            'position': 'before' if photo['diff'] < 0 else 'after'
        })

    return surrounding


def _compute_blur_with_texture(file_path):
    """
    Worker function to compute blur score and edge density for a single image.

    Args:
        file_path: Path to image file

    Returns:
        tuple: (file_path, blur_score, edge_density) or (file_path, None, None) on error
    """
    try:
        blur, edge_density = calculate_blur_score(file_path, use_cache=False, return_texture=True)
        return (file_path, blur, edge_density)
    except Exception:
        return (file_path, None, None)


def _compute_texture_only(file_path):
    """
    Worker function to compute edge density for a single image.
    Used for texture filtering of cached blurry images.

    Args:
        file_path: Path to image file

    Returns:
        tuple: (file_path, edge_density) or (file_path, None) on error
    """
    try:
        image = read_image_opencv(file_path, grayscale=True)
        if image is not None:
            return (file_path, calculate_edge_density(image))
    except Exception:
        pass
    return (file_path, None)


def blurry_with_context(directory, blur_threshold=BLUR_THRESHOLD_BLURRY, recursive=True,
                        use_texture_filter=True):
    """
    Find blurry photos and show surrounding context using parallel processing.

    Args:
        directory: Directory to scan
        blur_threshold: Score below this is blurry
        recursive: Whether to scan subdirectories
        use_texture_filter: Skip low-texture images (walls, carpet, etc.)

    Returns:
        list: Blurry photos with their context
    """
    directory = Path(directory)
    pattern = '**/*' if recursive else '*'
    max_workers = min(cpu_count(), MAX_PARALLEL_WORKERS)

    # Group photos by directory
    photos_by_dir = defaultdict(list)

    for file_path in directory.glob(pattern):
        if file_path.suffix.lower() not in {e.lower() for e in IMAGE_EXTENSIONS}:
            continue

        if not file_path.is_file():
            continue

        # Skip symlinks to avoid duplicate processing
        if file_path.is_symlink():
            continue

        # Skip review symlink subdirectories (Blurry, Duplicates)
        if REVIEW_BLURRY in file_path.parts or REVIEW_DUPLICATES in file_path.parts:
            continue

        photos_by_dir[file_path.parent].append(file_path)

    # Count total for progress
    total_photos = sum(len(photos) for photos in photos_by_dir.values())
    total_folders = len(photos_by_dir)

    # Store blur scores and edge densities for all photos
    blur_scores = {}  # path -> blur score
    edge_densities = {}  # path -> edge density
    unreadable = []
    low_texture_skipped = 0

    print(f"\n  Scanning {total_photos} photos in {total_folders} folders for blur...", flush=True)
    print(f"  Using {max_workers} parallel workers", flush=True)

    # Phase 1: Check cache and collect uncached files
    cached_count = 0
    files_to_process = []

    for folder, photos in photos_by_dir.items():
        cache = get_analysis_cache(folder)

        for photo in photos:
            cached_blur = cache.get_blur(photo)

            if cached_blur is not None:
                blur_scores[photo] = cached_blur
                cached_count += 1
            else:
                files_to_process.append(photo)

    print(f"    Cached: {cached_count}, To process: {len(files_to_process)}", flush=True)

    # Phase 2: Process uncached files in parallel
    if files_to_process:
        processed = 0
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_compute_blur_with_texture, fp): fp for fp in files_to_process}

            for future in as_completed(futures):
                processed += 1

                if processed % 500 == 0:
                    pct = (processed / len(files_to_process)) * 100
                    print(f"    Processing: {processed}/{len(files_to_process)} ({pct:.0f}%)", flush=True)

                file_path, blur, edge_density = future.result()

                if blur is None:
                    unreadable.append(file_path)
                    continue

                blur_scores[file_path] = blur
                edge_densities[file_path] = edge_density

                # Update cache
                cache = get_analysis_cache(file_path.parent)
                cache.set_blur(file_path, blur)

        save_all_caches()

    # Phase 3: For cached blurry images, compute edge density if texture filtering
    # This is much faster than recomputing blur - just reads image and does edge detection
    if use_texture_filter:
        blurry_cached_needing_texture = [
            p for p, blur in blur_scores.items()
            if blur < blur_threshold and p not in edge_densities
        ]

        if blurry_cached_needing_texture:
            print(f"    Computing texture for {len(blurry_cached_needing_texture)} cached blurry images...", flush=True)

            processed = 0
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(_compute_texture_only, p): p for p in blurry_cached_needing_texture}

                for future in as_completed(futures):
                    processed += 1
                    if processed % 500 == 0:
                        print(f"      Texture: {processed}/{len(blurry_cached_needing_texture)}", flush=True)

                    photo, density = future.result()
                    if density is not None:
                        edge_densities[photo] = density

    # Phase 4: Build results list
    results = []

    for folder, photos in photos_by_dir.items():
        for photo in photos:
            blur = blur_scores.get(photo)

            if blur is None:
                continue

            # Skip low-texture images
            if use_texture_filter and blur < blur_threshold:
                edge_density = edge_densities.get(photo)
                if edge_density is not None and edge_density < LOW_TEXTURE_EDGE_DENSITY:
                    low_texture_skipped += 1
                    continue

            if blur < blur_threshold:
                context = get_surrounding_photos(photo, photos, count=3, blur_cache=blur_scores)

                has_sharp_neighbor = any(
                    c['blur'] and c['blur'] >= BLUR_THRESHOLD_BLURRY
                    and c.get('diff_seconds', 0) <= SHARP_NEIGHBOR_MAX_SECONDS
                    for c in context
                )

                results.append({
                    'path': photo,
                    'blur': blur,
                    'interpretation': interpret_blur_score(blur),
                    'context': context,
                    'has_sharp_neighbor': has_sharp_neighbor,
                    'safe_to_delete': blur < VERY_BLURRY_THRESHOLD and has_sharp_neighbor
                })

    print(f"    Complete: {total_photos} photos analyzed, {len(results)} blurry found", flush=True)

    if low_texture_skipped:
        print(f"    Skipped: {low_texture_skipped} low-texture images (walls/carpet/sky)")

    if unreadable:
        print(f"    Unreadable: {len(unreadable)} files could not be analyzed")

    return results, unreadable


# ============================================================================
# FOLDER SUMMARY
# ============================================================================

def summarize_by_folder(directory, recursive=True):
    """
    Generate summary of issues grouped by folder.

    Args:
        directory: Directory to analyze
        recursive: Whether to scan subdirectories

    Returns:
        dict: Summary by folder path
    """
    directory = Path(directory)
    pattern = '**/*' if recursive else '*'

    # Collect all photos by folder
    photos_by_folder = defaultdict(list)

    for file_path in directory.glob(pattern):
        if file_path.suffix.lower() not in {e.lower() for e in IMAGE_EXTENSIONS}:
            continue

        if not file_path.is_file():
            continue

        # Skip symlinks to avoid duplicate processing
        if file_path.is_symlink():
            continue

        # Skip review symlink subdirectories (Blurry, Duplicates)
        if REVIEW_BLURRY in file_path.parts or REVIEW_DUPLICATES in file_path.parts:
            continue

        rel_folder = file_path.parent.relative_to(directory)
        photos_by_folder[rel_folder].append(file_path)

    # Analyze each folder
    summaries = {}

    print(f"\nAnalyzing {len(photos_by_folder)} folders...")

    for folder, photos in sorted(photos_by_folder.items()):
        blurry = []
        very_blurry = []

        for photo in photos:
            blur = calculate_blur_score(photo)

            if blur is not None:
                if blur < VERY_BLURRY_THRESHOLD:
                    very_blurry.append(photo)
                elif blur < BLUR_THRESHOLD_BLURRY:
                    blurry.append(photo)

        # Detect bursts
        bursts = detect_bursts(photos)

        # Count deletable from bursts
        deletable_from_bursts = 0

        for burst in bursts:
            analysis = analyze_burst(burst)
            deletable_from_bursts += len(analysis['deletable'])

        summaries[str(folder)] = {
            'total': len(photos),
            'blurry': len(blurry),
            'very_blurry': len(very_blurry),
            'bursts': len(bursts),
            'burst_deletable': deletable_from_bursts
        }

    return summaries


def print_folder_summary(summaries):
    """Print formatted folder summary."""
    print(f"\n{'=' * 80}")
    print("Photo Quality Summary by Folder")
    print('=' * 80)

    # Sort by issues (most issues first)
    sorted_folders = sorted(
        summaries.items(),
        key=lambda x: x[1]['very_blurry'] + x[1]['blurry'],
        reverse=True
    )

    # Only show folders with issues
    folders_with_issues = [
        (f, s) for f, s in sorted_folders
        if s['blurry'] > 0 or s['very_blurry'] > 0 or s['burst_deletable'] > 0
    ]

    if not folders_with_issues:
        print("\n  No issues found!")
        return

    print(f"\n  {'Folder':<45} | {'Total':>6} | {'Blurry':>6} | {'V.Blur':>6} | {'Bursts':>6}")
    print(f"  {'-' * 45}-+-{'-' * 6}-+-{'-' * 6}-+-{'-' * 6}-+-{'-' * 6}")

    total_blurry = 0
    total_very_blurry = 0
    total_burst_del = 0

    for folder, stats in folders_with_issues[:30]:  # Top 30
        folder_display = str(folder)[:44]
        print(f"  {folder_display:<45} | {stats['total']:>6} | {stats['blurry']:>6} | {stats['very_blurry']:>6} | {stats['burst_deletable']:>6}")

        total_blurry += stats['blurry']
        total_very_blurry += stats['very_blurry']
        total_burst_del += stats['burst_deletable']

    if len(folders_with_issues) > 30:
        print(f"\n  ... and {len(folders_with_issues) - 30} more folders with issues")

    print(f"\n  Totals: {total_blurry} blurry, {total_very_blurry} very blurry, {total_burst_del} burst deletable")


# ============================================================================
# AUTO-TRIAGE
# ============================================================================

class TriageManifest:
    """
    Tracks all moves for undo capability.
    """

    def __init__(self, manifest_path):
        self.manifest_path = Path(manifest_path)
        self.moves = []
        self._load()

    def _load(self):
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, 'r') as f:
                    data = json.load(f)
                    self.moves = data.get('moves', [])
            except (json.JSONDecodeError, IOError):
                self.moves = []

    def save(self):
        with open(self.manifest_path, 'w') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'moves': self.moves
            }, f, indent=2)

    def record_move(self, source, destination, reason):
        self.moves.append({
            'source': str(source),
            'destination': str(destination),
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        })

    def undo_all(self, dry_run=False):
        """Undo all recorded moves."""
        undone = 0
        errors = []

        # Process in reverse order
        for move in reversed(self.moves):
            src = Path(move['destination'])
            dst = Path(move['source'])

            if not src.exists():
                errors.append(f"Source missing: {src}")
                continue

            if dst.exists():
                errors.append(f"Destination exists: {dst}")
                continue

            if dry_run:
                print(f"  [DRY RUN] Would move: {src.name} → {dst.parent}")
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                undone += 1

        return undone, errors


def auto_triage(directory, dry_run=True, manifest_path=None, review_dir=None, use_symlinks=False):
    """
    Automatically move high-confidence issues to review folders.

    High confidence = very blurry (< 30) with sharp neighbor, or exact duplicates.

    Args:
        directory: Directory to triage
        dry_run: If True, only report what would happen
        manifest_path: Path to manifest file for undo
        review_dir: Base directory for review folders (auto-detected if None)
        use_symlinks: If True, create symlinks in review folder instead of moving.
                      Keeps originals in place for context-aware review.

    Returns:
        dict: Triage results
    """
    directory = Path(directory)

    # Find or use specified review directory
    if review_dir:
        review_base = Path(review_dir)
    else:
        review_base = find_review_base(directory)

    if manifest_path is None:
        manifest_path = review_base / MANIFEST_FILE

    manifest = TriageManifest(manifest_path)

    results = {
        'total': 0,
        'blurry_moved': 0,
        'duplicates_moved': 0,
        'skipped': 0,
        'crisp_unique': 0,
        'errors': []
    }

    print(f"\n{'=' * 70}")
    print("Auto-Triage" + (" (DRY RUN)" if dry_run else ""))
    print('=' * 70)

    # Phase 1: Handle exact duplicates
    print("\n  Phase 1: Scanning for exact duplicates...", flush=True)
    dup_results = scan_for_duplicates(directory, recursive=True)

    results['total'] = dup_results['total']

    # Capture errors from duplicate scanning (files that couldn't be hashed)
    for error_path in dup_results.get('errors', []):
        results['errors'].append(f"Hash failed: {error_path}")

    for md5, paths in dup_results['exact_duplicates'].items():
        if len(paths) < 2:
            continue

        # Keep newest, move others
        paths_with_mtime = []

        for p in paths:
            try:
                mtime = Path(p).stat().st_mtime
                paths_with_mtime.append((p, mtime))
            except OSError:
                results['errors'].append(f"Cannot stat: {p}")

        paths_with_mtime.sort(key=lambda x: x[1], reverse=True)

        # First is newest (keep), rest are duplicates
        for dup_path, _ in paths_with_mtime[1:]:
            dup_path = Path(dup_path)
            dest_folder = review_base / REVIEW_DUPLICATES
            dest_path = dest_folder / dup_path.name

            # Handle name collision
            if dest_path.exists() or dest_path.is_symlink():
                stem = dest_path.stem
                suffix = dest_path.suffix
                counter = 1

                while dest_path.exists() or dest_path.is_symlink():
                    dest_path = dest_folder / f"{stem}_{counter}{suffix}"
                    counter += 1

            if dry_run:
                action = "WOULD SYMLINK" if use_symlinks else "WOULD MOVE"
                print(f"    [{action}] {dup_path.name} → {REVIEW_BASE}/{REVIEW_DUPLICATES}/")
            else:
                dest_folder.mkdir(parents=True, exist_ok=True)

                if use_symlinks:
                    # Create symlink pointing to original
                    os.symlink(str(dup_path), str(dest_path))
                    manifest.record_move(dup_path, dest_path, "exact_duplicate_symlink")
                    print(f"    [SYMLINKED] {dup_path.name} → {REVIEW_BASE}/{REVIEW_DUPLICATES}/")
                else:
                    shutil.move(str(dup_path), str(dest_path))
                    manifest.record_move(dup_path, dest_path, "exact_duplicate")
                    print(f"    [MOVED] {dup_path.name} → {REVIEW_BASE}/{REVIEW_DUPLICATES}/")

            results['duplicates_moved'] += 1

    # Phase 2: Handle very blurry with sharp neighbors
    print("\n  Phase 2: Scanning for very blurry photos with sharp alternatives...", flush=True)
    blurry_results, blur_unreadable = blurry_with_context(directory, blur_threshold=BLUR_THRESHOLD_BLURRY)

    # Capture unreadable files from blur scanning
    for unreadable_path in blur_unreadable:
        results['errors'].append(f"Unreadable: {unreadable_path}")

    for item in blurry_results:
        if not item['safe_to_delete']:
            results['skipped'] += 1
            continue

        src_path = item['path']
        dest_folder = review_base / REVIEW_BLURRY
        dest_path = dest_folder / src_path.name

        # Handle name collision (check both file and symlink)
        if dest_path.exists() or dest_path.is_symlink():
            stem = dest_path.stem
            suffix = dest_path.suffix
            counter = 1

            while dest_path.exists() or dest_path.is_symlink():
                dest_path = dest_folder / f"{stem}_{counter}{suffix}"
                counter += 1

        if dry_run:
            action = "WOULD SYMLINK" if use_symlinks else "WOULD MOVE"
            print(f"    [{action}] {src_path.name} (blur: {item['blur']:.1f}) → {REVIEW_BASE}/{REVIEW_BLURRY}/")
        else:
            dest_folder.mkdir(parents=True, exist_ok=True)

            if use_symlinks:
                # Create symlink pointing to original (file stays in place)
                os.symlink(str(src_path), str(dest_path))
                manifest.record_move(src_path, dest_path, f"very_blurry_{item['blur']:.1f}_symlink")
                print(f"    [SYMLINKED] {src_path.name} (blur: {item['blur']:.1f}) → {REVIEW_BASE}/{REVIEW_BLURRY}/")
            else:
                shutil.move(str(src_path), str(dest_path))
                manifest.record_move(src_path, dest_path, f"very_blurry_{item['blur']:.1f}")
                print(f"    [MOVED] {src_path.name} (blur: {item['blur']:.1f}) → {REVIEW_BASE}/{REVIEW_BLURRY}/")

        results['blurry_moved'] += 1

    # Save manifest
    if not dry_run:
        manifest.save()
        print(f"\n  Manifest saved to: {manifest_path}")

    # Calculate crisp/unique: total minus all issues
    results['crisp_unique'] = (
        results['total']
        - results['duplicates_moved']
        - results['blurry_moved']
        - results['skipped']
    )

    # Summary - determine action word based on mode
    if dry_run:
        action_word = "Would symlink" if use_symlinks else "Would move"
    else:
        action_word = "Symlinked" if use_symlinks else "Moved"

    print(f"\n{'-' * 50}")
    print(f"Summary ({results['total']} photos scanned)")
    print('-' * 50)
    print(f"  Crisp & unique: {results['crisp_unique']}")
    print(f"  {action_word} duplicates: {results['duplicates_moved']}")
    print(f"  {action_word} very blurry: {results['blurry_moved']}")
    print(f"  Not auto-triaged: {results['skipped']} (blurry but no sharp alternative)")
    print(f"  Errors: {len(results['errors'])}")

    # Show error details if any, grouped by extension/type
    if results['errors']:
        print("\n  Error breakdown:")
        error_summary = summarize_errors(results['errors'])

        for category, details in sorted(error_summary.items(), key=lambda x: -x[1]['count']):
            print(f"    {category}: {details['count']} files")

        # Write full error list to file for review
        error_log_path = review_base / "error_log.txt"
        with open(error_log_path, 'w') as f:
            f.write(f"Photo Triage Error Log - {datetime.now().isoformat()}\n")
            f.write(f"{'=' * 60}\n\n")

            for category, details in sorted(error_summary.items()):
                f.write(f"{category} ({details['count']} files):\n")
                for path in sorted(details['paths']):
                    f.write(f"  {path}\n")
                f.write("\n")

        print(f"\n  Full error list written to: {error_log_path}")

    if results['blurry_moved'] > 0 or results['duplicates_moved'] > 0:
        print(f"\n  Destination: {review_base}/")

    if dry_run:
        print("\n  Run without --dry-run to actually move files")

    return results


def summarize_errors(errors):
    """
    Group errors by type/extension for cleaner summary display.

    Args:
        errors: List of error strings like "Hash failed: /path/to/file.heic"

    Returns:
        dict: {category: {'count': N, 'paths': [...]}, ...}
    """
    summary = {}

    for err in errors:
        # Extract the path from error message
        if ': ' in err:
            error_type, path = err.split(': ', 1)
        else:
            error_type = "Unknown"
            path = err

        # Get file extension for grouping
        path_obj = Path(path)
        ext = path_obj.suffix.lower() if path_obj.suffix else '(no extension)'

        # Create category name
        category = f"{error_type} ({ext})"

        if category not in summary:
            summary[category] = {'count': 0, 'paths': []}

        summary[category]['count'] += 1
        summary[category]['paths'].append(path)

    return summary


# ============================================================================
# EDITED PAIR PROTECTION
# ============================================================================

# Suffixes that indicate an edited version of a photo
EDITED_SUFFIXES = ['-edited', '_edited', '-edit', '_edit', ' edited', ' (edited)']


def _is_edited_version(path):
    """Check if a filename indicates this is an edited version."""
    stem = path.stem.lower()
    return any(stem.endswith(suffix.lower()) for suffix in EDITED_SUFFIXES)


def _get_original_stem(edited_path):
    """Get the original filename stem from an edited filename."""
    stem = edited_path.stem
    for suffix in EDITED_SUFFIXES:
        if stem.lower().endswith(suffix.lower()):
            return stem[:-len(suffix)]
    return stem


def _protect_edited_pairs(candidates):
    """
    Prevent both original and -edited versions from being in high-confidence removal.

    If both versions of a file are candidates for deletion, we don't want to
    accidentally delete both. Move such pairs to needs_review instead.

    Args:
        candidates: List of candidate dicts with 'path' key

    Returns:
        tuple: (filtered_candidates, protected_items)
    """
    # Build lookup of all candidate paths
    candidate_paths = {str(c['path'].resolve()): c for c in candidates}

    # Track which items need protection
    protected_paths = set()

    for candidate in candidates:
        path = candidate['path']

        if _is_edited_version(path):
            # This is an edited file - check if original is also a candidate
            original_stem = _get_original_stem(path)

            # Look for original in same directory
            for ext in [path.suffix, '.jpg', '.JPG', '.jpeg', '.JPEG', '.png', '.PNG']:
                original_path = path.parent / f"{original_stem}{ext}"
                original_key = str(original_path.resolve())

                if original_key in candidate_paths:
                    # Both original and edited are candidates - protect both
                    protected_paths.add(str(path.resolve()))
                    protected_paths.add(original_key)
                    break
        else:
            # This is an original file - check if edited version is also a candidate
            stem = path.stem

            for suffix in EDITED_SUFFIXES:
                for ext in [path.suffix, '.jpg', '.JPG', '.jpeg', '.JPEG', '.png', '.PNG']:
                    edited_path = path.parent / f"{stem}{suffix}{ext}"
                    edited_key = str(edited_path.resolve())

                    if edited_key in candidate_paths:
                        # Both original and edited are candidates - protect both
                        protected_paths.add(str(path.resolve()))
                        protected_paths.add(edited_key)
                        break

    # Split candidates into filtered and protected
    filtered = []
    protected = []

    for candidate in candidates:
        path_key = str(candidate['path'].resolve())
        if path_key in protected_paths:
            protected.append(candidate)
        else:
            filtered.append(candidate)

    if protected:
        print(f"  Protected {len(protected)} files in edited pairs from auto-removal")

    return filtered, protected


# ============================================================================
# HTML REVIEW REPORT
# ============================================================================

def generate_html_review(directory, output_path=None, include_duplicates=True):
    """
    Generate an HTML report for visual review of blurry/duplicate candidates.

    Each candidate is shown alongside its context photos, making it easy
    to decide whether to delete based on having a sharp alternative.

    Args:
        directory: Directory to analyze
        output_path: Where to save HTML (default: _TO_REVIEW_/.TMP_review_report.html)
        include_duplicates: Whether to include duplicate detection

    Returns:
        Path: Path to generated HTML file
    """
    directory = Path(directory)
    review_base = find_review_base(directory)

    if output_path is None:
        output_path = review_base / ".TMP_review_issues.html"
    else:
        output_path = Path(output_path)

    print("\nGenerating HTML review report...")
    print(f"  Analyzing: {directory}")

    # Gather blurry photos with context
    blurry_results, _ = blurry_with_context(
        directory,
        blur_threshold=BLUR_THRESHOLD_BLURRY
    )

    # Filter to safe-to-delete candidates (very blurry with sharp neighbor)
    candidates = [r for r in blurry_results if r['safe_to_delete']]

    # IMPORTANT: Protect edited pairs - don't allow both original and -edited to be
    # in high-confidence removal. If both are blurry, move both to needs_review.
    candidates, protected = _protect_edited_pairs(candidates)

    # Also get the "needs review" ones (blurry but NOT safe to auto-delete)
    # These are either: not very blurry, or very blurry but lacking a sharp neighbor
    needs_review = [r for r in blurry_results if not r['safe_to_delete']]

    # Add protected pairs to needs_review
    needs_review.extend(protected)

    # Gather duplicates if requested
    duplicates = []
    if include_duplicates:
        print("  Scanning for duplicates...", flush=True)
        dup_results = scan_for_duplicates(directory, recursive=True)

        # Add exact duplicates (same MD5)
        for md5, paths in dup_results['exact_duplicates'].items():
            if len(paths) >= 2:
                duplicates.append({
                    'type': 'exact',
                    'md5': md5,
                    'paths': [Path(p) for p in paths]
                })

        # Add perceptually similar groups (different content, similar appearance)
        for paths in dup_results['similar_groups']:
            if len(paths) >= 2:
                duplicates.append({
                    'type': 'similar',
                    'md5': None,
                    'paths': [Path(p) for p in paths]
                })

    # Build set of all paths in duplicate groups to avoid showing them twice
    # If a photo is in a duplicate group, it shouldn't also be in blurry review
    duplicate_paths = set()
    for dup_group in duplicates:
        for p in dup_group['paths']:
            duplicate_paths.add(str(p.resolve()))

    # Filter out photos that are already in duplicate groups
    original_candidate_count = len(candidates)
    original_review_count = len(needs_review)
    candidates = [c for c in candidates if str(Path(c['path']).resolve()) not in duplicate_paths]
    needs_review = [r for r in needs_review if str(Path(r['path']).resolve()) not in duplicate_paths]

    filtered_from_candidates = original_candidate_count - len(candidates)
    filtered_from_review = original_review_count - len(needs_review)
    if filtered_from_candidates > 0 or filtered_from_review > 0:
        print(f"  Filtered {filtered_from_candidates + filtered_from_review} photos already in duplicate groups")

    print(f"  Found {len(candidates)} high-confidence removals")
    print(f"  Found {len(needs_review)} needing manual review")
    print(f"  Found {len(duplicates)} duplicate groups")

    # Generate HTML with file:// references to original images
    html = _generate_html_content(candidates, needs_review, duplicates, directory)

    # Write file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(html)

    print(f"\n  Report saved to: {output_path}")
    print("  Open in browser to review photos visually")

    return output_path


# ============================================================================
# BROWSE ALL PHOTOS - Collapsible directory view with time grouping
# ============================================================================

def generate_html_browse(directory, output_path=None):
    """
    Generate an HTML browser for ALL photos organized by directory structure.

    Unlike generate_html_review which focuses on problem photos, this shows
    every photo in a collapsible hierarchy grouped by 5-minute intervals,
    allowing batch marking of any photos for removal.

    Performance: Uses batch EXIF extraction (~100x faster than per-file calls)
    and parallel processing for large photo collections.

    Args:
        directory: Base directory to scan (e.g., Organized_Photos/)
        output_path: Where to save HTML (default: _TO_REVIEW_/.TMP_browse_all.html)

    Returns:
        Path: Path to generated HTML file
    """
    import time
    start_time = time.time()

    directory = Path(directory)
    review_base = find_review_base(directory)

    if output_path is None:
        output_path = review_base / ".TMP_browse_all.html"
    else:
        output_path = Path(output_path)

    print("\nGenerating browse-all HTML report...")
    print(f"  Scanning: {directory}")

    # Phase 1: Collect all photo directories, excluding review subdirs
    scan_start = time.time()
    photo_dirs = _collect_photo_directories(directory)
    total_photos = sum(len(d['photos']) for d in photo_dirs)
    print(f"  Found {len(photo_dirs)} directories with {total_photos:,} photos ({time.time() - scan_start:.1f}s)")

    # Phase 2: Batch extract EXIF dates for ALL photos (major performance gain)
    exif_start = time.time()
    all_photos = []
    for dir_info in photo_dirs:
        all_photos.extend(dir_info['photos'])

    batch_extract_exif_dates(all_photos, show_progress=True)
    print(f"  EXIF extraction complete ({time.time() - exif_start:.1f}s)")

    # Phase 3: Generate HTML with time grouping
    html_start = time.time()
    print("  Generating HTML...", flush=True)
    html = _generate_browse_html(photo_dirs, directory)
    print(f"  HTML generation complete ({time.time() - html_start:.1f}s)")

    # Write file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(html)

    total_time = time.time() - start_time
    print(f"\n  Report saved to: {output_path}")
    print(f"  Total time: {total_time:.1f}s ({total_photos / total_time:.0f} photos/sec)")
    print("  Open in browser to browse and mark photos for removal")

    return output_path

    return output_path


def _collect_photo_directories(base_dir):
    """
    Collect all directories containing photos, organized hierarchically.

    Excludes _TO_REVIEW_/Blurry and _TO_REVIEW_/Duplicates subdirs.

    Returns:
        List of dicts with 'path', 'photos', 'rel_path' keys, sorted by path
    """
    base_dir = Path(base_dir)
    results = []

    # Directories to skip entirely
    skip_dirs = {REVIEW_BLURRY, REVIEW_DUPLICATES}

    for root, dirs, files in os.walk(base_dir):
        root_path = Path(root)

        # Skip review subdirectories (but not _TO_REVIEW_ itself for other files)
        if root_path.name in skip_dirs and REVIEW_BASE in str(root_path):
            dirs[:] = []  # Don't descend
            continue

        # Skip hidden directories
        dirs[:] = [d for d in dirs if not d.startswith('.')]

        # Find photo files in this directory
        photos = []
        for f in files:
            if f.startswith('.'):
                continue
            ext = Path(f).suffix.lower()
            if ext in IMAGE_EXTENSIONS:
                photo_path = root_path / f
                # Skip symlinks
                if photo_path.is_symlink():
                    continue
                photos.append(photo_path)

        if photos:
            try:
                rel_path = root_path.relative_to(base_dir)
            except ValueError:
                rel_path = root_path

            results.append({
                'path': root_path,
                'rel_path': rel_path,
                'photos': sorted(photos, key=lambda p: p.name)
            })

    # Sort by path for consistent ordering
    results.sort(key=lambda x: str(x['rel_path']))
    return results


def _group_photos_by_time(photos, window_seconds=300):
    """
    Group photos by timestamp within a time window.

    Uses the persistent per-directory analysis cache (populated by batch_extract_exif_dates)
    for fast timestamp lookup. Falls back to file mtime if no EXIF date cached.

    Args:
        photos: List of Path objects
        window_seconds: Maximum gap between photos in same group (default 5 min)

    Returns:
        List of lists, each containing (photo_path, timestamp) tuples in time groups
    """
    if not photos:
        return []

    # Get timestamps for all photos using persistent cache
    photos_with_time = []
    for p in photos:
        p = Path(p)

        # Check persistent analysis cache (populated by batch_extract_exif_dates)
        cache = get_analysis_cache(p.parent)
        cached_ts = cache.get_exif_date(p)

        if cached_ts is not None and cached_ts > 0:
            timestamp = cached_ts
        else:
            # Fallback to file mtime
            try:
                timestamp = p.stat().st_mtime
            except OSError:
                timestamp = 0

        photos_with_time.append((p, timestamp))

    # Sort by timestamp
    photos_with_time.sort(key=lambda x: x[1])

    # Group by time windows
    groups = []
    current_group = []
    last_timestamp = None

    for photo, timestamp in photos_with_time:
        if last_timestamp is None or (timestamp - last_timestamp) <= window_seconds:
            current_group.append((photo, timestamp))
        else:
            if current_group:
                groups.append(current_group)
            current_group = [(photo, timestamp)]
        last_timestamp = timestamp

    if current_group:
        groups.append(current_group)

    return groups


def _generate_browse_html(photo_dirs, base_dir):
    """Generate the HTML content for the browse-all view."""

    html_parts = ['''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Photo Browser - All Photos</title>
    <style>
        * { box-sizing: border-box; }
        html { scroll-behavior: smooth; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a1a;
            color: #e0e0e0;
            margin: 0;
            padding: 20px;
            padding-top: 120px;
            padding-bottom: 80px;
        }

        /* Sticky header with view options */
        .sticky-header {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            background: #1a1a1a;
            border-bottom: 1px solid #444;
            padding: 12px 20px;
            z-index: 100;
        }
        .header-top {
            display: flex;
            align-items: center;
            gap: 20px;
            margin-bottom: 10px;
        }
        .header-top h1 {
            margin: 0;
            font-size: 1.5em;
            color: #fff;
        }
        .header-top .stats {
            color: #888;
            font-size: 0.9em;
        }
        .view-options {
            display: flex;
            align-items: center;
            gap: 20px;
            flex-wrap: wrap;
        }
        .view-option {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.85em;
        }
        .view-option label {
            color: #aaa;
        }
        .view-option input[type="range"] {
            width: 100px;
        }
        .view-option input[type="checkbox"] {
            width: 16px;
            height: 16px;
        }
        .controls {
            display: flex;
            gap: 10px;
        }
        .controls button {
            padding: 6px 12px;
            background: #444;
            color: #fff;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.85em;
        }
        .controls button:hover {
            background: #555;
        }

        /* Collapsible directory structure */
        .directory {
            margin-bottom: 10px;
            border: 1px solid #333;
            border-radius: 8px;
            overflow: hidden;
        }
        .directory-header {
            background: #2a2a2a;
            padding: 12px 16px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 10px;
            user-select: none;
        }
        .directory-header:hover {
            background: #333;
        }
        .directory-header .toggle {
            font-size: 12px;
            transition: transform 0.2s;
        }
        .directory.expanded .toggle {
            transform: rotate(90deg);
        }
        .directory-header .path {
            flex: 1;
            font-weight: 500;
        }
        .directory-header .count {
            color: #888;
            font-size: 0.9em;
        }
        .directory-content {
            display: none;
            padding: 16px;
            background: #222;
        }
        .directory.expanded .directory-content {
            display: block;
        }

        /* Time groups within directory */
        .time-group {
            margin-bottom: 20px;
            padding: 12px;
            background: #2a2a2a;
            border-radius: 6px;
        }
        .time-group-header {
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 0.85em;
            color: #888;
            margin-bottom: 10px;
            padding-bottom: 8px;
            border-bottom: 1px solid #333;
        }
        .time-group-header .time-label {
            flex: 1;
        }
        .time-group-header .group-actions {
            display: flex;
            gap: 6px;
        }
        .time-group-header .group-actions button {
            padding: 4px 10px;
            font-size: 0.9em;
            background: #333;
            border: 2px solid;
            border-radius: 4px;
            cursor: pointer;
            font-weight: 500;
        }
        .time-group-header .group-actions .select-all-btn {
            color: #ef5350;
            border-color: #ef5350;
        }
        .time-group-header .group-actions .select-all-btn:hover {
            background: #ef5350;
            color: #fff;
        }
        .time-group-header .group-actions .deselect-all-btn {
            color: #4CAF50;
            border-color: #4CAF50;
        }
        .time-group-header .group-actions .deselect-all-btn:hover {
            background: #4CAF50;
            color: #fff;
        }
        .time-group-photos {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }

        /* Photo items - base size increased, controlled by CSS variable */
        /* Default is 170% zoom (index 2): 160*1.69=270, 120*1.69=203 */
        :root {
            --photo-width: 270px;
            --photo-height: 203px;
        }
        .photo-item {
            position: relative;
            width: var(--photo-width);
            border: 2px solid #444;
            border-radius: 4px;
            overflow: hidden;
            transition: all 0.2s;
            display: flex;
            flex-direction: column;
        }
        .photo-item:hover {
            border-color: #666;
        }
        .photo-item img {
            width: 100%;
            height: var(--photo-height);
            object-fit: cover;
            display: block;
            cursor: pointer;
        }
        .photo-item.no-crop img {
            height: auto;
            max-height: calc(var(--photo-height) * 2);
            object-fit: contain;
            background: #111;
        }
        .photo-item .photo-meta {
            padding: 4px 6px;
            font-size: 0.7em;
            background: #333;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        /* Keep/Remove action buttons at bottom of card */
        .photo-item .photo-actions {
            display: flex;
            gap: 2px;
            padding: 4px;
            background: #2a2a2a;
        }
        .photo-item .photo-actions button {
            flex: 1;
            padding: 4px 6px;
            font-size: 0.7em;
            border: 1px solid #555;
            border-radius: 3px;
            cursor: pointer;
            font-weight: 500;
            transition: all 0.15s;
            background: transparent;
            color: #888;
        }
        .photo-item .photo-actions button:hover {
            border-color: #777;
            color: #ccc;
        }
        .photo-item .photo-actions .keep-btn.selected {
            background: #4CAF50;
            border-color: #4CAF50;
            color: #fff;
        }
        .photo-item .photo-actions .remove-btn.selected {
            background: #ef5350;
            border-color: #ef5350;
            color: #fff;
        }
        .photo-item.selected-remove {
            border-color: #c62828;
            opacity: 0.7;
        }
        .photo-item.selected-remove::after {
            content: '🗑️';
            position: absolute;
            top: 4px;
            right: 4px;
            font-size: 16px;
        }

        /* Lightbox with Keep/Remove buttons */
        .lightbox {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.95);
            z-index: 1000;
            justify-content: center;
            align-items: center;
            flex-direction: column;
        }
        .lightbox.active { display: flex; }
        .lightbox img {
            max-width: 95vw;
            max-height: 70vh;
            object-fit: contain;
        }
        .lightbox-header {
            color: #fff;
            padding: 10px;
            text-align: center;
            font-size: 0.9em;
        }
        .lightbox-nav {
            position: absolute;
            top: 50%;
            transform: translateY(-50%);
            font-size: 48px;
            color: #fff;
            cursor: pointer;
            padding: 20px;
            user-select: none;
        }
        .lightbox-nav:hover { color: #4CAF50; }
        .lightbox-nav.prev { left: 10px; }
        .lightbox-nav.next { right: 10px; }
        .lightbox-nav.disabled { opacity: 0.3; pointer-events: none; }

        /* Lightbox action buttons */
        .lightbox-actions {
            display: flex;
            gap: 20px;
            margin-top: 20px;
        }
        .lightbox-actions button {
            padding: 12px 30px;
            font-size: 16px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .lightbox-actions .keep-btn {
            background: #4CAF50;
            color: white;
        }
        .lightbox-actions .keep-btn:hover {
            background: #45a049;
        }
        .lightbox-actions .remove-btn {
            background: #c62828;
            color: white;
        }
        .lightbox-actions .remove-btn:hover {
            background: #b71c1c;
        }
        .lightbox-actions .remove-btn.active {
            background: #7f1d1d;
            box-shadow: inset 0 2px 4px rgba(0,0,0,0.3);
        }
        .lightbox-status {
            margin-top: 10px;
            font-size: 0.9em;
            color: #888;
        }
        .lightbox-status.marked-remove {
            color: #ef5350;
        }

        /* Export bar */
        .export-bar {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: #2a2a2a;
            border-top: 1px solid #444;
            padding: 12px 20px;
            display: flex;
            align-items: center;
            gap: 20px;
            z-index: 100;
        }
        .export-bar .stats-display {
            flex: 1;
        }
        .export-bar button {
            padding: 10px 20px;
            font-size: 14px;
            cursor: pointer;
            border: none;
            border-radius: 4px;
        }
        .export-bar .export-btn {
            background: #4CAF50;
            color: white;
        }
        .export-bar .clear-btn {
            background: #666;
            color: white;
        }
    </style>
</head>
<body>
    <div class="sticky-header">
        <div class="header-top">
            <h1>📁 Photo Browser</h1>
            <div class="stats" id="total-stats"></div>
            <div class="controls">
                <button onclick="expandAll()">Expand All</button>
                <button onclick="collapseAll()">Collapse All</button>
            </div>
        </div>
        <div class="view-options">
            <div class="view-option">
                <label for="size-slider">Size:</label>
                <input type="range" id="size-slider" min="0" max="4" value="2" onchange="updatePhotoSize(this.value)">
                <span id="size-label">170%</span>
            </div>
            <div class="view-option">
                <input type="checkbox" id="no-crop" onchange="toggleCrop(this.checked)">
                <label for="no-crop">Show full image (no crop)</label>
            </div>
        </div>
    </div>
''']

    # Count totals
    total_photos = sum(len(d['photos']) for d in photo_dirs)
    total_dirs = len(photo_dirs)

    html_parts.append(f'''
    <script>document.getElementById('total-stats').textContent = '{total_photos:,} photos in {total_dirs} directories';</script>
    <div id="directories">
''')

    # Render each directory with progress logging
    total_dirs = len(photo_dirs)
    for idx, dir_info in enumerate(photo_dirs):
        if (idx + 1) % 50 == 0 or idx == total_dirs - 1:
            print(f"    Rendering directory {idx + 1}/{total_dirs}...", flush=True)
        html_parts.append(_render_browse_directory(dir_info, base_dir))

    # Close directories div and add lightbox/scripts
    html_parts.append('''
    </div>

    <div class="lightbox" id="lightbox" onclick="closeLightboxOnBackground(event)">
        <div class="lightbox-header" id="lightbox-path"></div>
        <span class="lightbox-nav prev" onclick="event.stopPropagation(); navigateLightbox(-1)">❮</span>
        <img id="lightbox-img" src="" alt="Full size" onclick="event.stopPropagation()">
        <span class="lightbox-nav next" onclick="event.stopPropagation(); navigateLightbox(1)">❯</span>
        <div class="lightbox-actions" onclick="event.stopPropagation()">
            <button class="keep-btn" onclick="keepCurrentPhoto()">✓ Keep</button>
            <button class="remove-btn" id="remove-btn" onclick="removeCurrentPhoto()">🗑️ Remove</button>
        </div>
        <div class="lightbox-status" id="lightbox-status"></div>
    </div>

    <div class="export-bar">
        <div class="stats-display">
            <span id="remove-count">0</span> photos marked for removal
            <span style="margin-left: 15px; color: #888;">|</span>
            <span style="margin-left: 15px;"><span id="storage-freed">0 B</span> to be freed</span>
        </div>
        <button class="clear-btn" onclick="clearSelections()">Clear All</button>
        <button class="export-btn" onclick="exportRemovals()">Export Removal List</button>
    </div>

    <script>
        const STORAGE_KEY = 'photo_browse_removals';
        let removals = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
        let currentPhotoStrip = [];
        let currentPhotoIndex = 0;
        let currentPhotoItems = [];  // DOM elements for current strip
        const lightbox = document.getElementById('lightbox');

        // Size settings: base + 30% per tick (5 ticks total)
        const SIZE_MULTIPLIERS = [1.0, 1.3, 1.69, 2.2, 2.86];  // 100%, 130%, 169%, 220%, 286%
        const SIZE_LABELS = ['100%', '130%', '170%', '220%', '285%'];
        const BASE_WIDTH = 160;
        const BASE_HEIGHT = 120;

        function updatePhotoSize(value) {
            const mult = SIZE_MULTIPLIERS[value];
            document.documentElement.style.setProperty('--photo-width', (BASE_WIDTH * mult) + 'px');
            document.documentElement.style.setProperty('--photo-height', (BASE_HEIGHT * mult) + 'px');
            document.getElementById('size-label').textContent = SIZE_LABELS[value];
        }

        function toggleCrop(noCrop) {
            document.querySelectorAll('.photo-item').forEach(item => {
                item.classList.toggle('no-crop', noCrop);
            });
        }

        // Apply saved state on load
        function applyState() {
            document.querySelectorAll('.photo-item').forEach(item => {
                const path = item.dataset.path;
                const isRemove = !!removals[path];  // Explicitly convert to boolean
                item.classList.toggle('selected-remove', isRemove);
                // Update button states
                const keepBtn = item.querySelector('.keep-btn');
                const removeBtn = item.querySelector('.remove-btn');
                if (keepBtn && removeBtn) {
                    keepBtn.classList.toggle('selected', !isRemove);
                    removeBtn.classList.toggle('selected', isRemove);
                }
            });
            updateCount();
        }

        function setPhotoDecision(button, decision) {
            const item = button.closest('.photo-item');
            const path = item.dataset.path;
            const shouldRemove = (decision === 'remove');

            // Update button states
            const keepBtn = item.querySelector('.keep-btn');
            const removeBtn = item.querySelector('.remove-btn');
            keepBtn.classList.toggle('selected', !shouldRemove);
            removeBtn.classList.toggle('selected', shouldRemove);

            // Update item state and storage
            item.classList.toggle('selected-remove', shouldRemove);
            if (shouldRemove) {
                removals[path] = true;
            } else {
                delete removals[path];
            }
            localStorage.setItem(STORAGE_KEY, JSON.stringify(removals));
            updateCount();
        }

        function setRemoval(path, shouldRemove) {
            const item = document.querySelector(`.photo-item[data-path="${CSS.escape(path)}"]`);
            if (shouldRemove) {
                removals[path] = true;
                if (item) {
                    item.classList.add('selected-remove');
                    const keepBtn = item.querySelector('.keep-btn');
                    const removeBtn = item.querySelector('.remove-btn');
                    if (keepBtn) keepBtn.classList.remove('selected');
                    if (removeBtn) removeBtn.classList.add('selected');
                }
            } else {
                delete removals[path];
                if (item) {
                    item.classList.remove('selected-remove');
                    const keepBtn = item.querySelector('.keep-btn');
                    const removeBtn = item.querySelector('.remove-btn');
                    if (keepBtn) keepBtn.classList.add('selected');
                    if (removeBtn) removeBtn.classList.remove('selected');
                }
            }
            localStorage.setItem(STORAGE_KEY, JSON.stringify(removals));
            updateCount();
        }

        function formatBytes(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
        }

        function updateCount() {
            const paths = Object.keys(removals);
            document.getElementById('remove-count').textContent = paths.length;

            // Calculate total storage to be freed
            let totalBytes = 0;
            paths.forEach(path => {
                const item = document.querySelector(`.photo-item[data-path="${CSS.escape(path)}"]`);
                if (item && item.dataset.size) {
                    totalBytes += parseInt(item.dataset.size, 10);
                }
            });
            document.getElementById('storage-freed').textContent = formatBytes(totalBytes);
        }

        // Select all/deselect all for a time group
        function selectAllInGroup(groupId) {
            const group = document.querySelector(`.time-group[data-group-id="${CSS.escape(groupId)}"]`);
            if (!group) return;
            group.querySelectorAll('.photo-item').forEach(item => {
                const path = item.dataset.path;
                removals[path] = true;
                item.classList.add('selected-remove');
                // Update button states
                const keepBtn = item.querySelector('.keep-btn');
                const removeBtn = item.querySelector('.remove-btn');
                if (keepBtn) keepBtn.classList.remove('selected');
                if (removeBtn) removeBtn.classList.add('selected');
            });
            localStorage.setItem(STORAGE_KEY, JSON.stringify(removals));
            updateCount();
        }

        function deselectAllInGroup(groupId) {
            const group = document.querySelector(`.time-group[data-group-id="${CSS.escape(groupId)}"]`);
            if (!group) return;
            group.querySelectorAll('.photo-item').forEach(item => {
                const path = item.dataset.path;
                delete removals[path];
                item.classList.remove('selected-remove');
                // Update button states
                const keepBtn = item.querySelector('.keep-btn');
                const removeBtn = item.querySelector('.remove-btn');
                if (keepBtn) keepBtn.classList.add('selected');
                if (removeBtn) removeBtn.classList.remove('selected');
            });
            localStorage.setItem(STORAGE_KEY, JSON.stringify(removals));
            updateCount();
        }

        function clearSelections() {
            if (!confirm('Clear all selections?')) return;
            removals = {};
            localStorage.setItem(STORAGE_KEY, JSON.stringify(removals));
            document.querySelectorAll('.photo-item.selected-remove').forEach(item => {
                item.classList.remove('selected-remove');
            });
            updateCount();
        }

        function exportRemovals() {
            const paths = Object.keys(removals);
            if (paths.length === 0) {
                alert('No photos marked for removal');
                return;
            }

            // Create shell script content
            let script = '#!/bin/bash\\n# Photo removal script - generated ' + new Date().toISOString() + '\\n';
            script += '# ' + paths.length + ' photos marked for removal\\n\\n';
            script += 'set -e\\n\\n';

            paths.forEach(p => {
                script += 'rm "' + p.replace(/"/g, '\\\\"') + '"\\n';
            });

            // Download as file
            const blob = new Blob([script], { type: 'text/plain' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'remove_photos.sh';
            a.click();
            URL.revokeObjectURL(url);
        }

        // Directory expand/collapse
        function toggleDirectory(header) {
            header.closest('.directory').classList.toggle('expanded');
        }

        function expandAll() {
            document.querySelectorAll('.directory').forEach(d => d.classList.add('expanded'));
        }

        function collapseAll() {
            document.querySelectorAll('.directory').forEach(d => d.classList.remove('expanded'));
        }

        // Lightbox with Keep/Remove functionality
        function openPhotoLightbox(img) {
            const photoItem = img.closest('.photo-item');
            const timeGroup = photoItem.closest('.time-group');
            currentPhotoItems = Array.from(timeGroup.querySelectorAll('.photo-item'));

            // Build photo strip with src, path, and short path
            currentPhotoStrip = currentPhotoItems.map(item => ({
                src: item.querySelector('img').src,
                path: item.dataset.path,
                shortPath: item.dataset.shortPath
            }));

            // Find current index
            currentPhotoIndex = currentPhotoItems.indexOf(photoItem);
            if (currentPhotoIndex < 0) currentPhotoIndex = 0;

            updateLightboxImage();
            lightbox.classList.add('active');
        }

        function updateLightboxImage() {
            if (currentPhotoStrip.length === 0) return;
            const photo = currentPhotoStrip[currentPhotoIndex];
            document.getElementById('lightbox-img').src = photo.src;
            document.getElementById('lightbox-path').textContent =
                `${currentPhotoIndex + 1} / ${currentPhotoStrip.length} — ${photo.shortPath}`;

            // Update nav buttons
            document.querySelector('.lightbox-nav.prev').classList.toggle('disabled', currentPhotoIndex === 0);
            document.querySelector('.lightbox-nav.next').classList.toggle('disabled', currentPhotoIndex === currentPhotoStrip.length - 1);

            // Update remove button state
            const isMarkedForRemoval = removals[photo.path];
            document.getElementById('remove-btn').classList.toggle('active', isMarkedForRemoval);
            const status = document.getElementById('lightbox-status');
            if (isMarkedForRemoval) {
                status.textContent = 'Marked for removal';
                status.className = 'lightbox-status marked-remove';
            } else {
                status.textContent = 'Keeping';
                status.className = 'lightbox-status';
            }
        }

        function keepCurrentPhoto() {
            if (currentPhotoStrip.length === 0) return;
            const photo = currentPhotoStrip[currentPhotoIndex];
            setRemoval(photo.path, false);
            updateLightboxImage();
            // Auto-advance to next photo
            if (currentPhotoIndex < currentPhotoStrip.length - 1) {
                currentPhotoIndex++;
                updateLightboxImage();
            }
        }

        function removeCurrentPhoto() {
            if (currentPhotoStrip.length === 0) return;
            const photo = currentPhotoStrip[currentPhotoIndex];
            setRemoval(photo.path, true);
            updateLightboxImage();
            // Auto-advance to next photo
            if (currentPhotoIndex < currentPhotoStrip.length - 1) {
                currentPhotoIndex++;
                updateLightboxImage();
            }
        }

        function navigateLightbox(direction) {
            const newIndex = currentPhotoIndex + direction;
            if (newIndex >= 0 && newIndex < currentPhotoStrip.length) {
                currentPhotoIndex = newIndex;
                updateLightboxImage();
            }
        }

        function closeLightbox() {
            lightbox.classList.remove('active');
        }

        function closeLightboxOnBackground(e) {
            if (e.target === lightbox) closeLightbox();
        }

        document.addEventListener('keydown', (e) => {
            if (!lightbox.classList.contains('active')) return;
            if (e.key === 'Escape') closeLightbox();
            else if (e.key === 'ArrowLeft') navigateLightbox(-1);
            else if (e.key === 'ArrowRight') navigateLightbox(1);
            else if (e.key === 'k' || e.key === 'K') keepCurrentPhoto();
            else if (e.key === 'r' || e.key === 'R' || e.key === 'Delete' || e.key === 'Backspace') removeCurrentPhoto();
        });

        // Initialize
        applyState();
    </script>
</body>
</html>
''')

    return ''.join(html_parts)


def _render_browse_directory(dir_info, base_dir):
    """Render a single directory section with time-grouped photos."""
    rel_path = dir_info['rel_path']
    photos = dir_info['photos']
    # Create a safe ID prefix from the directory path (convert Path to str if needed)
    rel_path_str = str(rel_path)
    safe_dir_id = rel_path_str.replace('/', '_').replace(' ', '_').replace('.', '_')

    # Group photos by time
    time_groups = _group_photos_by_time(photos)

    # Build directory HTML
    html_parts = [f'''
        <div class="directory">
            <div class="directory-header" onclick="toggleDirectory(this)">
                <span class="toggle">▶</span>
                <span class="path">{rel_path}</span>
                <span class="count">{len(photos)} photos</span>
            </div>
            <div class="directory-content">
''']

    # Render each time group
    for group_idx, group in enumerate(time_groups):
        group_id = f'{safe_dir_id}_g{group_idx}'

        # Get time range for header
        if group:
            first_time = group[0][1]
            last_time = group[-1][1]
            if first_time > 0:
                first_dt = datetime.fromtimestamp(first_time)
                time_label = first_dt.strftime('%d %b %Y, %H:%M')
                if len(group) > 1 and last_time != first_time:
                    last_dt = datetime.fromtimestamp(last_time)
                    time_label += f' – {last_dt.strftime("%H:%M")}'
            else:
                time_label = 'Unknown time'
        else:
            time_label = 'Unknown time'

        # Include Select All/Deselect All buttons in group header
        html_parts.append(f'''
                <div class="time-group" data-group-id="{group_id}">
                    <div class="time-group-header">
                        <span class="time-label">{time_label} ({len(group)} photos)</span>
                        <span class="group-actions">
                            <button class="select-all-btn" onclick="event.stopPropagation(); selectAllInGroup('{group_id}')">Select All</button>
                            <button class="deselect-all-btn" onclick="event.stopPropagation(); deselectAllInGroup('{group_id}')">Deselect All</button>
                        </span>
                    </div>
                    <div class="time-group-photos">
''')

        # Render photos in this group with Keep/Remove buttons
        for photo, timestamp in group:
            file_url = f'file://{photo.resolve()}'
            try:
                short_path = photo.relative_to(base_dir)
            except ValueError:
                short_path = photo.name
            # Get file size for storage calculation
            try:
                file_size = photo.stat().st_size
            except OSError:
                file_size = 0

            html_parts.append(f'''
                        <div class="photo-item" data-path="{photo.resolve()}" data-short-path="{short_path}" data-size="{file_size}">
                            <img src="{file_url}" alt="{photo.name}" loading="lazy" onclick="openPhotoLightbox(this)">
                            <div class="photo-meta" title="{photo.name}">{photo.name}</div>
                            <div class="photo-actions">
                                <button class="keep-btn" onclick="setPhotoDecision(this, 'keep')">KEEP</button>
                                <button class="remove-btn" onclick="setPhotoDecision(this, 'remove')">REMOVE</button>
                            </div>
                        </div>
''')

        html_parts.append('''
                    </div>
                </div>
''')

    html_parts.append('''
            </div>
        </div>
''')

    return ''.join(html_parts)


def _generate_html_content(candidates, needs_review, duplicates, base_dir):
    """Generate the actual HTML content for the review report.

    Args:
        candidates: List of safe-to-delete candidates
        needs_review: List of items needing manual review
        duplicates: List of duplicate groups
        base_dir: Base directory for relative paths
    """

    html_parts = ['''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Photo Triage Review</title>
    <style>
        * { box-sizing: border-box; }
        html {
            scroll-behavior: smooth;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a1a;
            color: #e0e0e0;
            margin: 0;
            padding: 20px;
            padding-bottom: 80px; /* Space for fixed export bar */
        }
        h1, h2, h3 { color: #fff; }
        .summary {
            background: #2a2a2a;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 30px;
        }
        .summary-stats {
            display: flex;
            gap: 30px;
            flex-wrap: wrap;
        }
        .stat {
            text-align: center;
        }
        .stat-value {
            font-size: 2em;
            font-weight: bold;
            color: #4CAF50;
        }
        .stat-label {
            color: #888;
            font-size: 0.9em;
        }
        .blur-reference {
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid #444;
            font-size: 0.9em;
            color: #aaa;
        }
        .blur-reference span {
            margin: 0 8px;
        }
        .section {
            margin-bottom: 40px;
            scroll-margin-top: 80px;  /* Offset for sticky header when jumping to sections */
        }
        .section-header {
            display: flex;
            align-items: center;
            gap: 15px;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 1px solid #333;
            flex-wrap: wrap;
        }
        .sort-controls {
            margin-left: auto;
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.85em;
            color: #888;
        }
        .sort-btn {
            background: #333;
            border: 1px solid #555;
            color: #ccc;
            padding: 4px 12px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.85em;
        }
        .sort-btn:hover { background: #444; }
        .sort-btn.active {
            background: #4CAF50;
            color: white;
            border-color: #4CAF50;
        }
        .section-cards {
            display: flex;
            flex-direction: column;
            gap: 20px;
        }
        .badge {
            background: #4CAF50;
            color: white;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.85em;
        }
        .badge.warning { background: #ff9800; }
        .badge.info { background: #2196F3; }

        .candidate-card {
            background: #2a2a2a;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .candidate-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        .candidate-path {
            font-family: monospace;
            font-size: 0.85em;
            color: #888;
            word-break: break-all;
        }
        .blur-score {
            font-weight: bold;
            padding: 4px 10px;
            border-radius: 4px;
        }
        .blur-very-blurry { background: #c62828; color: white; }
        .blur-blurry { background: #ef6c00; color: white; }
        .blur-soft { background: #fbc02d; color: black; }
        .blur-sharp { background: #4CAF50; color: white; }

        .photo-strip {
            display: flex;
            gap: 10px;
            overflow-x: auto;
            padding: 10px 0;
        }
        .photo-item {
            flex-shrink: 0;
            text-align: center;
        }
        .photo-item img {
            max-height: 200px;
            max-width: 300px;
            border-radius: 8px;
            cursor: pointer;
            transition: transform 0.2s;
        }
        .photo-item img:hover {
            transform: scale(1.05);
        }
        .photo-item.candidate img {
            border: 3px solid #ff9800;
        }
        .photo-item.sharp img {
            border: 3px solid #4CAF50;
        }
        .photo-label {
            margin-top: 5px;
            font-size: 0.8em;
            color: #888;
        }
        .photo-label .blur {
            font-weight: bold;
        }

        .duplicate-group {
            background: #2a2a2a;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .duplicate-photos {
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
        }
        .duplicate-item {
            text-align: center;
            padding: 4px;
        }
        .duplicate-item img {
            max-height: 150px;
            max-width: 200px;
            border-radius: 8px;
            cursor: pointer;
        }
        .duplicate-item.keep {
            border: 3px solid #4CAF50;
            border-radius: 11px;
        }
        .duplicate-item.remove-selected {
            border: 3px solid #f44336;
            border-radius: 11px;
        }
        .duplicate-meta {
            font-size: 0.75em;
            color: #888;
            margin-top: 5px;
        }
        .duplicate-actions {
            display: flex;
            gap: 5px;
            justify-content: center;
            margin-top: 8px;
        }
        .duplicate-actions .btn {
            padding: 4px 10px;
            font-size: 0.75em;
        }

        .action-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: #333;
            padding: 10px 15px;
            border-radius: 8px;
            margin-top: 10px;
            gap: 15px;
        }
        .action-hint {
            font-size: 0.9em;
            flex: 1;
        }
        .action-buttons {
            display: flex;
            gap: 8px;
            flex-shrink: 0;
        }
        .btn {
            padding: 8px 16px;
            border: 2px solid #555;
            border-radius: 6px;
            cursor: pointer;
            font-weight: bold;
            font-size: 0.9em;
            transition: all 0.2s;
            background: transparent;
            color: #888;
        }
        .btn:hover {
            border-color: #777;
            color: #ccc;
        }
        .btn-keep {
            color: #4CAF50;
            border-color: #4CAF50;
        }
        .btn-keep:hover {
            background: rgba(76, 175, 80, 0.2);
        }
        .btn-remove {
            color: #ef5350;
            border-color: #ef5350;
        }
        .btn-remove:hover {
            background: rgba(239, 83, 80, 0.2);
        }
        .btn.selected {
            transform: scale(1.05);
            box-shadow: 0 0 8px rgba(255,255,255,0.2);
        }
        .btn-keep.selected {
            background: #4CAF50;
            color: #fff;
        }
        .btn-remove.selected {
            background: #ef5350;
            color: #fff;
        }

        /* Card states based on decision */
        .candidate-card.decided-keep {
            border-left: 4px solid #4CAF50;
            opacity: 0.7;
        }
        .candidate-card.decided-remove {
            border-left: 4px solid #c62828;
            opacity: 0.7;
        }

        /* Export bar */
        .export-bar {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: #2a2a2a;
            padding: 15px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-top: 1px solid #444;
            z-index: 100;
        }
        .export-stats {
            font-size: 0.9em;
        }
        .export-stats span {
            margin-right: 20px;
        }
        .btn-export {
            background: #1976D2;
            color: white;
            padding: 10px 20px;
        }
        .btn-export:hover { background: #1565C0; }

        /* Lightbox */
        .lightbox {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.95);
            z-index: 1000;
            justify-content: center;
            align-items: center;
            flex-direction: column;
        }
        .lightbox.active { display: flex; }
        .lightbox img {
            max-width: 95%;
            max-height: calc(95% - 60px);
        }
        .lightbox-close {
            position: absolute;
            top: 20px;
            right: 30px;
            font-size: 40px;
            color: white;
            cursor: pointer;
        }
        .lightbox-path {
            position: absolute;
            top: 20px;
            left: 30px;
            color: #ccc;
            font-family: monospace;
            font-size: 14px;
            max-width: 70%;
            word-break: break-all;
        }
        .lightbox-nav {
            position: absolute;
            top: 50%;
            transform: translateY(-50%);
            font-size: 60px;
            color: rgba(255,255,255,0.7);
            cursor: pointer;
            user-select: none;
            padding: 20px;
        }
        .lightbox-nav:hover { color: white; }
        .lightbox-nav.prev { left: 10px; }
        .lightbox-nav.next { right: 10px; }
        .lightbox-nav.disabled { color: rgba(255,255,255,0.2); cursor: default; }
        .lightbox-hint {
            position: absolute;
            bottom: 20px;
            color: #888;
            font-size: 12px;
        }

        /* Sticky header */
        .sticky-header {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            background: #1a1a1a;
            padding: 10px 20px;
            z-index: 100;
            border-bottom: 1px solid #333;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .sticky-header h1 {
            margin: 0;
            font-size: 1.3em;
        }
        .nav-links {
            display: flex;
            gap: 20px;
        }
        .nav-link {
            color: #ccc;
            text-decoration: none;
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 0.9em;
            transition: background 0.2s;
        }
        .nav-link:hover {
            background: #333;
            color: white;
        }
        .nav-link .nav-count {
            background: #444;
            padding: 2px 8px;
            border-radius: 10px;
            margin-left: 6px;
            font-size: 0.85em;
        }
        .nav-link.high-confidence .nav-count { background: #4CAF50; }
        .nav-link.needs-review .nav-count { background: #ff9800; }
        .nav-link.duplicates .nav-count { background: #2196F3; }

        /* Offset content for sticky header */
        body {
            padding-top: 60px;
        }
    </style>
</head>
<body>
    <div class="sticky-header">
        <h1>📸 Photo Triage Review</h1>
        <nav class="nav-links">
            <a href="#high-confidence-section" class="nav-link high-confidence">🎯 High-Confidence<span class="nav-count" id="nav-high-count">0</span></a>
            <a href="#needs-review-section" class="nav-link needs-review">⚠️ Needs Review<span class="nav-count" id="nav-review-count">0</span></a>
            <a href="#duplicates-section" class="nav-link duplicates">📋 Duplicates<span class="nav-count" id="nav-dup-count">0</span></a>
        </nav>
    </div>
''']

    # Summary section with blur score reference
    html_parts.append(f'''
    <div class="summary">
        <div class="summary-stats">
            <div class="stat">
                <div class="stat-value">{len(candidates)}</div>
                <div class="stat-label">High-confidence</div>
            </div>
            <div class="stat">
                <div class="stat-value" style="color: #ff9800;">{len(needs_review)}</div>
                <div class="stat-label">Needs review</div>
            </div>
            <div class="stat">
                <div class="stat-value" style="color: #2196F3;">{len(duplicates)}</div>
                <div class="stat-label">Duplicates</div>
            </div>
        </div>
        <div class="blur-reference">
            <strong>Blur scores:</strong>
            <span style="color:#32fd38;">150+ Sharp</span> |
            <span style="color:#4CAF50;">80-150 Decent</span> |
            <span style="color:#8BC34A;">40-80 Soft</span> |
            <span style="color:#ff9800;">20-40 Blurry</span> |
            <span style="color:#f44336;">&lt;20 Very Blurry</span>
        </div>
    </div>
    <script>
        // Set nav counts
        document.getElementById('nav-high-count').textContent = '{len(candidates)}';
        document.getElementById('nav-review-count').textContent = '{len(needs_review)}';
        document.getElementById('nav-dup-count').textContent = '{len(duplicates)}';
    </script>
''')

    # Helper to extract timestamp for sorting
    def get_sort_key(item, sort_by='date'):
        if sort_by == 'blur':
            return item['blur']
        else:
            # Sort by date - use timestamp from filename or mtime
            ts = extract_timestamp_from_filename(item['path'].name)
            if ts:
                return ts
            # Fallback to file mtime
            try:
                return datetime.fromtimestamp(item['path'].stat().st_mtime)
            except OSError:
                return datetime.min

    # High-confidence removals section (pre-selected for removal)
    if candidates:
        html_parts.append(f'''
    <div class="section" id="high-confidence-section" data-section="high-confidence">
        <div class="section-header">
            <h2>🎯 High-Confidence Removals</h2>
            <span class="badge">Very blurry with sharp alternative ≤5min &mdash; pre-selected for removal</span>
            <div class="sort-controls">
                <span>Sort by:</span>
                <button class="sort-btn active" data-sort="date" onclick="sortSection('high-confidence', 'date')">Date</button>
                <button class="sort-btn" data-sort="blur" onclick="sortSection('high-confidence', 'blur')">Blur</button>
            </div>
        </div>
        <div class="section-cards">
''')
        # Default sort by date
        display_candidates = sorted(candidates, key=lambda x: get_sort_key(x, 'date'))

        for item in display_candidates:
            # Add data attributes for client-side sorting
            ts = extract_timestamp_from_filename(item['path'].name)
            ts_str = ts.isoformat() if ts else ''
            html_parts.append(_render_candidate_card(
                item, base_dir, is_safe=True, preselect_remove=True,
                extra_attrs=f'data-blur="{item["blur"]}" data-date="{ts_str}"'
            ))

        html_parts.append('</div></div>')  # Close section-cards and section

    # Needs review section
    if needs_review:
        html_parts.append(f'''
    <div class="section" id="needs-review-section" data-section="needs-review">
        <div class="section-header">
            <h2>⚠️ Needs Manual Review</h2>
            <span class="badge warning">Blurry but no sharp alternative within 5min</span>
            <div class="sort-controls">
                <span>Sort by:</span>
                <button class="sort-btn active" data-sort="date" onclick="sortSection('needs-review', 'date')">Date</button>
                <button class="sort-btn" data-sort="blur" onclick="sortSection('needs-review', 'blur')">Blur</button>
            </div>
        </div>
        <div class="section-cards">
''')
        # Default sort by date
        display_review = sorted(needs_review, key=lambda x: get_sort_key(x, 'date'))

        for item in display_review:
            ts = extract_timestamp_from_filename(item['path'].name)
            ts_str = ts.isoformat() if ts else ''
            html_parts.append(_render_candidate_card(
                item, base_dir, is_safe=False,
                extra_attrs=f'data-blur="{item["blur"]}" data-date="{ts_str}"'
            ))

        html_parts.append('</div></div>')  # Close section-cards and section

    # Duplicates section
    if duplicates:
        html_parts.append('''
    <div class="section" id="duplicates-section">
        <div class="section-header">
            <h2>📋 Duplicates</h2>
            <span class="badge info">Identical file content</span>
        </div>
''')
        for dup_group in duplicates:
            html_parts.append(_render_duplicate_group(dup_group, base_dir))

        html_parts.append('</div>')

    # Export bar and lightbox
    html_parts.append('''
    <div class="export-bar">
        <div class="export-stats">
            <span id="keep-count">Keep: 0</span>
            <span id="remove-count">Remove: 0</span>
            <span id="pending-count">Pending: 0</span>
        </div>
        <div>
            <button class="btn btn-export" onclick="exportDecisions()">Export Remove Script</button>
            <button class="btn" style="background:#666;" onclick="clearDecisions()">Clear All</button>
        </div>
    </div>

    <div class="lightbox" onclick="closeLightboxOnBackground(event)">
        <span class="lightbox-close" onclick="closeLightbox()">&times;</span>
        <span class="lightbox-path" id="lightbox-path"></span>
        <span class="lightbox-nav prev" onclick="navigateLightbox(-1)">&#8249;</span>
        <img id="lightbox-img" src="" alt="Full size">
        <span class="lightbox-nav next" onclick="navigateLightbox(1)">&#8250;</span>
        <span class="lightbox-hint">← → to navigate • Esc to close</span>
    </div>

    <script>
        const lightbox = document.querySelector('.lightbox');
        const STORAGE_KEY = 'photo_triage_decisions';

        // Track current photo strip for lightbox navigation
        let currentPhotoStrip = [];
        let currentPhotoIndex = 0;

        // Sort section by date or blur
        function sortSection(sectionId, sortBy) {
            const section = document.getElementById(sectionId + '-section');
            if (!section) return;

            const container = section.querySelector('.section-cards');
            if (!container) return;

            const cards = Array.from(container.querySelectorAll('.candidate-card'));

            cards.sort((a, b) => {
                if (sortBy === 'blur') {
                    return parseFloat(a.dataset.blur) - parseFloat(b.dataset.blur);
                } else {
                    // Sort by date (oldest first for chronological review)
                    const dateA = a.dataset.date || '';
                    const dateB = b.dataset.date || '';
                    return dateA.localeCompare(dateB);
                }
            });

            // Re-append in sorted order
            cards.forEach(card => container.appendChild(card));

            // Update button states
            section.querySelectorAll('.sort-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.sort === sortBy);
            });
        }

        // Load and apply saved decisions on page load
        function loadDecisions() {
            const saved = localStorage.getItem(STORAGE_KEY);
            if (!saved) return {};
            try {
                return JSON.parse(saved);
            } catch (e) {
                return {};
            }
        }

        function saveDecisions(decisions) {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(decisions));
        }

        function applyDecisions() {
            const decisions = loadDecisions();
            let needsSave = false;

            // Apply to candidate cards
            document.querySelectorAll('.candidate-card').forEach(card => {
                const cardId = card.dataset.cardId;
                const path = card.dataset.path;

                // If no saved decision, check for preselect attribute
                if (!decisions[cardId] && card.dataset.preselect === 'remove') {
                    decisions[cardId] = { path: path, decision: 'REMOVE' };
                    needsSave = true;
                }

                if (decisions[cardId]) {
                    const decision = decisions[cardId].decision;
                    card.classList.remove('decided-keep', 'decided-remove');
                    card.classList.add('decided-' + decision.toLowerCase());

                    // Update button states
                    const keepBtn = card.querySelector('.btn-keep');
                    const removeBtn = card.querySelector('.btn-remove');
                    keepBtn.classList.toggle('selected', decision === 'KEEP');
                    removeBtn.classList.toggle('selected', decision === 'REMOVE');
                }
            });

            // Apply to duplicate items (preselected via button classes in HTML)
            document.querySelectorAll('.duplicate-item').forEach(item => {
                const path = item.dataset.path;

                // Check if already has a decision from localStorage
                if (decisions[path]) {
                    const decision = decisions[path].decision;
                    item.classList.remove('keep', 'remove-selected');
                    if (decision === 'KEEP') {
                        item.classList.add('keep');
                    } else {
                        item.classList.add('remove-selected');
                    }
                    const keepBtn = item.querySelector('.keep-btn');
                    const removeBtn = item.querySelector('.remove-btn');
                    if (keepBtn) keepBtn.classList.toggle('selected', decision === 'KEEP');
                    if (removeBtn) removeBtn.classList.toggle('selected', decision === 'REMOVE');
                } else {
                    // No saved decision - check preselection from HTML
                    const removeBtn = item.querySelector('.remove-btn.selected');
                    if (removeBtn) {
                        // Pre-selected for removal - save it
                        decisions[path] = { path: path, decision: 'REMOVE' };
                        item.classList.add('remove-selected');
                        needsSave = true;
                    } else {
                        const keepBtn = item.querySelector('.keep-btn.selected');
                        if (keepBtn) {
                            decisions[path] = { path: path, decision: 'KEEP' };
                            item.classList.add('keep');
                            needsSave = true;
                        }
                    }
                }
            });

            // Check all duplicate group warnings (all copies removed, edited pairs)
            document.querySelectorAll('.duplicate-group').forEach(group => {
                checkDuplicateWarnings(group);
            });

            // Save preselected items to localStorage
            if (needsSave) {
                saveDecisions(decisions);
            }

            updateCounts();
        }

        function markDecision(btn, decision) {
            const card = btn.closest('.candidate-card');
            const cardId = card.dataset.cardId;
            const path = card.dataset.path;

            const decisions = loadDecisions();
            decisions[cardId] = { path: path, decision: decision };
            saveDecisions(decisions);

            // Update UI
            card.classList.remove('decided-keep', 'decided-remove');
            card.classList.add('decided-' + decision.toLowerCase());

            const keepBtn = card.querySelector('.btn-keep');
            const removeBtn = card.querySelector('.btn-remove');
            keepBtn.classList.toggle('selected', decision === 'KEEP');
            removeBtn.classList.toggle('selected', decision === 'REMOVE');

            updateCounts();
        }

        function updateCounts() {
            const decisions = loadDecisions();
            const values = Object.values(decisions);
            const keepCount = values.filter(d => d.decision === 'KEEP').length;
            const removeCount = values.filter(d => d.decision === 'REMOVE').length;

            // Count total items: candidate cards + duplicate items
            const totalCards = document.querySelectorAll('.candidate-card').length;
            const totalDuplicates = document.querySelectorAll('.duplicate-item').length;
            const totalItems = totalCards + totalDuplicates;
            const pendingCount = totalItems - keepCount - removeCount;

            document.getElementById('keep-count').textContent = 'Keep: ' + keepCount;
            document.getElementById('remove-count').textContent = 'Remove: ' + removeCount;
            document.getElementById('pending-count').textContent = 'Pending: ' + pendingCount;
        }

        function exportDecisions() {
            const decisions = loadDecisions();
            const toRemove = Object.values(decisions)
                .filter(d => d.decision === 'REMOVE')
                .map(d => d.path);

            if (toRemove.length === 0) {
                alert('No files marked for removal.');
                return;
            }

            // Create a shell script
            const script = '#!/bin/bash\\n# Photo Triage - Files to Remove\\n# Generated: ' + new Date().toISOString() + '\\n\\n' +
                toRemove.map(p => 'rm "' + p + '"').join('\\n');

            // Create download
            const blob = new Blob([script], { type: 'text/plain' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'remove_photos.sh';
            a.click();
            URL.revokeObjectURL(url);
        }

        function clearDecisions() {
            if (confirm('Clear all decisions? This cannot be undone.')) {
                localStorage.removeItem(STORAGE_KEY);
                document.querySelectorAll('.candidate-card').forEach(card => {
                    card.classList.remove('decided-keep', 'decided-remove');
                    card.querySelectorAll('.btn').forEach(btn => btn.classList.remove('selected'));
                });
                // Also clear duplicate decisions
                document.querySelectorAll('.duplicate-item').forEach(item => {
                    item.classList.remove('keep', 'remove-selected');
                    item.querySelectorAll('.btn').forEach(btn => btn.classList.remove('selected'));
                });
                updateCounts();
            }
        }

        // Duplicate item decision handling
        function setDuplicateDecision(btn, decision) {
            const item = btn.closest('.duplicate-item');
            const path = item.dataset.path;

            // Save to localStorage with same format as candidates
            const decisions = loadDecisions();
            decisions[path] = {
                path: path,
                decision: decision.toUpperCase(),
                timestamp: new Date().toISOString()
            };
            saveDecisions(decisions);

            // Update UI
            item.classList.remove('keep', 'remove-selected');
            if (decision === 'keep') {
                item.classList.add('keep');
            } else {
                item.classList.add('remove-selected');
            }

            const keepBtn = item.querySelector('.keep-btn');
            const removeBtn = item.querySelector('.remove-btn');
            keepBtn.classList.toggle('selected', decision === 'keep');
            removeBtn.classList.toggle('selected', decision === 'remove');

            // Check for warnings (all copies removed, edited pair both removed)
            checkDuplicateWarnings(item.closest('.duplicate-group'));

            updateCounts();
        }

        function checkDuplicateWarnings(group) {
            if (!group) return;

            const items = group.querySelectorAll('.duplicate-item');
            let allRemoved = true;
            let originalRemoved = false;
            let editedRemoved = false;
            let originalKept = false;
            let editedKept = false;

            items.forEach(item => {
                const isOriginal = item.dataset.isOriginal === 'true';
                const isEdited = item.dataset.isEdited === 'true';
                const isRemoveSelected = item.querySelector('.remove-btn.selected') !== null;
                const isKeepSelected = item.querySelector('.keep-btn.selected') !== null;

                if (!isRemoveSelected) allRemoved = false;
                if (isOriginal && isRemoveSelected) originalRemoved = true;
                if (isEdited && isRemoveSelected) editedRemoved = true;
                if (isOriginal && isKeepSelected) originalKept = true;
                if (isEdited && isKeepSelected) editedKept = true;
            });

            // Warning: all copies marked for removal
            const allRemovedWarning = group.querySelector('.all-removed-warning');
            if (allRemovedWarning) {
                allRemovedWarning.style.display = allRemoved ? 'block' : 'none';
            }

            // Warning: edited pair both removed (only if has-edited-pair)
            const editedPairWarning = group.querySelector('.edited-pair-warning');
            if (editedPairWarning && group.dataset.hasEditedPair === 'true') {
                // Only show if not already showing all-removed warning (avoid duplicate warnings)
                editedPairWarning.style.display = (!allRemoved && originalRemoved && editedRemoved) ? 'block' : 'none';
            }

            // Warning: edited pair both kept (redundant storage)
            const bothKeptWarning = group.querySelector('.both-kept-warning');
            if (bothKeptWarning && group.dataset.hasEditedPair === 'true') {
                bothKeptWarning.style.display = (originalKept && editedKept) ? 'block' : 'none';
            }
        }

        // Lightbox functions
        function openLightbox(img, photoStrip, index) {
            currentPhotoStrip = photoStrip;
            currentPhotoIndex = index;
            updateLightboxImage();
            lightbox.classList.add('active');
        }

        function updateLightboxImage() {
            if (currentPhotoStrip.length === 0) return;

            const photo = currentPhotoStrip[currentPhotoIndex];
            document.getElementById('lightbox-img').src = photo.src;

            // Build header with path, blur, and time
            let headerText = photo.shortPath;
            if (photo.blur) {
                headerText += ` • blur: ${photo.blur}`;
            }
            if (photo.time) {
                headerText += ` • ${photo.time}`;
            }
            document.getElementById('lightbox-path').textContent = headerText;

            // Update nav button states
            document.querySelector('.lightbox-nav.prev').classList.toggle('disabled', currentPhotoIndex === 0);
            document.querySelector('.lightbox-nav.next').classList.toggle('disabled', currentPhotoIndex === currentPhotoStrip.length - 1);
        }

        function navigateLightbox(direction) {
            const newIndex = currentPhotoIndex + direction;
            if (newIndex >= 0 && newIndex < currentPhotoStrip.length) {
                currentPhotoIndex = newIndex;
                updateLightboxImage();
            }
        }

        function closeLightbox() {
            lightbox.classList.remove('active');
        }

        function closeLightboxOnBackground(e) {
            // Only close if clicking the background, not nav buttons or image
            if (e.target === lightbox) {
                closeLightbox();
            }
        }

        // Click image to open lightbox with navigation context
        document.querySelectorAll('.photo-strip').forEach(strip => {
            const photos = Array.from(strip.querySelectorAll('.photo-item'));
            photos.forEach((photoItem, idx) => {
                const img = photoItem.querySelector('img');
                img.onclick = (e) => {
                    e.stopPropagation();
                    const photoData = photos.map(p => ({
                        src: p.querySelector('img').src,
                        shortPath: p.dataset.shortPath || p.querySelector('img').alt,
                        blur: p.dataset.blur || '',
                        time: p.dataset.time || ''
                    }));
                    openLightbox(img, photoData, idx);
                };
            });
        });

        // Open duplicate lightbox with all photos from same group for arrow navigation
        function openDuplicateLightbox(img) {
            event.stopPropagation();
            const duplicateItem = img.closest('.duplicate-item');
            const group = duplicateItem.closest('.duplicate-group');
            const allItems = Array.from(group.querySelectorAll('.duplicate-item'));

            // Build photo strip from all items in this group
            const photoData = allItems.map(item => ({
                src: item.querySelector('img').src,
                shortPath: item.dataset.shortPath || '',
                blur: item.dataset.blur || '',
                time: ''
            }));

            // Find current index
            const currentIdx = allItems.indexOf(duplicateItem);
            openLightbox(img, photoData, currentIdx);
        }

        // Keyboard navigation
        document.addEventListener('keydown', (e) => {
            if (!lightbox.classList.contains('active')) return;

            if (e.key === 'Escape') {
                closeLightbox();
            } else if (e.key === 'ArrowLeft') {
                navigateLightbox(-1);
            } else if (e.key === 'ArrowRight') {
                navigateLightbox(1);
            }
        });

        // Initialize on page load
        applyDecisions();
    </script>
</body>
</html>
''')

    return ''.join(html_parts)


def _render_candidate_card(item, base_dir, is_safe=True, preselect_remove=False, extra_attrs=''):
    """Render a single candidate card with context photos.

    Args:
        item: Dict with 'path', 'blur', 'context' keys
        base_dir: Base directory for relative path display
        is_safe: Whether this is a high-confidence removal (has sharp alternative)
        preselect_remove: If True, card will be pre-selected for removal on load
        extra_attrs: Additional HTML attributes for the card (for sorting)
    """
    path = item['path']
    blur = item['blur']
    context = item['context']

    # Get file modification date for context (human-readable format)
    try:
        mtime = path.stat().st_mtime
        date_str = datetime.fromtimestamp(mtime).strftime('%-d %B %Y')
    except OSError:
        date_str = 'Unknown date'

    # Determine blur class
    if blur < VERY_BLURRY_THRESHOLD:
        blur_class = 'blur-very-blurry'
    elif blur < BLUR_THRESHOLD_BLURRY:
        blur_class = 'blur-blurry'
    else:
        blur_class = 'blur-soft'

    # Build context photo strip
    photo_strip = []

    # Add context photos before
    before_photos = [c for c in context if c['position'] == 'before']
    for ctx in before_photos:
        ctx_blur = ctx['blur'] or 0
        is_sharp = ctx_blur >= BLUR_THRESHOLD_BLURRY
        diff_sec = ctx.get('diff_seconds', None)
        photo_strip.append(_render_photo_item(ctx['path'], ctx_blur, is_sharp=is_sharp, diff_seconds=diff_sec))

    # Add the candidate itself
    photo_strip.append(_render_photo_item(path, blur, is_candidate=True))

    # Add context photos after
    after_photos = [c for c in context if c['position'] == 'after']
    for ctx in after_photos:
        ctx_blur = ctx['blur'] or 0
        is_sharp = ctx_blur >= BLUR_THRESHOLD_BLURRY
        diff_sec = ctx.get('diff_seconds', None)
        photo_strip.append(_render_photo_item(ctx['path'], ctx_blur, is_sharp=is_sharp, diff_seconds=diff_sec))

    # Create a safe ID for the card (used for localStorage)
    card_id = str(path.resolve()).replace('/', '_').replace(' ', '_')

    # Build preselect attribute if needed
    preselect_attr = ' data-preselect="remove"' if preselect_remove else ''

    # Add extra attrs if provided
    extra_attr_str = f' {extra_attrs}' if extra_attrs else ''

    # Build hint text based on context
    if is_safe:
        hint_text = '✅ <strong>High confidence</strong> &mdash; Sharp alternative within 5min'
    else:
        hint_text = '⚠️ <strong>Review needed</strong> &mdash; No sharp alternative within 5min'

    return f'''
        <div class="candidate-card" data-path="{path.resolve()}" data-card-id="{card_id}"{preselect_attr}{extra_attr_str}>
            <div class="candidate-header">
                <div>
                    <strong>{path.name}</strong>
                    <div class="candidate-path">{date_str}</div>
                </div>
                <span class="blur-score {blur_class}">Blur: {blur:.1f}</span>
            </div>
            <div class="photo-strip">
                {''.join(photo_strip)}
            </div>
            <div class="action-bar">
                <span class="action-hint">
                    {hint_text}
                </span>
                <div class="action-buttons">
                    <button class="btn btn-keep" onclick="markDecision(this, 'KEEP')">✓ Keep</button>
                    <button class="btn btn-remove" onclick="markDecision(this, 'REMOVE')">✗ Remove</button>
                </div>
            </div>
        </div>
'''


def _render_photo_item(path, blur, is_candidate=False, is_sharp=False, diff_seconds=None):
    """Render a single photo in the strip using file:// URL for full resolution.

    Args:
        path: Path to the image
        blur: Blur score
        is_candidate: Whether this is the main candidate photo
        is_sharp: Whether this is a sharp context photo
        diff_seconds: Time difference from candidate in seconds (for context photos)
    """
    css_class = 'photo-item'

    # Format time difference as a readable string
    if diff_seconds is not None:
        if diff_seconds == 0:
            time_str = 'same time'
        elif diff_seconds < 60:
            time_str = f'{int(diff_seconds)}s'
        elif diff_seconds < 3600:
            time_str = f'{int(diff_seconds/60)}m'
        elif diff_seconds < 86400:
            time_str = f'{diff_seconds/3600:.1f}h'
        else:
            time_str = f'{int(diff_seconds/86400)}d'
    else:
        time_str = None

    if is_candidate:
        css_class += ' candidate'
        label = f'Blur: {blur:.1f}'
    elif is_sharp:
        css_class += ' sharp'
        # Sharp context photo: show blur score and time apart
        if time_str:
            label = f'✓ {blur:.0f} • {time_str}'
        else:
            label = f'✓ Sharp ({blur:.0f})'
    else:
        # Blurry context photo: show blur score and time apart
        if time_str:
            label = f'blur {blur:.0f} • {time_str}'
        else:
            label = f'blur {blur:.0f}'

    # Use file:// URL with absolute path - works in Safari/Firefox
    file_url = f'file://{path.resolve()}'

    # Build path display for lightbox: last 2 dirs + filename
    parts = path.resolve().parts
    if len(parts) >= 3:
        short_path = '/'.join(parts[-3:])
    else:
        short_path = path.name

    # Data attributes for lightbox display
    time_attr = time_str if time_str else ''
    blur_attr = f'{blur:.1f}'

    return f'''
                <div class="{css_class}" data-full-path="{path.resolve()}" data-short-path="{short_path}" data-blur="{blur_attr}" data-time="{time_attr}">
                    <img src="{file_url}" alt="{path.name}" title="{path.resolve()}" loading="lazy">
                    <div class="photo-label">
                        {label}
                    </div>
                </div>
'''


def _render_duplicate_group(dup_group, base_dir):
    """Render a duplicate group card with KEEP/REMOVE buttons.

    For edited pairs (original + -edited version), auto-selects the original
    for removal since edited versions typically represent intentional improvements.
    """
    import re
    paths = dup_group['paths']
    dup_type = dup_group.get('type', 'exact')

    # Sort by modification time, newest first (the "keeper")
    paths_with_mtime = []
    for p in paths:
        try:
            mtime = p.stat().st_mtime
            size = p.stat().st_size
            paths_with_mtime.append((p, mtime, size))
        except OSError:
            paths_with_mtime.append((p, 0, 0))

    paths_with_mtime.sort(key=lambda x: x[1], reverse=True)

    # Detect edited pairs: find files ending in -edited and their originals
    edited_pattern = re.compile(r'^(.+)-edited(\.[^.]+)$', re.IGNORECASE)
    edited_files = set()
    original_files = set()

    for p, _, _ in paths_with_mtime:
        match = edited_pattern.match(p.name)
        if match:
            edited_files.add(p)
            # Find the corresponding original
            base_name = match.group(1)
            ext = match.group(2)
            potential_original = p.parent / f'{base_name}{ext}'
            if potential_original in [x[0] for x in paths_with_mtime]:
                original_files.add(potential_original)

    # Determine which files to auto-select for removal
    # If this is an edited pair, select the original for removal (keep the edited)
    # Otherwise, select all but the newest for removal
    has_edited_pair = bool(edited_files and original_files)

    # Build type badge
    type_badge = ''
    if dup_type == 'exact':
        type_badge = '<span style="background:#c62828;color:white;padding:2px 8px;border-radius:4px;font-size:0.85em;margin-left:8px;">Exact duplicate</span>'
    else:
        type_badge = '<span style="background:#ff9800;color:white;padding:2px 8px;border-radius:4px;font-size:0.85em;margin-left:8px;">Perceptually similar</span>'

    # Calculate blur scores and get EXIF dates for all files in group
    blur_scores = {}
    exif_dates = {}
    for p, _, _ in paths_with_mtime:
        try:
            blur_scores[p] = calculate_blur_score(p)
        except Exception:
            blur_scores[p] = None

        # Get actual photo date from EXIF (not filesystem mtime)
        exif_dates[p] = get_exif_date(p)

    photos_html = []
    for i, (p, mtime, size) in enumerate(paths_with_mtime):
        file_url = f'file://{p.resolve()}'

        # Use EXIF date if available, fall back to file mtime
        exif_date = exif_dates.get(p)
        if exif_date:
            date_str = exif_date.strftime('%-d %B %Y')
        elif mtime:
            date_str = datetime.fromtimestamp(mtime).strftime('%-d %B %Y') + ' (file date)'
        else:
            date_str = 'Unknown'

        size_str = f'{size / 1024 / 1024:.1f} MB' if size else 'Unknown'

        try:
            rel_path = p.relative_to(base_dir)
        except ValueError:
            rel_path = p

        # Determine default selection
        if has_edited_pair:
            # For edited pairs: keep the edited version, remove the original
            if p in original_files:
                default_remove = True
                label = '🗑️ Original (edited version exists)'
            elif p in edited_files:
                default_remove = False
                label = '🏆 KEEP (edited)'
            else:
                # Neither original nor edited - unusual, default to keep newest
                default_remove = (i != 0)
                label = '🏆 KEEP (newest)' if i == 0 else '🗑️ Duplicate'
        else:
            # No edited pair - keep the newest
            default_remove = (i != 0)
            label = '🏆 KEEP (newest)' if i == 0 else '🗑️ Duplicate'

        css_class = 'duplicate-item'
        if not default_remove:
            css_class += ' keep'

        # Pre-select buttons based on default
        keep_selected = '' if default_remove else 'selected'
        remove_selected = 'selected' if default_remove else ''

        # Get blur score and format display
        blur = blur_scores.get(p)
        blur_display = ''
        blur_class = ''
        blur_data = ''
        if blur is not None:
            blur_int = int(blur)
            blur_data = f'data-blur="{blur_int}"'
            if blur < 20:
                blur_class = 'blur-very-blurry'
                blur_display = f'<span class="{blur_class}" style="padding:2px 6px;border-radius:3px;">Blur: {blur_int}</span>'
            elif blur < 40:
                blur_class = 'blur-blurry'
                blur_display = f'<span class="{blur_class}" style="padding:2px 6px;border-radius:3px;">Blur: {blur_int}</span>'
            elif blur < 80:
                blur_class = 'blur-soft'
                blur_display = f'<span class="{blur_class}" style="padding:2px 6px;border-radius:3px;">Blur: {blur_int}</span>'
            else:
                blur_class = 'blur-sharp'
                blur_display = f'<span class="{blur_class}" style="padding:2px 6px;border-radius:3px;">Blur: {blur_int}</span>'

        photos_html.append(f'''
            <div class="{css_class}" data-path="{p.resolve()}" data-short-path="{rel_path}" data-is-original="{'true' if p in original_files else 'false'}" data-is-edited="{'true' if p in edited_files else 'false'}" {blur_data}>
                <img src="{file_url}" alt="{p.name}" title="{p.resolve()}" loading="lazy" onclick="openDuplicateLightbox(this)">
                <div class="duplicate-meta">
                    {label}<br>
                    {blur_display}<br>
                    {date_str}<br>
                    {size_str}<br>
                    <span style="font-size:0.9em; word-break:break-all;">{rel_path}</span>
                </div>
                <div class="duplicate-actions">
                    <button class="btn keep-btn {keep_selected}" onclick="setDuplicateDecision(this, 'keep')">KEEP</button>
                    <button class="btn remove-btn {remove_selected}" onclick="setDuplicateDecision(this, 'remove')">REMOVE</button>
                </div>
            </div>
''')

    # Add warnings for dangerous selections
    # Warning 1: All copies marked for removal (always present, hidden by default)
    all_removed_warning = '<div class="all-removed-warning" style="display:none; color:#c62828; font-weight:bold; font-size:0.9em; margin-top:8px;">🚨 ALL copies selected for removal! This photo will be permanently deleted.</div>'

    # Warning 2: Edited pair both removed (only for edited pairs)
    edited_pair_warning = ''
    both_kept_warning = ''
    if has_edited_pair:
        edited_pair_warning = '<div class="edited-pair-warning" style="display:none; color:#ff9800; font-size:0.85em; margin-top:8px;">⚠️ Both original AND edited selected for removal!</div>'
        both_kept_warning = '<div class="both-kept-warning" style="display:none; color:#2196f3; font-size:0.85em; margin-top:8px;">ℹ️ Keeping both original AND edited—intentional? The edited version usually supersedes the original.</div>'

    return f'''
        <div class="duplicate-group" data-has-edited-pair="{'true' if has_edited_pair else 'false'}">
            <div style="margin-bottom:8px;">{type_badge}</div>
            <div class="duplicate-photos">
                {''.join(photos_html)}
            </div>
            {all_removed_warning}
            {edited_pair_warning}
            {both_kept_warning}
        </div>
'''


# ============================================================================
# CLI
# ============================================================================

def main():
    """Main entry point."""
    if not OPENCV_AVAILABLE:
        print("ERROR: OpenCV is required.")
        print("Install with: brew install opencv")
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Photo triage with context-aware batch decisions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  summary   Show issues grouped by folder
  blurry    Find blurry photos with surrounding context
  bursts    Detect and analyze photo bursts
  review    Generate HTML review report with KEEP/REMOVE buttons
  undo      Reverse previous moves (legacy)

Workflow:
  1. Run 'review' to generate an interactive HTML report
  2. Use KEEP/REMOVE buttons to mark decisions (saved to localStorage)
  3. Click "Export Remove List" to download a shell script
  4. Review and run the script to delete marked files

Examples:
  # Generate HTML review with 100 items per section (default)
  python3 photo_triage.py review Organized_Photos/2018/ --open

  # Generate full review (no limit)
  python3 photo_triage.py review Organized_Photos/ --open

  # Quick summary of all issues by folder
  python3 photo_triage.py summary Organized_Photos/

  # See blurry photos with their neighbors
  python3 photo_triage.py blurry Organized_Photos/2018/
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Summary command
    summary_parser = subparsers.add_parser('summary', help='Summarize issues by folder')
    summary_parser.add_argument('directory', nargs='?', default=None,
                                help='Directory to analyze (default: Organized_Photos/)')
    summary_parser.add_argument('--no-recursive', action='store_true')

    # Blurry command
    blurry_parser = subparsers.add_parser('blurry', help='Find blurry photos with context')
    blurry_parser.add_argument('directory', nargs='?', default=None,
                               help='Directory to scan (default: Organized_Photos/)')
    blurry_parser.add_argument('--threshold', type=float, default=BLUR_THRESHOLD_BLURRY)
    blurry_parser.add_argument('--no-recursive', action='store_true')
    blurry_parser.add_argument('--output', help='Save to CSV')

    # Bursts command
    bursts_parser = subparsers.add_parser('bursts', help='Detect and analyze bursts')
    bursts_parser.add_argument('directory', nargs='?', default=None,
                               help='Directory to scan (default: Organized_Photos/)')
    bursts_parser.add_argument('--window', type=int, default=BURST_WINDOW_SECONDS,
                               help='Seconds between burst photos')
    bursts_parser.add_argument('--no-recursive', action='store_true')

    # Undo command (legacy - for undoing previous moves)
    undo_parser = subparsers.add_parser('undo', help='Undo previous triage moves (legacy)')
    undo_parser.add_argument('directory', help='Directory to find manifest (or use --review-dir)')
    undo_parser.add_argument('--review-dir',
                               help='Directory containing manifest (auto-detected if not specified)')
    undo_parser.add_argument('--manifest', help='Path to manifest file')
    undo_parser.add_argument('--dry-run', action='store_true')

    # Review-issues command (blurry/duplicate HTML report)
    review_parser = subparsers.add_parser('review-issues', help='Generate HTML review report for blurry/duplicate photos')
    review_parser.add_argument('directory', nargs='?', default=None,
                               help='Directory to analyze (default: Organized_Photos/)')
    review_parser.add_argument('--output', '-o',
                               help='Output path for HTML (default: _TO_REVIEW_/.TMP_review_issues.html)')
    review_parser.add_argument('--no-duplicates', action='store_true',
                               help='Skip duplicate detection')
    review_parser.add_argument('--open', action='store_true',
                               help='Open report in browser after generation')

    # Browse command (all photos in collapsible directory view)
    browse_parser = subparsers.add_parser('browse', help='Browse ALL photos organized by directory with time grouping')
    browse_parser.add_argument('directory', nargs='?', default=None,
                               help='Directory to browse (default: Organized_Photos/)')
    browse_parser.add_argument('--output', '-o',
                               help='Output path for HTML (default: _TO_REVIEW_/.TMP_browse_all.html)')
    browse_parser.add_argument('--open', action='store_true',
                               help='Open report in browser after generation')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Resolve directory - use default if not specified
    def resolve_directory(dir_arg):
        if dir_arg:
            return Path(dir_arg)

        default_dir = find_default_directory()

        if default_dir:
            print(f"  Using default directory: {default_dir}")
            return default_dir

        print("ERROR: No directory specified and Organized_Photos/ not found.")
        print("       Run from the process-media directory or specify a path.")
        sys.exit(1)

    if args.command == 'summary':
        directory = resolve_directory(args.directory)
        summaries = summarize_by_folder(
            directory,
            recursive=not args.no_recursive
        )
        print_folder_summary(summaries)

    elif args.command == 'blurry':
        directory = resolve_directory(args.directory)
        results, unreadable = blurry_with_context(
            directory,
            blur_threshold=args.threshold,
            recursive=not args.no_recursive
        )

        print(f"\n{'=' * 70}")
        print(f"Blurry Photos with Context")
        print('=' * 70)
        print(f"\n  Found {len(results)} blurry photos")
        if unreadable:
            print(f"  Unreadable files: {len(unreadable)}")

        safe_count = sum(1 for r in results if r['safe_to_delete'])
        print(f"  Safe to delete (very blurry + sharp neighbor): {safe_count}")

        # Show results grouped by deletability
        if results:
            print(f"\n{'-' * 50}")
            print("Safe to Delete (very blurry with sharp alternative)")
            print('-' * 50)

            for item in sorted(results, key=lambda x: x['blur'])[:20]:
                if item['safe_to_delete']:
                    print(f"\n  {item['path'].name}")
                    print(f"    Blur: {item['blur']:.1f} ({item['interpretation']})")
                    print(f"    Nearby sharp photos:")

                    for ctx in item['context'][:2]:
                        if ctx['blur'] and ctx['blur'] >= BLUR_THRESHOLD_BLURRY:
                            print(f"      {ctx['path'].name} - {ctx['blur']:.1f} ({ctx['interpretation']})")

        if args.output:
            with open(args.output, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['Path', 'Blur', 'Safe to Delete', 'Has Sharp Neighbor'])

                for item in results:
                    writer.writerow([
                        str(item['path']),
                        f"{item['blur']:.1f}",
                        'Yes' if item['safe_to_delete'] else 'No',
                        'Yes' if item['has_sharp_neighbor'] else 'No'
                    ])

            print(f"\n  Results saved to: {args.output}")

    elif args.command == 'bursts':
        directory = resolve_directory(args.directory)
        pattern = '**/*' if not args.no_recursive else '*'

        all_photos = [
            p for p in directory.glob(pattern)
            if p.suffix.lower() in {e.lower() for e in IMAGE_EXTENSIONS}
            and p.is_file()
            and not p.is_symlink()  # Skip symlinks to avoid duplicate processing
            and REVIEW_BLURRY not in p.parts and REVIEW_DUPLICATES not in p.parts  # Skip review symlink subdirs
        ]

        bursts = detect_bursts(all_photos, window_seconds=args.window)

        print(f"\n{'=' * 70}")
        print(f"Burst Detection")
        print('=' * 70)
        print(f"\n  Found {len(bursts)} bursts ({sum(len(b) for b in bursts)} photos)")

        deletable_total = 0

        for i, burst in enumerate(bursts[:10]):
            analysis = analyze_burst(burst)
            deletable_total += len(analysis['deletable'])

            print(f"\n  Burst {i + 1}: {analysis['count']} photos")
            print(f"    Best: {analysis['best']['path'].name} (blur: {analysis['best']['blur']:.1f})")
            print(f"    Worst: {analysis['worst']['path'].name} (blur: {analysis['worst']['blur']:.1f})")

            if analysis['deletable']:
                print(f"    Deletable: {len(analysis['deletable'])} very blurry photos")

        if len(bursts) > 10:
            print(f"\n  ... and {len(bursts) - 10} more bursts")

        print(f"\n  Total deletable from bursts: {deletable_total}")

    elif args.command == 'undo':
        directory = resolve_directory(args.directory)
        review_dir = getattr(args, 'review_dir', None) or find_review_base(directory)
        manifest_path = args.manifest or (review_dir / MANIFEST_FILE)
        manifest = TriageManifest(manifest_path)

        if not manifest.moves:
            print("No moves to undo.")
            sys.exit(0)

        print(f"\n  Found {len(manifest.moves)} moves to undo")

        undone, errors = manifest.undo_all(dry_run=args.dry_run)

        if args.dry_run:
            print(f"\n  [DRY RUN] Would undo {len(manifest.moves)} moves")
        else:
            print(f"\n  Undone: {undone}")

            if errors:
                print(f"  Errors: {len(errors)}")

                for err in errors[:5]:
                    print(f"    {err}")

            # Clear manifest after successful undo
            manifest.moves = []
            manifest.save()

    elif args.command == 'review-issues':
        directory = resolve_directory(args.directory)

        output_path = generate_html_review(
            directory,
            output_path=args.output,
            include_duplicates=not args.no_duplicates
        )

        if args.open:
            import webbrowser
            webbrowser.open(f'file://{output_path}')

    elif args.command == 'browse':
        directory = resolve_directory(args.directory)

        output_path = generate_html_browse(
            directory,
            output_path=args.output
        )

        if args.open:
            import webbrowser
            webbrowser.open(f'file://{output_path}')

    # Always save all caches at the end
    save_all_caches()


if __name__ == "__main__":
    main()
