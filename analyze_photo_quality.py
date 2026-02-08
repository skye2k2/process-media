#!/usr/bin/env python3 -u
"""
Photo Quality Analysis Tool

Analyzes photos for blur detection and quality comparison between versions.
Optimized for batch processing thousands of images quickly.

Use cases:
- Detect blurry photos that should be reviewed or deleted
- Compare original vs edited (-edited suffix) pairs for quality differences
- Compare duplicate candidates to determine which is higher quality
- Batch analyze entire directories for quality triage

Usage:
    # Detect blurry photos in a directory
    python3 analyze_photo_quality.py blur Organized_Photos/2024/

    # Compare two specific images
    python3 analyze_photo_quality.py compare original.jpg edited.jpg

    # Find and compare all -edited pairs in a directory
    python3 analyze_photo_quality.py pairs Organized_Photos/2024/

    # Full analysis (blur + pairs) on a directory
    python3 analyze_photo_quality.py analyze Organized_Photos/

Blur Detection Interpretation:
    The Laplacian variance measures edge sharpness. Higher = sharper.

    150+     : Sharp (good quality)
    80-150   : Decent (acceptable quality)
    40-80    : Soft (may be intentional or minor focus issues)
    20-40    : Blurry (likely focus issues, needs review)
    <20      : Very blurry (high-confidence auto-triage candidates)

    Note: Thresholds vary by content. Portraits with bokeh will score lower
    in blurred regions but that's intentional. Low-texture images (walls,
    carpet, sky) are exempt from blur classification since Laplacian variance
    is naturally low for uniform subjects. The tool reports the score
    and you decide based on context.

SSIM Interpretation (same as video):
    1.0      : Identical
    >0.98    : Imperceptible difference
    0.95-0.98: Nearly indistinguishable
    0.90-0.95: Minor visible differences
    <0.90    : Noticeable differences
"""

import argparse
import csv
import hashlib
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from multiprocessing import cpu_count
from pathlib import Path

# ============================================================================
# CONFIGURATION
# ============================================================================

# Image extensions to process
IMAGE_EXTENSIONS = {
    '.jpg', '.jpeg', '.JPG', '.JPEG',
    '.png', '.PNG',
    '.heic', '.HEIC',
    '.webp', '.WEBP',
    '.tiff', '.TIFF', '.tif', '.TIF',
    '.bmp', '.BMP',
}

# Blur thresholds (higher = sharper)
# Photos below BLUR_THRESHOLD_BLURRY are flagged for review
BLUR_THRESHOLD_VERY_BLURRY = 20   # Definitely blurry, high-confidence auto-triage
BLUR_THRESHOLD_BLURRY = 40        # Blurry, needs manual review
BLUR_THRESHOLD_SOFT = 80          # Soft but often acceptable
BLUR_THRESHOLD_SHARP = 150        # Sharp

# Texture threshold for blur filtering
# Photos with edge density below this are "low texture" (walls, carpet, sky, etc.)
# and should not be classified as blurry since they naturally have low Laplacian variance
LOW_TEXTURE_EDGE_DENSITY = 0.02

# Parallel processing - leave headroom for system tasks
MAX_PARALLEL_WORKERS = 10

# Patterns for edited file detection
EDITED_SUFFIXES = ['-edited', '_edited', '-edit', '_edit', ' edited', ' (edited)']

# Cache settings
ANALYSIS_CACHE_FILE = ".analysis_cache.json"
PHASH_HAMMING_THRESHOLD = 5  # Images with hamming distance <= this are "similar"

# Subdirectories containing symlinks for manual review (exclude from scanning)
# These are within the _TO_REVIEW_ directory
REVIEW_SYMLINK_SUBDIRS = {"Blurry", "Duplicates"}

# ============================================================================
# DEPENDENCIES CHECK
# ============================================================================

try:
    import cv2
    import numpy as np
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False
    print("WARNING: OpenCV not installed. Install with: pip3 install opencv-python numpy")
    print("         Some features will be unavailable.\n")

# HEIC support via pillow-heif (Apple's image format)
try:
    from PIL import Image
    import pillow_heif
    # Register HEIF opener with PIL
    pillow_heif.register_heif_opener()
    HEIC_AVAILABLE = True
except ImportError:
    HEIC_AVAILABLE = False
    # Only warn if there might be HEIC files
    # print("Note: pillow-heif not installed. HEIC files won't be processed.")
    # print("      Install with: pip3 install pillow-heif")


def read_image_opencv(image_path, grayscale=False):
    """
    Read an image file, with HEIC support if available.

    Uses PIL+pillow-heif for HEIC files, then converts to OpenCV format.
    For other formats, uses OpenCV directly.

    Args:
        image_path: Path to image file
        grayscale: If True, return grayscale image

    Returns:
        numpy.ndarray: Image in OpenCV format (BGR or grayscale), or None if error
    """
    image_path = Path(image_path)
    suffix = image_path.suffix.lower()

    # Handle HEIC files specially
    if suffix in {'.heic', '.heif'}:
        if not HEIC_AVAILABLE:
            return None

        try:
            # Open with PIL (pillow-heif handles the HEIC decoding)
            pil_image = Image.open(image_path)

            # Convert to RGB if needed (HEIC can have various modes)
            if pil_image.mode != 'RGB':
                pil_image = pil_image.convert('RGB')

            # Convert PIL -> numpy array
            img_array = np.array(pil_image)

            # Convert RGB -> BGR for OpenCV compatibility
            img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)

            if grayscale:
                return cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

            return img_bgr

        except Exception as e:
            # Silently return None; caller handles missing images
            return None

    # Standard formats: use OpenCV directly
    if grayscale:
        return cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    else:
        return cv2.imread(str(image_path))


# ============================================================================
# UNIFIED ANALYSIS CACHE
# ============================================================================

class ImageAnalysisCache:
    """
    Unified persistent cache for all image analysis data.

    Stores computed values (blur score, MD5, perceptual hash) keyed by file
    path, with mtime and size for invalidation. Fields are populated lazily—
    each analysis adds its own fields without requiring all fields to exist.

    Cache entry structure:
    {
        "mtime": 1234567890.123,
        "size": 12345,
        "blur": 123.45,        # Optional: from blur detection
        "md5": "abc123...",    # Optional: from duplicate detection
        "phash": "def456..."   # Optional: from duplicate detection
    }
    """

    def __init__(self, cache_path):
        """
        Initialize the cache, migrating legacy caches if present.

        Args:
            cache_path: Path to the JSON cache file
        """
        self.cache_path = Path(cache_path)
        self.cache = {}
        self.dirty = False
        self._load()

    def _load(self):
        """Load cache from disk, migrating legacy caches if needed."""
        # Try to load existing unified cache
        if self.cache_path.exists():
            try:
                with open(self.cache_path, 'r') as f:
                    self.cache = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.cache = {}

    def save(self):
        """Save cache to disk if modified."""
        if self.dirty:
            with open(self.cache_path, 'w') as f:
                json.dump(self.cache, f, indent=2)
            self.dirty = False

    def _is_valid(self, file_path, entry):
        """Check if cache entry is still valid for the file."""
        try:
            stat = file_path.stat()
            return (
                entry.get('mtime') == stat.st_mtime and
                entry.get('size') == stat.st_size
            )
        except OSError:
            return False

    def get_blur(self, file_path):
        """
        Get cached blur score for a file if still valid.

        Args:
            file_path: Path to the image file

        Returns:
            float blur score, or None if not cached/invalid
        """
        file_path = Path(file_path).resolve()
        key = str(file_path)

        if key not in self.cache:
            return None

        entry = self.cache[key]

        if not self._is_valid(file_path, entry):
            return None

        return entry.get('blur')

    def set_blur(self, file_path, blur_score):
        """
        Store blur score for a file, preserving other cached values.

        Args:
            file_path: Path to the image file
            blur_score: Calculated blur score
        """
        file_path = Path(file_path).resolve()
        key = str(file_path)

        try:
            stat = file_path.stat()
        except OSError:
            return

        if key in self.cache:
            # Update existing entry
            self.cache[key]['mtime'] = stat.st_mtime
            self.cache[key]['size'] = stat.st_size
            self.cache[key]['blur'] = blur_score
        else:
            # New entry
            self.cache[key] = {
                'mtime': stat.st_mtime,
                'size': stat.st_size,
                'blur': blur_score
            }

        self.dirty = True

    def get_hashes(self, file_path):
        """
        Get cached hashes for a file if still valid.

        Args:
            file_path: Path to the image file

        Returns:
            dict with 'md5' and 'phash' keys, or None if not cached/invalid
        """
        file_path = Path(file_path).resolve()
        key = str(file_path)

        if key not in self.cache:
            return None

        entry = self.cache[key]

        if not self._is_valid(file_path, entry):
            return None

        # Only return if both hashes are present
        if entry.get('md5') and entry.get('phash'):
            return {
                'md5': entry.get('md5'),
                'phash': entry.get('phash')
            }

        return None

    def set_hashes(self, file_path, md5_hash, phash):
        """
        Store hashes for a file, preserving other cached values.

        Args:
            file_path: Path to the image file
            md5_hash: MD5 hash of file contents
            phash: Perceptual hash (as hex string)
        """
        file_path = Path(file_path).resolve()
        key = str(file_path)

        try:
            stat = file_path.stat()
        except OSError:
            return

        if key in self.cache:
            # Update existing entry
            self.cache[key]['mtime'] = stat.st_mtime
            self.cache[key]['size'] = stat.st_size
            self.cache[key]['md5'] = md5_hash
            self.cache[key]['phash'] = phash
        else:
            # New entry
            self.cache[key] = {
                'mtime': stat.st_mtime,
                'size': stat.st_size,
                'md5': md5_hash,
                'phash': phash
            }

        self.dirty = True

    def get_exif_date(self, file_path):
        """
        Get cached EXIF date timestamp for a file if still valid.

        Args:
            file_path: Path to the image file

        Returns:
            float timestamp (seconds since epoch), or None if not cached/invalid.
            Returns 0 if EXIF date was checked but not found in the file.
        """
        file_path = Path(file_path).resolve()
        key = str(file_path)

        if key not in self.cache:
            return None

        entry = self.cache[key]

        if not self._is_valid(file_path, entry):
            return None

        # 'exif_date' key stores timestamp or 0 if no EXIF date exists
        return entry.get('exif_date')

    def set_exif_date(self, file_path, timestamp):
        """
        Store EXIF date timestamp for a file, preserving other cached values.

        Args:
            file_path: Path to the image file
            timestamp: EXIF date as seconds since epoch, or 0 if no EXIF date
        """
        file_path = Path(file_path).resolve()
        key = str(file_path)

        try:
            stat = file_path.stat()
        except OSError:
            return

        if key in self.cache:
            # Update existing entry
            self.cache[key]['mtime'] = stat.st_mtime
            self.cache[key]['size'] = stat.st_size
            self.cache[key]['exif_date'] = timestamp
        else:
            # New entry
            self.cache[key] = {
                'mtime': stat.st_mtime,
                'size': stat.st_size,
                'exif_date': timestamp
            }

        self.dirty = True


# Global cache instance (one per directory, lazily initialized)
_analysis_caches = {}


def get_analysis_cache(directory=None):
    """
    Get or initialize the analysis cache for a directory.

    Args:
        directory: Directory to store cache in (uses cwd if None)

    Returns:
        ImageAnalysisCache instance
    """
    global _analysis_caches

    if directory is None:
        directory = Path.cwd()
    else:
        directory = Path(directory)

    key = str(directory)

    if key not in _analysis_caches:
        cache_path = directory / ANALYSIS_CACHE_FILE
        _analysis_caches[key] = ImageAnalysisCache(cache_path)

    return _analysis_caches[key]


def save_all_caches():
    """Save all analysis caches."""
    global _analysis_caches

    for cache in _analysis_caches.values():
        cache.save()


# ============================================================================
# PERCEPTUAL HASHING (OpenCV-based, no extra dependencies)
# ============================================================================

def compute_phash(image_path, hash_size=8):
    """
    Compute perceptual hash using DCT (similar to pHash algorithm).

    This implementation uses OpenCV only, no imagehash dependency needed.
    Supports HEIC files if pillow-heif is installed.

    Args:
        image_path: Path to image file
        hash_size: Size of hash (8 = 64-bit hash)

    Returns:
        str: Hex string of perceptual hash, or None if error
    """
    if not OPENCV_AVAILABLE:
        return None

    try:
        # Read image in grayscale (supports HEIC via read_image_opencv)
        img = read_image_opencv(image_path, grayscale=True)

        if img is None:
            return None

        # Resize to 32x32 for DCT (need more than hash_size for good DCT)
        img_resized = cv2.resize(img, (32, 32), interpolation=cv2.INTER_AREA)

        # Convert to float for DCT
        img_float = np.float32(img_resized)

        # Apply DCT
        dct = cv2.dct(img_float)

        # Extract top-left 8x8 (low frequencies, most important)
        dct_low = dct[:hash_size, :hash_size]

        # Compute median (excluding DC component)
        median = np.median(dct_low.flatten()[1:])

        # Create binary hash: 1 if above median, 0 if below
        hash_bits = (dct_low.flatten() > median).astype(int)

        # Convert to hex string
        hash_int = int(''.join(map(str, hash_bits)), 2)
        hash_hex = format(hash_int, f'0{hash_size * hash_size // 4}x')

        return hash_hex

    except Exception as e:
        print(f"  Error computing phash for {image_path}: {e}")
        return None


def compute_md5(file_path):
    """
    Compute MD5 hash of file contents.

    Args:
        file_path: Path to file

    Returns:
        str: MD5 hex digest
    """
    hash_md5 = hashlib.md5()

    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            hash_md5.update(chunk)

    return hash_md5.hexdigest()


def hamming_distance(hash1, hash2):
    """
    Compute hamming distance between two hex hash strings.

    Args:
        hash1: First hash (hex string)
        hash2: Second hash (hex string)

    Returns:
        int: Number of differing bits
    """
    if hash1 is None or hash2 is None:
        return float('inf')

    # Convert hex to int
    int1 = int(hash1, 16)
    int2 = int(hash2, 16)

    # XOR and count 1 bits
    xor = int1 ^ int2
    return bin(xor).count('1')


# ============================================================================
# DUPLICATE DETECTION
# ============================================================================

def _compute_file_hashes(file_path):
    """
    Worker function to compute MD5 and phash for a single file.
    Used for parallel hash computation in duplicate scanning.

    Args:
        file_path: Path to image file

    Returns:
        tuple: (file_path, md5, phash, error_message)
    """
    try:
        md5 = compute_md5(file_path)
        phash = compute_phash(file_path)
        return (file_path, md5, phash, None)
    except Exception as e:
        return (file_path, None, None, str(e))


def _compare_phash_chunk(args):
    """
    Worker function to compare a chunk of images for perceptual similarity.
    Returns list of (i, j) pairs that are within hamming threshold.

    Args:
        args: Tuple of (start_i, end_i, phashes, threshold)

    Returns:
        list: List of (i, j) tuples for similar image pairs
    """
    start_i, end_i, phashes, threshold = args
    similar_pairs = []

    for i in range(start_i, end_i):
        phash_i = phashes[i]

        for j in range(i + 1, len(phashes)):
            dist = hamming_distance(phash_i, phashes[j])

            if dist <= threshold:
                similar_pairs.append((i, j))

    return similar_pairs


def scan_for_duplicates(directory, recursive=True, hamming_threshold=PHASH_HAMMING_THRESHOLD):
    """
    Scan directory for duplicate images using MD5 and perceptual hashing.

    Args:
        directory: Path to scan
        recursive: Whether to scan subdirectories
        hamming_threshold: Max hamming distance for perceptual similarity

    Returns:
        dict: Results with 'exact_duplicates', 'similar_images', 'unique', 'errors'
    """
    directory = Path(directory)
    cache = get_analysis_cache(directory)

    results = {
        'exact_duplicates': {},   # MD5 -> list of paths
        'similar_groups': [],      # List of groups with similar phash
        'unique': [],
        'errors': [],
        'total': 0,
        'cached': 0,
        'computed': 0
    }

    # Collect all image files
    pattern = '**/*' if recursive else '*'
    image_files = []

    for file_path in directory.glob(pattern):
        if file_path.suffix.lower() not in {e.lower() for e in IMAGE_EXTENSIONS}:
            continue

        if not file_path.is_file():
            continue

        # Skip symlinks to avoid duplicate processing
        if file_path.is_symlink():
            continue

        # Skip review symlink subdirectories (Blurry, Duplicates)
        if any(subdir in file_path.parts for subdir in REVIEW_SYMLINK_SUBDIRS):
            continue

        # Skip cache file
        if file_path.name == ANALYSIS_CACHE_FILE:
            continue

        image_files.append(file_path)

    results['total'] = len(image_files)
    print(f"\nScanning {results['total']} images for duplicates...", flush=True)

    # Compute hashes for all images
    file_hashes = []  # List of (path, md5, phash)

    # Separate cached from uncached
    cached_hashes = []
    uncached_files = []

    for file_path in image_files:
        cached = cache.get_hashes(file_path)

        if cached and cached.get('md5') and cached.get('phash'):
            cached_hashes.append((file_path, cached['md5'], cached['phash']))
            results['cached'] += 1
        else:
            uncached_files.append(file_path)

    file_hashes.extend(cached_hashes)

    # Process uncached files in parallel
    if uncached_files:
        print(f"  Computing hashes for {len(uncached_files)} uncached images...", flush=True)

        processed = 0
        with ProcessPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as executor:
            futures = {executor.submit(_compute_file_hashes, fp): fp for fp in uncached_files}

            for future in as_completed(futures):
                processed += 1
                if processed % 500 == 0:
                    print(f"    Hashes: {processed}/{len(uncached_files)}", flush=True)

                file_path, md5, phash, error = future.result()

                if error or not phash:
                    results['errors'].append(file_path)
                else:
                    cache.set_hashes(file_path, md5, phash)
                    results['computed'] += 1
                    file_hashes.append((file_path, md5, phash))

    # Save cache
    cache.save()
    print(f"  Cached: {results['cached']}, Computed: {results['computed']}, Errors: {len(results['errors'])}")

    # Group by MD5 (exact duplicates)
    md5_groups = {}

    for path, md5, phash in file_hashes:
        if md5 not in md5_groups:
            md5_groups[md5] = []
        md5_groups[md5].append((path, phash))

    # Find exact duplicates (same MD5)
    for md5, files in md5_groups.items():
        if len(files) > 1:
            results['exact_duplicates'][md5] = [str(f[0]) for f in files]

    # Find perceptually similar images (different MD5 but similar phash)
    # Group unique MD5s first, then compare phashes
    unique_by_md5 = [(files[0][0], files[0][1]) for files in md5_groups.values()]

    # Build similarity groups using union-find approach
    n = len(unique_by_md5)
    parent = list(range(n))

    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    print(f"  Comparing {n} unique images for perceptual similarity...", flush=True)

    # Extract just the phashes for parallel comparison
    phashes = [item[1] for item in unique_by_md5]

    # Split work into chunks (roughly equal work per chunk)
    # Use smaller chunks for better load balancing since earlier i values do more work
    num_workers = MAX_PARALLEL_WORKERS
    chunk_size = max(100, n // (num_workers * 4))  # More chunks than workers for balancing
    chunks = []

    for start in range(0, n, chunk_size):
        end = min(start + chunk_size, n)
        chunks.append((start, end, phashes, hamming_threshold))

    # Process chunks in parallel
    all_similar_pairs = []
    processed_chunks = 0

    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = {executor.submit(_compare_phash_chunk, chunk): chunk for chunk in chunks}

        for future in as_completed(futures):
            processed_chunks += 1
            if processed_chunks % 10 == 0:
                print(f"    Chunks: {processed_chunks}/{len(chunks)}", flush=True)

            pairs = future.result()
            all_similar_pairs.extend(pairs)

    print(f"    Found {len(all_similar_pairs)} similar pairs, building groups...", flush=True)

    # Apply unions in main thread (fast, just pointer updates)
    for i, j in all_similar_pairs:
        union(i, j)

    # Collect similarity groups
    groups = {}

    for i in range(n):
        root = find(i)

        if root not in groups:
            groups[root] = []
        groups[root].append(unique_by_md5[i][0])

    # Only keep groups with multiple images
    for root, paths in groups.items():
        if len(paths) > 1:
            results['similar_groups'].append([str(p) for p in paths])
        else:
            results['unique'].append(str(paths[0]))

    return results


def print_duplicate_report(results, show_all=False):
    """
    Print formatted duplicate detection results.

    Args:
        results: Results from scan_for_duplicates
        show_all: Whether to show all duplicates (default: top 20)
    """
    print(f"\n{'=' * 70}")
    print("Duplicate Detection Results")
    print('=' * 70)

    print(f"\n  Total images scanned: {results['total']}")
    print(f"  Unique images: {len(results['unique'])}")
    print(f"  Exact duplicate groups: {len(results['exact_duplicates'])}")
    print(f"  Perceptually similar groups: {len(results['similar_groups'])}")
    print(f"  Errors: {len(results['errors'])}")

    # Calculate space wasted by exact duplicates
    total_wasted = 0
    duplicate_count = 0

    for md5, paths in results['exact_duplicates'].items():
        if len(paths) > 1:
            # First file is "original", rest are duplicates
            for dup_path in paths[1:]:
                try:
                    total_wasted += Path(dup_path).stat().st_size
                    duplicate_count += 1
                except OSError:
                    pass

    if duplicate_count > 0:
        print(f"\n  Space wasted by exact duplicates: {total_wasted / 1024 / 1024:.1f} MB ({duplicate_count} files)")

    # Show exact duplicates
    if results['exact_duplicates']:
        print(f"\n{'-' * 50}")
        print("Exact Duplicates (byte-identical)")
        print('-' * 50)

        shown = 0

        for md5, paths in sorted(results['exact_duplicates'].items(), key=lambda x: -len(x[1])):
            if not show_all and shown >= 10:
                remaining = len(results['exact_duplicates']) - shown
                print(f"\n  ... and {remaining} more duplicate groups")
                break

            print(f"\n  Group ({len(paths)} files):")

            for path in paths:
                size = Path(path).stat().st_size / 1024
                print(f"    {size:7.1f} KB | {path}")

            shown += 1

    # Show perceptually similar groups
    if results['similar_groups']:
        print(f"\n{'-' * 50}")
        print("Perceptually Similar (may be resized/recompressed)")
        print('-' * 50)

        shown = 0

        for group in sorted(results['similar_groups'], key=lambda x: -len(x)):
            if not show_all and shown >= 10:
                remaining = len(results['similar_groups']) - shown
                print(f"\n  ... and {remaining} more similar groups")
                break

            print(f"\n  Group ({len(group)} files):")

            for path in group:
                try:
                    size = Path(path).stat().st_size / 1024
                    print(f"    {size:7.1f} KB | {path}")
                except OSError:
                    print(f"    [error] | {path}")

            shown += 1


# ============================================================================
# BLUR DETECTION
# ============================================================================

def calculate_edge_density(image):
    """
    Calculate edge density of an image (how much texture/detail it contains).

    Low-texture images (walls, carpet, sky, solid colors) naturally have low
    Laplacian variance even when perfectly in focus. This metric helps identify
    such images to avoid false "blurry" classifications.

    Args:
        image: Grayscale numpy array

    Returns:
        float: Edge density (0.0 to 1.0), where higher = more texture
    """
    edges = cv2.Canny(image, 50, 150)
    return np.sum(edges > 0) / edges.size


def calculate_blur_score(image_path, use_cache=True, return_texture=False):
    """
    Calculate blur score using Laplacian variance with center-weight boost.

    The Laplacian highlights edges. In a sharp image, edges are well-defined
    and the variance is high. In a blurry image, edges are smeared and
    variance is low.

    For portrait/bokeh photos where the subject is sharp but background is
    intentionally blurred, we also check the center region. If the center
    is significantly sharper than the overall image, we use a weighted
    combination to avoid false positives.

    Args:
        image_path: Path to image file
        use_cache: Whether to use/update the analysis cache (default True)
        return_texture: If True, return (blur_score, edge_density) tuple

    Returns:
        float: Blur score (higher = sharper), or None if unreadable
        If return_texture=True: tuple of (blur_score, edge_density)
    """
    if not OPENCV_AVAILABLE:
        return (None, None) if return_texture else None

    image_path = Path(image_path)

    # Check cache first (texture is not cached, only blur score)
    if use_cache and not return_texture:
        cache = get_analysis_cache(image_path.parent)
        cached_score = cache.get_blur(image_path)

        if cached_score is not None:
            return cached_score

    try:
        # Read image in grayscale (supports HEIC via read_image_opencv)
        image = read_image_opencv(image_path, grayscale=True)

        if image is None:
            return (None, None) if return_texture else None

        # Calculate edge density (texture metric)
        edge_density = calculate_edge_density(image)

        # Calculate overall Laplacian variance
        laplacian = cv2.Laplacian(image, cv2.CV_64F)
        overall_score = laplacian.var()

        # Calculate center region score (middle 50% of image)
        # This helps with portrait/bokeh photos where subject is sharp
        h, w = image.shape[:2]
        center_y1, center_y2 = h // 4, 3 * h // 4
        center_x1, center_x2 = w // 4, 3 * w // 4
        center_region = image[center_y1:center_y2, center_x1:center_x2]

        center_laplacian = cv2.Laplacian(center_region, cv2.CV_64F)
        center_score = center_laplacian.var()

        # If center is significantly sharper (2x+), it's likely intentional bokeh
        # Use a weighted score that favors the center
        if center_score > overall_score * 2:
            # Bokeh detected: weight center heavily (70% center, 30% overall)
            score = center_score * 0.7 + overall_score * 0.3
        else:
            # Normal photo: use overall score
            score = overall_score

        # Store in cache
        if use_cache:
            cache = get_analysis_cache(image_path.parent)
            cache.set_blur(image_path, score)

        if return_texture:
            return (score, edge_density)
        return score

    except Exception as e:
        print(f"  Error reading {image_path}: {e}")
        return (None, None) if return_texture else None


def interpret_blur_score(score):
    """Return human-readable interpretation of blur score."""
    if score is None:
        return "Unknown"
    elif score >= BLUR_THRESHOLD_SHARP:
        return "Fully sharp"
    elif score >= BLUR_THRESHOLD_SOFT:
        return "Sharp"
    elif score >= BLUR_THRESHOLD_BLURRY:
        return "Decent"
    elif score >= BLUR_THRESHOLD_VERY_BLURRY:
        return "Soft"
    else:
        return "Blurry"


def is_photo_blurry(image_path, threshold=BLUR_THRESHOLD_BLURRY, use_texture_filter=True):
    """
    Determine if a photo is blurry, accounting for low-texture subjects.

    Low-texture images (walls, carpet, sky, solid colors) naturally have low
    Laplacian variance even when perfectly in focus. This function filters out
    such images to avoid false positives.

    Args:
        image_path: Path to image file
        threshold: Blur score threshold (below this = blurry)
        use_texture_filter: If True, exempt low-texture images from blur classification

    Returns:
        dict with keys:
            'is_blurry': bool - whether the photo should be considered blurry
            'blur_score': float - the raw blur score
            'edge_density': float - texture metric (if texture filter enabled)
            'low_texture': bool - whether the image is low-texture
            'reason': str - explanation of the classification
    """
    if use_texture_filter:
        blur_score, edge_density = calculate_blur_score(image_path, return_texture=True)
    else:
        blur_score = calculate_blur_score(image_path)
        edge_density = None

    if blur_score is None:
        return {
            'is_blurry': False,
            'blur_score': None,
            'edge_density': edge_density,
            'low_texture': False,
            'reason': 'Unable to read image'
        }

    low_texture = edge_density is not None and edge_density < LOW_TEXTURE_EDGE_DENSITY

    # Low-texture images are exempt from blur classification
    # (they naturally have low Laplacian variance even when sharp)
    if use_texture_filter and low_texture:
        return {
            'is_blurry': False,
            'blur_score': blur_score,
            'edge_density': edge_density,
            'low_texture': True,
            'reason': f'Low-texture image (edge_density={edge_density:.4f})'
        }

    is_blurry = blur_score < threshold

    return {
        'is_blurry': is_blurry,
        'blur_score': blur_score,
        'edge_density': edge_density,
        'low_texture': low_texture,
        'reason': f'Blur score {blur_score:.1f} {"<" if is_blurry else ">="} {threshold}'
    }


def _process_single_image(args):
    """
    Worker function for parallel blur detection.

    Note: Workers don't update cache (cross-process caching is complex).
    Cache is checked/updated by the main process before/after parallel work.

    Args:
        args: Tuple of (file_path, threshold)

    Returns:
        dict: Result with path, score, interpretation, and status
    """
    file_path, threshold = args
    try:
        # Don't use cache in workers - main process handles caching
        score = calculate_blur_score(file_path, use_cache=False)

        if score is None:
            return {'path': file_path, 'status': 'error'}

        return {
            'path': file_path,
            'score': score,
            'interpretation': interpret_blur_score(score),
            'status': 'blurry' if score < threshold else 'sharp'
        }
    except Exception as e:
        return {'path': file_path, 'status': 'error', 'error': str(e)}


def scan_for_blur(directory, threshold=BLUR_THRESHOLD_BLURRY, recursive=True, max_workers=None):
    """
    Scan directory for blurry images using parallel processing.

    Args:
        directory: Path to scan
        threshold: Score below this is considered blurry
        recursive: Whether to scan subdirectories
        max_workers: Number of parallel workers (default: CPU count)

    Returns:
        dict: Results with 'blurry', 'sharp', 'errors' lists
    """
    directory = Path(directory)
    results = {
        'blurry': [],
        'sharp': [],
        'errors': [],
        'total': 0,
        'cached': 0
    }

    # Determine worker count - cap at MAX_PARALLEL_WORKERS to leave headroom
    if max_workers is None:
        max_workers = min(cpu_count(), MAX_PARALLEL_WORKERS)

    pattern = '**/*' if recursive else '*'

    print(f"\nScanning for blurry images (threshold: {threshold})...")
    print(f"Directory: {directory}")
    print(f"Using {max_workers} parallel workers\n")

    # Collect all image files first
    image_files = []
    lower_extensions = {e.lower() for e in IMAGE_EXTENSIONS}

    for file_path in directory.glob(pattern):
        if file_path.suffix.lower() not in lower_extensions:
            continue
        if not file_path.is_file():
            continue
        # Skip symlinks to avoid duplicate processing
        if file_path.is_symlink():
            continue
        # Skip review symlink subdirectories (Blurry, Duplicates)
        if any(subdir in file_path.parts for subdir in REVIEW_SYMLINK_SUBDIRS):
            continue
        image_files.append(file_path)

    total_files = len(image_files)
    print(f"Found {total_files} images to process...")

    # First pass: check cache for already-computed values (main process)
    files_to_process = []
    for file_path in image_files:
        cache = get_analysis_cache(file_path.parent)
        cached_score = cache.get_blur(file_path)

        if cached_score is not None:
            results['total'] += 1
            results['cached'] += 1
            entry = {
                'path': file_path,
                'score': cached_score,
                'interpretation': interpret_blur_score(cached_score)
            }
            if cached_score < threshold:
                results['blurry'].append(entry)
            else:
                results['sharp'].append(entry)
        else:
            files_to_process.append(file_path)

    if results['cached'] > 0:
        print(f"  Found {results['cached']} cached results")

    if not files_to_process:
        print("  All images already cached!")
        return results

    print(f"  Processing {len(files_to_process)} uncached images...")

    # Process uncached images in parallel
    processed = 0
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks with threshold
        futures = {
            executor.submit(_process_single_image, (fp, threshold)): fp
            for fp in files_to_process
        }

        for future in as_completed(futures):
            processed += 1
            results['total'] += 1

            # Progress indicator every 100 images
            if processed % 100 == 0:
                pct = (processed / len(files_to_process)) * 100
                print(f"  Processed {processed}/{len(files_to_process)} ({pct:.0f}%)...")

            try:
                result = future.result()

                if result['status'] == 'error':
                    results['errors'].append(result['path'])
                else:
                    # Update cache in main process
                    cache = get_analysis_cache(result['path'].parent)
                    cache.set_blur(result['path'], result['score'])

                    if result['status'] == 'blurry':
                        results['blurry'].append({
                            'path': result['path'],
                            'score': result['score'],
                            'interpretation': result['interpretation']
                        })
                    else:
                        results['sharp'].append({
                            'path': result['path'],
                            'score': result['score'],
                            'interpretation': result['interpretation']
                        })
            except Exception as e:
                results['errors'].append(futures[future])

    # Save all caches
    save_all_caches()
    print(f"  Cache updated with {processed} new entries")

    return results

    return results


# ============================================================================
# IMAGE COMPARISON (SSIM)
# ============================================================================

def calculate_image_ssim(image1_path, image2_path):
    """
    Calculate SSIM between two images.

    Images are resized to match if dimensions differ.

    Args:
        image1_path: Path to first image
        image2_path: Path to second image

    Returns:
        float: SSIM value (0-1), or None if error
    """
    if not OPENCV_AVAILABLE:
        return None

    try:
        # Read images (supports HEIC via read_image_opencv)
        img1 = read_image_opencv(image1_path)
        img2 = read_image_opencv(image2_path)

        if img1 is None or img2 is None:
            return None

        # Resize if dimensions differ (use smaller dimensions)
        h1, w1 = img1.shape[:2]
        h2, w2 = img2.shape[:2]

        if (h1, w1) != (h2, w2):
            # Resize to smaller dimensions
            target_h = min(h1, h2)
            target_w = min(w1, w2)
            img1 = cv2.resize(img1, (target_w, target_h))
            img2 = cv2.resize(img2, (target_w, target_h))

        # Convert to grayscale for SSIM
        gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)

        # Calculate SSIM
        # Using a simplified SSIM calculation for speed
        c1 = 6.5025  # (0.01 * 255) ** 2
        c2 = 58.5225  # (0.03 * 255) ** 2

        gray1 = gray1.astype(np.float64)
        gray2 = gray2.astype(np.float64)

        # Calculate means
        mu1 = cv2.GaussianBlur(gray1, (11, 11), 1.5)
        mu2 = cv2.GaussianBlur(gray2, (11, 11), 1.5)

        mu1_sq = mu1 ** 2
        mu2_sq = mu2 ** 2
        mu1_mu2 = mu1 * mu2

        # Calculate variances and covariance
        sigma1_sq = cv2.GaussianBlur(gray1 ** 2, (11, 11), 1.5) - mu1_sq
        sigma2_sq = cv2.GaussianBlur(gray2 ** 2, (11, 11), 1.5) - mu2_sq
        sigma12 = cv2.GaussianBlur(gray1 * gray2, (11, 11), 1.5) - mu1_mu2

        # Calculate SSIM
        ssim_map = ((2 * mu1_mu2 + c1) * (2 * sigma12 + c2)) / \
                   ((mu1_sq + mu2_sq + c1) * (sigma1_sq + sigma2_sq + c2))

        return float(ssim_map.mean())

    except Exception as e:
        print(f"  Error comparing images: {e}")
        return None


def interpret_ssim(ssim_value):
    """Return human-readable interpretation of SSIM value."""
    if ssim_value is None:
        return "Unknown"
    elif ssim_value >= 1.0:
        return "Identical"
    elif ssim_value >= 0.98:
        return "Imperceptible difference"
    elif ssim_value >= 0.95:
        return "Nearly indistinguishable"
    elif ssim_value >= 0.90:
        return "Minor visible differences"
    elif ssim_value >= 0.85:
        return "Noticeable differences"
    else:
        return "Significant differences"


def compare_images(image1_path, image2_path, include_blur=True):
    """
    Compare two images for quality.

    Args:
        image1_path: Path to first image
        image2_path: Path to second image
        include_blur: Whether to include blur scores

    Returns:
        dict: Comparison results
    """
    image1_path = Path(image1_path)
    image2_path = Path(image2_path)

    result = {
        'image1': {
            'path': image1_path,
            'size': image1_path.stat().st_size if image1_path.exists() else 0,
        },
        'image2': {
            'path': image2_path,
            'size': image2_path.stat().st_size if image2_path.exists() else 0,
        },
        'ssim': None,
        'ssim_interpretation': None,
    }

    # Calculate SSIM
    ssim = calculate_image_ssim(image1_path, image2_path)
    result['ssim'] = ssim
    result['ssim_interpretation'] = interpret_ssim(ssim)

    # Calculate blur scores if requested
    if include_blur:
        blur1 = calculate_blur_score(image1_path)
        blur2 = calculate_blur_score(image2_path)

        result['image1']['blur_score'] = blur1
        result['image1']['blur_interpretation'] = interpret_blur_score(blur1)
        result['image2']['blur_score'] = blur2
        result['image2']['blur_interpretation'] = interpret_blur_score(blur2)

        # Determine which is sharper
        if blur1 is not None and blur2 is not None:
            if blur1 > blur2 * 1.1:  # 10% threshold
                result['sharper'] = 'image1'
            elif blur2 > blur1 * 1.1:
                result['sharper'] = 'image2'
            else:
                result['sharper'] = 'similar'

    return result


# ============================================================================
# EDITED PAIR DETECTION
# ============================================================================

def find_edited_pairs(directory, recursive=True):
    """
    Find original and -edited file pairs.

    Args:
        directory: Path to scan
        recursive: Whether to scan subdirectories

    Returns:
        list: List of (original_path, edited_path) tuples
    """
    directory = Path(directory)
    pairs = []

    pattern = '**/*' if recursive else '*'

    # Build set of all image files
    all_files = {}

    for file_path in directory.glob(pattern):
        if file_path.suffix.lower() not in {e.lower() for e in IMAGE_EXTENSIONS}:
            continue

        if not file_path.is_file():
            continue

        # Skip symlinks to avoid duplicate processing
        if file_path.is_symlink():
            continue

        # Skip review symlink subdirectories (Blurry, Duplicates)
        if any(subdir in file_path.parts for subdir in REVIEW_SYMLINK_SUBDIRS):
            continue

        all_files[str(file_path)] = file_path

    # Find edited files and match to originals
    for file_str, file_path in all_files.items():
        stem = file_path.stem

        for suffix in EDITED_SUFFIXES:
            if stem.lower().endswith(suffix.lower()):
                # This is an edited file, find original
                original_stem = stem[:-len(suffix)]

                # Look for original with same extension
                original_path = file_path.parent / f"{original_stem}{file_path.suffix}"

                if str(original_path) in all_files:
                    pairs.append((original_path, file_path))
                    break

                # Try other extensions
                for ext in IMAGE_EXTENSIONS:
                    original_path = file_path.parent / f"{original_stem}{ext}"

                    if str(original_path) in all_files:
                        pairs.append((original_path, file_path))
                        break

    return pairs


def analyze_edited_pairs(directory, recursive=True):
    """
    Find and analyze all edited pairs in a directory.

    Args:
        directory: Path to scan
        recursive: Whether to scan subdirectories

    Returns:
        list: Analysis results for each pair
    """
    pairs = find_edited_pairs(directory, recursive)

    if not pairs:
        print("No edited pairs found.")
        return []

    print(f"\nFound {len(pairs)} edited pairs\n")

    results = []

    for original, edited in pairs:
        print(f"  Comparing: {original.name}")
        print(f"       with: {edited.name}")

        comparison = compare_images(original, edited)
        comparison['original'] = original
        comparison['edited'] = edited
        results.append(comparison)

        # Print summary
        if comparison['ssim'] is not None:
            print(f"    SSIM: {comparison['ssim']:.4f} ({comparison['ssim_interpretation']})")

        if 'sharper' in comparison:
            if comparison['sharper'] == 'image1':
                print(f"    Sharper: Original")
            elif comparison['sharper'] == 'image2':
                print(f"    Sharper: Edited")
            else:
                print(f"    Sharpness: Similar")

        print()

    return results


# ============================================================================
# FULL ANALYSIS
# ============================================================================

def full_analysis(directory, blur_threshold=BLUR_THRESHOLD_BLURRY, recursive=True, output_csv=None):
    """
    Perform full quality analysis on a directory.

    Args:
        directory: Path to analyze
        blur_threshold: Score below this is flagged as blurry
        recursive: Whether to scan subdirectories
        output_csv: Optional path to save results as CSV

    Returns:
        dict: Full analysis results
    """
    directory = Path(directory)

    print(f"\n{'=' * 70}")
    print("Photo Quality Analysis")
    print('=' * 70)
    print(f"\nDirectory: {directory}")
    print(f"Recursive: {recursive}")
    print(f"Blur threshold: {blur_threshold}")

    # Scan for blur
    print(f"\n{'-' * 50}")
    print("Phase 1: Blur Detection")
    print('-' * 50)

    blur_results = scan_for_blur(directory, blur_threshold, recursive)

    print(f"\n  Total images scanned: {blur_results['total']}")
    print(f"  Sharp images: {len(blur_results['sharp'])}")
    print(f"  Blurry images: {len(blur_results['blurry'])}")
    print(f"  Errors: {len(blur_results['errors'])}")

    # List blurry images
    if blur_results['blurry']:
        print(f"\n  Blurry images (score < {blur_threshold}):")

        # Sort by score (lowest/blurriest first)
        sorted_blurry = sorted(blur_results['blurry'], key=lambda x: x['score'])

        for entry in sorted_blurry[:20]:  # Show top 20
            rel_path = entry['path'].relative_to(directory) if entry['path'].is_relative_to(directory) else entry['path']
            print(f"    {entry['score']:6.1f} | {entry['interpretation']:12} | {rel_path}")

        if len(sorted_blurry) > 20:
            print(f"    ... and {len(sorted_blurry) - 20} more")

    # Find edited pairs
    print(f"\n{'-' * 50}")
    print("Phase 2: Edited Pair Analysis")
    print('-' * 50)

    pair_results = analyze_edited_pairs(directory, recursive)

    # Summary
    print(f"\n{'=' * 70}")
    print("Summary")
    print('=' * 70)

    print(f"\n  Total images: {blur_results['total']}")
    print(f"  Blurry (needs review): {len(blur_results['blurry'])}")
    print(f"  Edited pairs found: {len(pair_results)}")

    # Calculate potential space savings from edited pairs
    if pair_results:
        total_edited_size = sum(r['image2']['size'] for r in pair_results)
        print(f"  Edited files total size: {total_edited_size / 1024 / 1024:.1f} MB")

    # Save CSV if requested
    if output_csv:
        output_path = Path(output_csv)

        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Path', 'Blur Score', 'Blur Interpretation', 'Is Blurry'])

            for entry in blur_results['sharp'] + blur_results['blurry']:
                is_blurry = entry['score'] < blur_threshold
                writer.writerow([
                    str(entry['path']),
                    f"{entry['score']:.1f}",
                    entry['interpretation'],
                    'Yes' if is_blurry else 'No'
                ])

        print(f"\n  Results saved to: {output_path}")

    return {
        'blur': blur_results,
        'pairs': pair_results
    }


# ============================================================================
# CLI
# ============================================================================

def main():
    """Main entry point."""
    if not OPENCV_AVAILABLE:
        print("ERROR: OpenCV is required for photo analysis.")
        print("Install with: pip3 install opencv-python numpy")
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Analyze photo quality: blur detection and version comparison",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  blur       Scan for blurry images
  compare    Compare two specific images
  pairs      Find and compare -edited pairs
  duplicates Find exact and perceptual duplicates
  analyze    Full analysis (blur + pairs)

Examples:
  # Find blurry photos
  python3 analyze_photo_quality.py blur Organized_Photos/2024/

  # Compare original vs edited
  python3 analyze_photo_quality.py compare photo.jpg photo-edited.jpg

  # Find all edited pairs and compare
  python3 analyze_photo_quality.py pairs Organized_Photos/

  # Find duplicate photos (uses cached hashes for speed)
  python3 analyze_photo_quality.py duplicates Organized_Photos/

  # Full analysis with CSV output
  python3 analyze_photo_quality.py analyze Organized_Photos/ --output results.csv

Blur Detection Interpretation:
    The Laplacian variance measures edge sharpness. Higher = sharper.

    150+     : Sharp (good quality)
    80-150   : Decent (acceptable quality)
    40-80    : Soft (may be intentional or minor focus issues)
    20-40    : Blurry (likely focus issues, needs review)
    <20      : Very blurry (high-confidence auto-triage candidates)

Note: Thresholds vary by content. Portraits with bokeh will score lower
in blurred regions but that's intentional. Low-texture images (walls,
carpet, sky) are exempt from blur classification since Laplacian variance
is naturally low for uniform subjects. The tool reports the score
and you decide based on context.

SSIM Interpretation (Structural Similarity Index):
  1.0      : Identical
  >0.98    : Imperceptible difference
  0.95-0.98: Nearly indistinguishable
  0.90-0.95: Minor visible differences
  <0.90    : Noticeable differences
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Blur command
    blur_parser = subparsers.add_parser('blur', help='Detect blurry images')
    blur_parser.add_argument('directory', nargs='?', default='Organized_Photos/',
                             help='Directory to scan (default: Organized_Photos/)')
    blur_parser.add_argument('--threshold', type=float, default=BLUR_THRESHOLD_BLURRY,
                             help=f'Blur threshold (default: {BLUR_THRESHOLD_BLURRY})')
    blur_parser.add_argument('--no-recursive', action='store_true',
                             help='Only scan top-level directory')
    blur_parser.add_argument('--output', help='Save results to CSV file')

    # Compare command
    compare_parser = subparsers.add_parser('compare', help='Compare two images')
    compare_parser.add_argument('image1', help='First image path')
    compare_parser.add_argument('image2', help='Second image path')

    # Pairs command
    pairs_parser = subparsers.add_parser('pairs', help='Find and compare edited pairs')
    pairs_parser.add_argument('directory', nargs='?', default='Organized_Photos/',
                              help='Directory to scan (default: Organized_Photos/)')
    pairs_parser.add_argument('--no-recursive', action='store_true',
                              help='Only scan top-level directory')

    # Duplicates command
    dup_parser = subparsers.add_parser('duplicates', help='Find duplicate images')
    dup_parser.add_argument('directory', nargs='?', default='Organized_Photos/',
                            help='Directory to scan (default: Organized_Photos/)')
    dup_parser.add_argument('--no-recursive', action='store_true',
                            help='Only scan top-level directory')
    dup_parser.add_argument('--threshold', type=int, default=PHASH_HAMMING_THRESHOLD,
                            help=f'Perceptual hash hamming distance threshold (default: {PHASH_HAMMING_THRESHOLD})')
    dup_parser.add_argument('--output', help='Save results to CSV file')
    dup_parser.add_argument('--all', action='store_true',
                            help='Show all duplicates (default: top 10 groups)')

    # Analyze command
    analyze_parser = subparsers.add_parser('analyze', help='Full quality analysis')
    analyze_parser.add_argument('directory', nargs='?', default='Organized_Photos/',
                                help='Directory to analyze (default: Organized_Photos/)')
    analyze_parser.add_argument('--threshold', type=float, default=BLUR_THRESHOLD_BLURRY,
                                help=f'Blur threshold (default: {BLUR_THRESHOLD_BLURRY})')
    analyze_parser.add_argument('--no-recursive', action='store_true',
                                help='Only scan top-level directory')
    analyze_parser.add_argument('--output', help='Save results to CSV file')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == 'blur':
        results = scan_for_blur(
            args.directory,
            threshold=args.threshold,
            recursive=not args.no_recursive
        )

        print(f"\n{'=' * 50}")
        print(f"Total: {results['total']} images")
        print(f"Blurry: {len(results['blurry'])} images")
        print(f"Sharp: {len(results['sharp'])} images")

        if results['blurry']:
            print(f"\nBlurry images:")

            for entry in sorted(results['blurry'], key=lambda x: x['score'])[:20]:
                print(f"  {entry['score']:6.1f} | {entry['interpretation']:12} | {entry['path'].name}")

        if args.output:
            with open(args.output, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['Path', 'Blur Score', 'Interpretation'])

                for entry in sorted(results['blurry'], key=lambda x: x['score']):
                    writer.writerow([str(entry['path']), f"{entry['score']:.1f}", entry['interpretation']])

            print(f"\nResults saved to: {args.output}")

    elif args.command == 'compare':
        if not Path(args.image1).exists():
            print(f"ERROR: File not found: {args.image1}")
            sys.exit(1)

        if not Path(args.image2).exists():
            print(f"ERROR: File not found: {args.image2}")
            sys.exit(1)

        result = compare_images(args.image1, args.image2)

        print(f"\n{'=' * 50}")
        print("Image Comparison Results")
        print('=' * 50)

        print(f"\n  Image 1: {Path(args.image1).name}")
        print(f"    Size: {result['image1']['size'] / 1024:.1f} KB")

        if 'blur_score' in result['image1']:
            print(f"    Blur: {result['image1']['blur_score']:.1f} ({result['image1']['blur_interpretation']})")

        print(f"\n  Image 2: {Path(args.image2).name}")
        print(f"    Size: {result['image2']['size'] / 1024:.1f} KB")

        if 'blur_score' in result['image2']:
            print(f"    Blur: {result['image2']['blur_score']:.1f} ({result['image2']['blur_interpretation']})")

        print(f"\n  SSIM: {result['ssim']:.4f}")
        print(f"    → {result['ssim_interpretation']}")

        if 'sharper' in result:
            if result['sharper'] == 'image1':
                print(f"\n  ✓ Image 1 is sharper")
            elif result['sharper'] == 'image2':
                print(f"\n  ✓ Image 2 is sharper")
            else:
                print(f"\n  ≈ Similar sharpness")

    elif args.command == 'pairs':
        analyze_edited_pairs(args.directory, recursive=not args.no_recursive)

    elif args.command == 'duplicates':
        results = scan_for_duplicates(
            args.directory,
            recursive=not args.no_recursive,
            hamming_threshold=args.threshold
        )

        print_duplicate_report(results, show_all=args.all)

        if args.output:
            with open(args.output, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['Type', 'Group', 'Path', 'Size (KB)'])

                group_num = 1

                for md5, paths in results['exact_duplicates'].items():
                    for path in paths:
                        try:
                            size = Path(path).stat().st_size / 1024
                        except OSError:
                            size = 0
                        writer.writerow(['Exact', group_num, path, f"{size:.1f}"])

                    group_num += 1

                for group in results['similar_groups']:
                    for path in group:
                        try:
                            size = Path(path).stat().st_size / 1024
                        except OSError:
                            size = 0
                        writer.writerow(['Similar', group_num, path, f"{size:.1f}"])

                    group_num += 1

            print(f"\n  Results saved to: {args.output}")

    elif args.command == 'analyze':
        full_analysis(
            args.directory,
            blur_threshold=args.threshold,
            recursive=not args.no_recursive,
            output_csv=args.output
        )


if __name__ == "__main__":
    main()
