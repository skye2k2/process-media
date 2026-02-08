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

from build_file_index import build_file_index
from media_utils import VIDEO_EXTENSIONS


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
        size_tolerance: float = 0.20
    ):
        """
        Initialize the detector.

        Args:
            photo_dir: Path to organized photos
            video_dir: Path to organized videos
            duration_tolerance: Max duration difference (seconds) for match
            size_tolerance: Size difference ratio (0.20 = 20%) for "similar"
        """
        self.photo_dir = Path(photo_dir)
        self.video_dir = Path(video_dir)
        self.duration_tolerance = duration_tolerance
        self.size_tolerance = size_tolerance

        # Duration cache file path and in-memory cache
        self._cache_file = Path(__file__).parent / ".duration_cache.json"
        self._duration_cache = self._load_duration_cache()
        self._cache_dirty = False

        # Build file index
        self.file_index = build_file_index(
            photo_dir=self.photo_dir,
            video_dir=self.video_dir
        )

        # Build a secondary index by date pattern for faster lookups
        self._date_pattern_index = self._build_date_pattern_index()

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

        # Extract date pattern from source filename
        date_pattern = extract_date_pattern(source_path.name)

        if not date_pattern:
            return DuplicateResult(
                is_duplicate=False,
                confidence=MatchConfidence.NONE,
                existing_path=None,
                prefer_existing=False,
                reason="No date pattern in filename"
            )

        # Find candidates with matching date pattern
        candidates = self._date_pattern_index.get(date_pattern, [])

        if not candidates:
            return DuplicateResult(
                is_duplicate=False,
                confidence=MatchConfidence.NONE,
                existing_path=None,
                prefer_existing=False,
                reason=f"No files match date pattern {date_pattern}"
            )

        # Get source file info
        source_size = source_path.stat().st_size
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
