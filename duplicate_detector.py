#!/usr/bin/env python3
"""
Smart Duplicate Detection Module

Multi-signal duplicate detection for media files, using:
1. Filename date pattern matching (YYYYMMDD_HHMMSS)
2. Video/audio duration matching
3. File size comparison
4. Quality analysis for size mismatches

When files have matching dates and durations but different sizes,
performs quality analysis to determine which version to prefer.

Usage:
    from duplicate_detector import DuplicateDetector

    detector = DuplicateDetector(organized_photos_dir, organized_videos_dir)
    result = detector.find_duplicate(source_file)

    if result.is_duplicate:
        if result.prefer_existing:
            # Skip the source file, existing is better or equal
        else:
            # Source is better quality, consider replacing existing
"""

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from analyze_photo_quality import compute_md5, get_analysis_cache, save_all_caches
from build_file_index import build_file_index
from media_utils import VIDEO_EXTENSIONS

# Hashes of incoming source files, stored beside this module rather than in the
# source tree. See DuplicateDetector._hash_source() for the rationale.
SOURCE_HASH_CACHE_FILE = ".source_hash_cache.json"


class MatchConfidence(Enum):
    """Confidence level of duplicate match."""
    NONE = 0           # No match found
    LOW = 1            # Only date pattern matches
    MEDIUM = 2         # Date + duration match, but size differs significantly
    HIGH = 3           # Date + duration + similar size
    EXACT = 4          # Identical file (same size, same duration)


@dataclass
class QualityInfo:
    """Video quality metrics."""
    codec: str
    width: int
    height: int
    bitrate: int           # Video bitrate in bps
    duration: float        # Duration in seconds
    file_size: int         # File size in bytes

    @property
    def pixels(self) -> int:
        """Total pixels (resolution)."""
        return self.width * self.height

    @property
    def bits_per_pixel_per_second(self) -> float:
        """Encoding efficiency metric (lower = more compressed)."""
        if self.pixels == 0 or self.duration == 0:
            return 0
        return self.bitrate / self.pixels


@dataclass
class DuplicateResult:
    """Result of duplicate detection."""
    is_duplicate: bool
    confidence: MatchConfidence
    existing_path: Optional[Path]
    prefer_existing: bool
    reason: str
    source_quality: Optional[QualityInfo] = None
    existing_quality: Optional[QualityInfo] = None


# ============================================================================
# QUALITY ANALYSIS
# ============================================================================

def get_video_quality(file_path: Path) -> Optional[QualityInfo]:
    """
    Extract quality metrics from a video file using ffprobe.

    Args:
        file_path: Path to the video file

    Returns:
        QualityInfo or None if extraction fails
    """
    try:
        # Get video stream info
        result = subprocess.run(
            [
                'ffprobe', '-v', 'quiet',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=codec_name,width,height,bit_rate',
                '-of', 'csv=p=0',
                str(file_path)
            ],
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode != 0 or not result.stdout.strip():
            return None

        parts = result.stdout.strip().split(',')

        if len(parts) < 4:
            return None

        codec = parts[0]
        width = int(parts[1]) if parts[1] else 0
        height = int(parts[2]) if parts[2] else 0

        # Bitrate might be "N/A" or empty
        try:
            bitrate = int(parts[3]) if parts[3] and parts[3] != 'N/A' else 0
        except ValueError:
            bitrate = 0

        # Get duration
        duration_result = subprocess.run(
            [
                'ffprobe', '-v', 'quiet',
                '-show_entries', 'format=duration',
                '-of', 'csv=p=0',
                str(file_path)
            ],
            capture_output=True,
            text=True,
            check=False
        )

        duration = 0.0

        if duration_result.returncode == 0 and duration_result.stdout.strip():
            try:
                duration = float(duration_result.stdout.strip())
            except ValueError:
                pass

        return QualityInfo(
            codec=codec,
            width=width,
            height=height,
            bitrate=bitrate,
            duration=duration,
            file_size=file_path.stat().st_size
        )

    except Exception:
        return None


def compare_quality(source: QualityInfo, existing: QualityInfo) -> tuple[bool, str]:
    """
    Compare quality between source and existing file.

    Returns:
        tuple: (prefer_existing, reason_string)
    """
    # Check resolution first - higher resolution wins
    if source.pixels > existing.pixels * 1.1:  # 10% tolerance
        return False, f"Source has higher resolution ({source.width}x{source.height} vs {existing.width}x{existing.height})"

    if existing.pixels > source.pixels * 1.1:
        return True, f"Existing has higher resolution ({existing.width}x{existing.height} vs {source.width}x{source.height})"

    # Same resolution - check codec preference (HEVC/H.265 > H.264)
    hevc_codecs = {'hevc', 'h265', 'libx265'}
    source_is_hevc = source.codec.lower() in hevc_codecs
    existing_is_hevc = existing.codec.lower() in hevc_codecs

    if source_is_hevc and not existing_is_hevc:
        return False, f"Source uses more efficient codec ({source.codec} vs {existing.codec})"

    if existing_is_hevc and not source_is_hevc:
        return True, f"Existing uses more efficient codec ({existing.codec} vs {source.codec})"

    # Same codec - compare bitrates
    # If one is significantly larger (2x+) with same quality indicators,
    # it's likely bloated from re-encoding
    size_ratio = existing.file_size / source.file_size if source.file_size > 0 else 1

    if size_ratio > 2.0:
        # Existing is more than 2x larger - extreme bloat
        # Prefer the smaller (source) if resolution is same
        return False, f"Existing is {size_ratio:.1f}x larger with same resolution - likely re-encoded bloat"

    if size_ratio < 0.5:
        # Source is more than 2x larger - extreme bloat
        return True, f"Source is {1/size_ratio:.1f}x larger with same resolution - likely re-encoded bloat"

    # Check for significant size difference (>20% but <2x)
    # This is unusual and worth noting - same duration/resolution but different sizes
    if size_ratio > 1.20:
        # Existing is 20-100% larger - significant difference, prefer smaller source
        return False, f"Existing is {size_ratio:.1f}x larger with same resolution - prefer smaller source"

    if size_ratio < 0.83:  # 1/1.20 ≈ 0.83
        # Source is 20-100% larger - significant difference, prefer smaller existing
        return True, f"Source is {1/size_ratio:.1f}x larger with same resolution - prefer smaller existing"

    # Similar sizes (within 20%), similar quality - prefer existing (already organized)
    return True, "Similar quality - keeping existing organized file"


# ============================================================================
# DATE EXTRACTION
# ============================================================================

def extract_date_from_filename(filename: str) -> Optional[datetime]:
    """
    Extract datetime from filename patterns like VID_YYYYMMDD_HHMMSS.

    Args:
        filename: The filename to parse

    Returns:
        datetime or None
    """
    # Pattern: optional prefix, then YYYYMMDD_HHMMSS
    match = re.search(
        r'(?:VID_|IMG_|PXL_)?(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})',
        filename
    )

    if match:
        year, month, day, hour, minute, second = match.groups()

        try:
            return datetime(
                int(year), int(month), int(day),
                int(hour), int(minute), int(second)
            )
        except ValueError:
            return None

    return None


def extract_date_pattern(filename: str) -> Optional[str]:
    """
    Extract the core date pattern (YYYYMMDD_HHMMSS) from a filename.

    This allows matching files with different prefixes/suffixes but same timestamp.

    Args:
        filename: The filename to parse

    Returns:
        Date pattern string or None
    """
    match = re.search(r'(\d{8}_\d{6})', filename)
    return match.group(1) if match else None


# ============================================================================
# DUPLICATE DETECTOR CLASS
# ============================================================================

class DuplicateDetector:
    """
    Smart duplicate detection using multiple signals.

    Attributes:
        photo_dir: Path to organized photos directory
        video_dir: Path to organized videos directory
        file_index: Index of existing files
        duration_tolerance: Acceptable duration difference in seconds
        size_tolerance: Acceptable size difference ratio for "similar" match
    """

    def __init__(
        self,
        photo_dir: Path,
        video_dir: Path,
        duration_tolerance: float = 1.0,
        size_tolerance: float = 0.20,
        source_hash_cache: Optional[Path] = None
    ):
        """
        Initialize the detector.

        Args:
            photo_dir: Path to organized photos
            video_dir: Path to organized videos
            duration_tolerance: Max duration difference (seconds) for match
            size_tolerance: Size difference ratio (0.20 = 20%) for "similar"
            source_hash_cache: Override the location of the source-hash cache.
                               Defaults to .source_hash_cache.json beside this
                               module. Injectable so tests need not write there.
        """
        self.photo_dir = Path(photo_dir)
        self.video_dir = Path(video_dir)
        self.duration_tolerance = duration_tolerance
        self.size_tolerance = size_tolerance

        # Duration cache file path and in-memory cache
        self._cache_file = Path(__file__).parent / ".duration_cache.json"
        self._duration_cache = self._load_duration_cache()
        self._cache_dirty = False

        # Hashes of INCOMING files, kept in a project-local file rather than in
        # the source tree — see _hash_source() for why the source tree is off
        # limits. This survives the usual dry-run-then-live-run sequence, which
        # would otherwise read every source byte twice (over 100 GB across the
        # pending import backlog, much of it over a network share).
        if source_hash_cache is None:
            source_hash_cache = Path(__file__).parent / SOURCE_HASH_CACHE_FILE

        self._source_hash_path = Path(source_hash_cache)
        self._source_hashes = self._load_source_hashes()
        self._source_hashes_dirty = False

        # Build file index
        self.file_index = build_file_index(
            photo_dir=self.photo_dir,
            video_dir=self.video_dir
        )

        # Build a secondary index by date pattern for faster lookups
        self._date_pattern_index = self._build_date_pattern_index()

        # Built on first use by _get_size_index(). Deferred because a run whose
        # files all match on date pattern never needs it, and building it costs a
        # stat() per archived file.
        self._size_index = None

    def _build_date_pattern_index(self) -> dict[str, list[Path]]:
        """Build index mapping date patterns to file paths."""
        index = {}

        for (base_name, ext, is_edited), paths in self.file_index.items():
            date_pattern = extract_date_pattern(base_name)

            if date_pattern:
                if date_pattern not in index:
                    index[date_pattern] = []

                index[date_pattern].extend(paths)

        return index

    def _get_size_index(self) -> dict[int, list[Path]]:
        """
        Lazily build an index mapping file size to archived paths.

        Size is the cheap pre-filter for content-hash matching: byte-identical
        files necessarily have identical length, so hashing can be confined to
        the handful of archived files that share the source's exact size. This
        avoids hashing the whole archive (over 150 GB) to answer one question.

        Returns:
            dict of {size_in_bytes: [Path, ...]}
        """
        if self._size_index is not None:
            return self._size_index

        index = {}

        for paths in self.file_index.values():
            for path in paths:
                try:
                    size = path.stat().st_size
                except OSError:
                    # Vanished or unreadable between indexing and now — skip
                    continue

                index.setdefault(size, []).append(path)

        self._size_index = index
        return index

    def _get_cached_md5(self, file_path: Path) -> Optional[str]:
        """
        Return the MD5 of an ARCHIVED file, reusing the analysis cache.

        The per-directory .analysis_cache.json files already hold MD5s computed
        by photo triage, so most archived files can be checked without re-reading
        their contents. A freshly computed hash is written back for next time.

        Cache entries are invalidated by mtime/size, so a file replaced since it
        was hashed is re-read rather than trusted.

        Only ever call this for files inside the organized archive. Source files
        awaiting import must use _hash_source() instead — see the note there.

        Args:
            file_path: Path to an archived file

        Returns:
            str: MD5 hex digest, or None if the file could not be read
        """
        cache = get_analysis_cache(file_path.parent)
        cached = cache.get_md5(file_path)

        if cached:
            return cached

        try:
            digest = compute_md5(file_path)
        except OSError:
            return None

        cache.set_md5(file_path, digest)
        return digest

    def _load_source_hashes(self) -> dict:
        """
        Load the source-hash cache, tolerating absence or corruption.

        Returns:
            dict of {absolute_path: {"mtime": float, "size": int, "md5": str}}
        """
        if not self._source_hash_path.exists():
            return {}

        try:
            with open(self._source_hash_path, 'r') as handle:
                loaded = json.load(handle)

        except (json.JSONDecodeError, OSError):
            # A truncated cache is not worth diagnosing — recompute instead
            return {}

        if not isinstance(loaded, dict):
            return {}

        return loaded

    def save_source_hashes(self):
        """
        Persist the source-hash cache, dropping entries for vanished files.

        Pruning matters because the normal outcome of an import is that the
        source file MOVES into the archive, leaving its entry permanently dead.
        Without pruning the file would grow without bound across imports.
        """
        if not self._source_hashes_dirty:
            return

        surviving = {
            key: entry for key, entry in self._source_hashes.items()
            if Path(key).exists()
        }

        try:
            with open(self._source_hash_path, 'w') as handle:
                json.dump(surviving, handle, indent=2)

            self._source_hashes = surviving
            self._source_hashes_dirty = False

        except OSError as error:
            print(f"  WARNING: Could not save source hash cache: {error}")

    def _hash_source(self, file_path: Path) -> Optional[str]:
        """
        Hash an incoming source file, caching outside the source tree.

        The source tree itself is never written to. It is frequently a mounted
        NAS share or a memory card — possibly read-only, and writing there would
        both violate --dry-run and put avoidable wear on the NAS drives. So the
        hash is recorded in a project-local file instead.

        Entries are validated by mtime and size, exactly like the analysis cache,
        so a source file edited or swapped between runs is re-read.

        Args:
            file_path: Path to the incoming file

        Returns:
            str: MD5 hex digest, or None if the file could not be read
        """
        try:
            stat_result = file_path.stat()
        except OSError:
            return None

        key = str(file_path.resolve())
        entry = self._source_hashes.get(key)

        if (
            isinstance(entry, dict)
            and entry.get('mtime') == stat_result.st_mtime
            and entry.get('size') == stat_result.st_size
            and entry.get('md5')
        ):
            return entry['md5']

        try:
            digest = compute_md5(file_path)
        except OSError:
            return None

        self._source_hashes[key] = {
            'mtime': stat_result.st_mtime,
            'size': stat_result.st_size,
            'md5': digest,
        }
        self._source_hashes_dirty = True

        return digest

    def _find_identical_by_content(
        self, source_path: Path, source_size: int
    ) -> Optional[Path]:
        """
        Find an archived file byte-identical to source_path.

        This is the fallback for files that name-based matching cannot see, which
        is 26% of the archive: anything without a YYYYMMDD_HHMMSS stamp in its
        filename. Organized Nikon files are named DSCN3089_S3500.JPG, so without
        this, re-ingesting the same SD card imports every photo a second time
        (see BUG-6).

        Content hashing is used rather than a date+size heuristic because a false
        positive here means silently discarding a genuinely new photo. Byte
        equality carries no such risk. Re-encoded or resized near-duplicates are
        deliberately out of scope — the perceptual-hash pass in photo_triage.py
        handles those during review.

        Args:
            source_path: Incoming file to check
            source_size: Size of source_path in bytes (already stat'ed by caller)

        Returns:
            Path of the matching archived file, or None
        """
        candidates = self._get_size_index().get(source_size, [])

        if not candidates:
            return None

        source_md5 = self._hash_source(source_path)

        if source_md5 is None:
            return None

        # Sorted for determinism: the same inputs must always name the same
        # match, so dry-run output matches the subsequent live run.
        for candidate_path in sorted(candidates):
            if candidate_path == source_path:
                continue

            if self._get_cached_md5(candidate_path) == source_md5:
                return candidate_path

        return None

    def _load_duration_cache(self) -> dict:
        """
        Load the duration cache from disk.

        Cache format: {file_path: {"duration": float, "mtime": float, "size": int}}
        The mtime and size are used to invalidate stale entries.
        """
        if self._cache_file.exists():
            try:
                with open(self._cache_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        return {}

    def save_caches(self):
        """
        Persist every cache this detector may have dirtied.

        Content-hash deduplication writes MD5s into the per-directory
        .analysis_cache.json files. Without a flush those hashes are recomputed on
        every run — including twice for the common --dry-run-then-live-run
        sequence, over an archive of more than 150 GB. Callers that previously
        only saved the duration cache should call this instead.
        """
        self.save_duration_cache()
        self.save_source_hashes()
        save_all_caches()

    def save_duration_cache(self):
        """
        Save the duration cache to disk if it was modified.

        Should be called after processing is complete to persist
        any newly computed durations.
        """
        if self._cache_dirty:
            try:
                with open(self._cache_file, 'w') as f:
                    json.dump(self._duration_cache, f)
            except IOError:
                pass

    def _get_duration(self, file_path: Path) -> Optional[float]:
        """
        Get video duration in seconds, using cache when available.

        Cache entries are invalidated if the file's mtime or size changes.
        """
        path_key = str(file_path)

        # Check cache first
        if path_key in self._duration_cache:
            cached = self._duration_cache[path_key]

            try:
                stat = file_path.stat()

                # Validate cache entry by mtime and size
                if cached.get('mtime') == stat.st_mtime and cached.get('size') == stat.st_size:
                    return cached.get('duration')

            except OSError:
                pass

        # Cache miss or stale - compute duration via ffprobe
        try:
            result = subprocess.run(
                [
                    'ffprobe', '-v', 'quiet',
                    '-show_entries', 'format=duration',
                    '-of', 'csv=p=0',
                    str(file_path)
                ],
                capture_output=True,
                text=True,
                check=False
            )

            if result.returncode == 0 and result.stdout.strip():
                duration = float(result.stdout.strip())

                # Cache the result
                try:
                    stat = file_path.stat()
                    self._duration_cache[path_key] = {
                        'duration': duration,
                        'mtime': stat.st_mtime,
                        'size': stat.st_size
                    }
                    self._cache_dirty = True
                except OSError:
                    pass

                return duration

            return None

        except Exception:
            return None

    def find_duplicate(self, source_path: Path) -> DuplicateResult:
        """
        Find if source file has a duplicate in the organized directories.

        Uses multi-signal matching:
        1. Date pattern from filename
        2. Duration comparison
        3. Size comparison
        4. Quality analysis for significant size differences

        Args:
            source_path: Path to the source file to check

        Returns:
            DuplicateResult with match details and recommendation
        """
        source_path = Path(source_path)

        if not source_path.exists():
            return DuplicateResult(
                is_duplicate=False,
                confidence=MatchConfidence.NONE,
                existing_path=None,
                prefer_existing=False,
                reason="Source file does not exist"
            )

        source_size = source_path.stat().st_size

        # Extract date pattern from source filename
        date_pattern = extract_date_pattern(source_path.name)

        # Files with no date in the filename (DSCN*, DSC_*, IMG_####, and every
        # scanned or hand-named image) cannot be matched by name at all. Fall
        # straight through to content hashing — see BUG-6.
        if not date_pattern:
            identical = self._find_identical_by_content(source_path, source_size)

            if identical is not None:
                return DuplicateResult(
                    is_duplicate=True,
                    confidence=MatchConfidence.EXACT,
                    existing_path=identical,
                    prefer_existing=True,
                    reason=f"Byte-identical to {identical.name} (no date in filename)"
                )

            return DuplicateResult(
                is_duplicate=False,
                confidence=MatchConfidence.NONE,
                existing_path=None,
                prefer_existing=False,
                reason="No date pattern in filename, and no identical content in archive"
            )

        # Find candidates with matching date pattern
        candidates = self._date_pattern_index.get(date_pattern, [])

        if not candidates:
            # The stamp is present but unknown to the archive. The file may still
            # be an already-imported photo that was renamed at some point, so
            # check content before declaring it new.
            identical = self._find_identical_by_content(source_path, source_size)

            if identical is not None:
                return DuplicateResult(
                    is_duplicate=True,
                    confidence=MatchConfidence.EXACT,
                    existing_path=identical,
                    prefer_existing=True,
                    reason=f"Byte-identical to renamed archive copy {identical.name}"
                )

            return DuplicateResult(
                is_duplicate=False,
                confidence=MatchConfidence.NONE,
                existing_path=None,
                prefer_existing=False,
                reason=f"No files match date pattern {date_pattern}"
            )

        # Get remaining source file info
        is_video = source_path.suffix.lower() in {e.lower() for e in VIDEO_EXTENSIONS}
        source_duration = self._get_duration(source_path) if is_video else None

        # Check each candidate
        for candidate_path in candidates:
            if not candidate_path.exists():
                continue

            candidate_size = candidate_path.stat().st_size

            # Check duration match for videos
            if is_video and source_duration is not None:
                candidate_duration = self._get_duration(candidate_path)

                if candidate_duration is None:
                    continue

                duration_diff = abs(source_duration - candidate_duration)

                if duration_diff > self.duration_tolerance:
                    # Duration doesn't match - not the same video
                    continue

                # Duration matches! Now check size
                size_ratio = max(source_size, candidate_size) / min(source_size, candidate_size)
                size_diff_pct = abs(source_size - candidate_size) / max(source_size, candidate_size)

                if size_diff_pct <= self.size_tolerance:
                    # Similar size - high confidence exact match
                    # Differentiate "exact same" (≤1%) from "similar" (>1% but ≤10%)
                    source_mb = source_size / 1_000_000
                    candidate_mb = candidate_size / 1_000_000

                    if size_diff_pct <= 0.01:
                        size_desc = "exact size"
                    else:
                        size_desc = f"similar size ({source_mb:.1f}MB vs {candidate_mb:.1f}MB)"

                    return DuplicateResult(
                        is_duplicate=True,
                        confidence=MatchConfidence.EXACT if size_diff_pct <= 0.01 else MatchConfidence.HIGH,
                        existing_path=candidate_path,
                        prefer_existing=True,
                        reason=f"Exact match: {source_duration:.1f}s, {size_desc}"
                    )
                else:
                    # Different sizes - need quality analysis
                    source_quality = get_video_quality(source_path)
                    existing_quality = get_video_quality(candidate_path)

                    if source_quality and existing_quality:
                        prefer_existing, quality_reason = compare_quality(
                            source_quality, existing_quality
                        )

                        return DuplicateResult(
                            is_duplicate=True,
                            confidence=MatchConfidence.MEDIUM,
                            existing_path=candidate_path,
                            prefer_existing=prefer_existing,
                            reason=f"Same content, different encoding: {quality_reason}",
                            source_quality=source_quality,
                            existing_quality=existing_quality
                        )
                    else:
                        # Couldn't analyze quality - be conservative, keep existing
                        return DuplicateResult(
                            is_duplicate=True,
                            confidence=MatchConfidence.MEDIUM,
                            existing_path=candidate_path,
                            prefer_existing=True,
                            reason="Same date/duration, different size - keeping existing (quality analysis failed)"
                        )

            else:
                # Not a video or no duration - fall back to size comparison only
                size_diff_pct = abs(source_size - candidate_size) / max(source_size, candidate_size)

                if size_diff_pct <= self.size_tolerance:
                    source_mb = source_size / 1_000_000
                    candidate_mb = candidate_size / 1_000_000

                    if size_diff_pct <= 0.01:
                        size_desc = "exact size"
                    else:
                        size_desc = f"similar size ({source_mb:.1f}MB vs {candidate_mb:.1f}MB)"

                    return DuplicateResult(
                        is_duplicate=True,
                        confidence=MatchConfidence.EXACT if size_diff_pct <= 0.01 else MatchConfidence.HIGH,
                        existing_path=candidate_path,
                        prefer_existing=True,
                        reason=f"Same date pattern, {size_desc}"
                    )

        # Date pattern matched but no duration/size match
        return DuplicateResult(
            is_duplicate=False,
            confidence=MatchConfidence.LOW,
            existing_path=candidates[0] if candidates else None,
            prefer_existing=False,
            reason=f"Date pattern matches {len(candidates)} file(s) but duration/size don't match"
        )


# ============================================================================
# CLI FOR TESTING
# ============================================================================

def main():
    """CLI for testing duplicate detection."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 duplicate_detector.py <file_path>")
        print("\nTests duplicate detection against organized directories.")
        sys.exit(1)

    source_path = Path(sys.argv[1])

    if not source_path.exists():
        print(f"Error: File not found: {source_path}")
        sys.exit(1)

    script_dir = Path(__file__).parent
    photo_dir = script_dir / "Organized_Photos"
    video_dir = script_dir / "Organized_Videos"

    print(f"\nAnalyzing: {source_path.name}")
    print("-" * 60)

    detector = DuplicateDetector(photo_dir, video_dir)
    result = detector.find_duplicate(source_path)

    print(f"Is duplicate:    {result.is_duplicate}")
    print(f"Confidence:      {result.confidence.name}")
    print(f"Prefer existing: {result.prefer_existing}")
    print(f"Reason:          {result.reason}")

    if result.existing_path:
        print(f"Existing file:   {result.existing_path.name}")

    if result.source_quality:
        sq = result.source_quality
        print(f"\nSource quality:")
        print(f"  Resolution: {sq.width}x{sq.height}")
        print(f"  Codec:      {sq.codec}")
        print(f"  Bitrate:    {sq.bitrate/1_000_000:.1f} Mbps")
        print(f"  Size:       {sq.file_size/1_000_000:.1f} MB")

    if result.existing_quality:
        eq = result.existing_quality
        print(f"\nExisting quality:")
        print(f"  Resolution: {eq.width}x{eq.height}")
        print(f"  Codec:      {eq.codec}")
        print(f"  Bitrate:    {eq.bitrate/1_000_000:.1f} Mbps")
        print(f"  Size:       {eq.file_size/1_000_000:.1f} MB")

    print("")


if __name__ == "__main__":
    main()
