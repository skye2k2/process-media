#!/usr/bin/env python3
"""
Video Quality Comparison Tool

Compares video quality between an original file and a re-encoded version using
objective metrics (SSIM, PSNR) and extracts comparison frames for visual inspection.

This tool is useful for:
- Determining if a re-encoding results in visible quality loss
- Comparing different CRF values to find the sweet spot for your content
- Validating that DVD/Blu-ray rips maintain acceptable quality
- A/B testing different encoding presets

Usage:
    # Compare two existing files
    python3 analyze_quality.py original.mov converted.mp4

    # Test a specific CRF value (creates a test encode)
    python3 analyze_quality.py original.mov --test-crf 20

    # Compare multiple CRF values
    python3 analyze_quality.py original.mov --test-crf 18 20 22 24

    # Limit analysis to first N seconds (faster for long videos)
    python3 analyze_quality.py original.mov converted.mp4 --duration 60

Quality Metric Interpretation:

    SSIM (Structural Similarity Index):
        1.0      = Identical
        >0.98    = Imperceptible difference
        0.95-0.98 = Nearly indistinguishable (target for archival)
        0.90-0.95 = Minor visible differences
        <0.90    = Noticeable quality loss

    PSNR (Peak Signal-to-Noise Ratio):
        >45 dB   = Excellent (mathematically near-lossless)
        40-45 dB = Very good (broadcast quality)
        35-40 dB = Good (acceptable for most content)
        30-35 dB = Fair (visible artifacts likely)
        <30 dB   = Poor (significant quality loss)

    Note: SSIM is generally more perceptually accurate than PSNR.
    A video with SSIM >0.95 and PSNR >38 dB is typically "visually lossless"
    for normal viewing conditions.

  For TV series, once you've found your ideal CRF with a test episode, that setting should work consistently across the entire series (assuming similar source quality, which is usually typical). Animated content typically compresses better than live-action, so you may find you can push CRF a bit higher (23-25) for cartoons while keeping CRF 20-22 for live-action dramas.

  The comparison frames are particularly useful when the metrics are borderline--sometimes a show with lots of grain or film artifacts will score lower on PSNR but still look fine to human eyes. When in doubt, open those PNGs side-by-side for manual review.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# ============================================================================
# CONFIGURATION
# ============================================================================

# Default encoding settings for test encodes
DEFAULT_CRF = 20
DEFAULT_PRESET = "slow"
DEFAULT_AUDIO_BITRATE = "192k"

# Sample duration for quick comparisons (seconds)
DEFAULT_SAMPLE_DURATION = 60

# Frame extraction times (as percentage of duration)
FRAME_EXTRACTION_POINTS = [0.1, 0.3, 0.5, 0.7, 0.9]


# ============================================================================
# VIDEO ANALYSIS
# ============================================================================

def get_video_info(file_path):
    """
    Get comprehensive video information using ffprobe.

    Args:
        file_path: Path to video file

    Returns:
        dict: Video metadata including codec, resolution, bitrate, duration
    """
    try:
        result = subprocess.run(
            [
                'ffprobe', '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                '-select_streams', 'v:0',
                str(file_path)
            ],
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)
        stream = data.get('streams', [{}])[0]
        fmt = data.get('format', {})

        return {
            'codec': stream.get('codec_name', 'unknown'),
            'width': int(stream.get('width', 0)),
            'height': int(stream.get('height', 0)),
            'duration': float(fmt.get('duration', 0)),
            'bitrate': int(fmt.get('bit_rate', 0)),
            'size': int(fmt.get('size', 0)),
            'fps': eval(stream.get('r_frame_rate', '0/1')) if '/' in stream.get('r_frame_rate', '') else 0,
        }

    except Exception as e:
        print(f"Error getting video info: {e}")
        return None


def create_sample_clip(input_path, output_path, duration, start_time=0):
    """
    Extract a sample clip from the video for faster analysis.

    Args:
        input_path: Source video path
        output_path: Output clip path
        duration: Duration in seconds
        start_time: Start time in seconds

    Returns:
        bool: Success
    """
    cmd = [
        'ffmpeg', '-y',
        '-ss', str(start_time),
        '-i', str(input_path),
        '-t', str(duration),
        '-c', 'copy',
        str(output_path)
    ]

    result = subprocess.run(cmd, capture_output=True, check=False)
    return result.returncode == 0


def encode_test_version(input_path, output_path, crf, preset=DEFAULT_PRESET):
    """
    Create a test H.265 encode with specified settings.

    Args:
        input_path: Source video path
        output_path: Output path
        crf: CRF value (lower = better quality)
        preset: x265 preset

    Returns:
        bool: Success
    """
    cmd = [
        'ffmpeg', '-y',
        '-i', str(input_path),
        '-c:v', 'libx265',
        '-crf', str(crf),
        '-preset', preset,
        '-tag:v', 'hvc1',
        '-c:a', 'aac',
        '-b:a', DEFAULT_AUDIO_BITRATE,
        '-movflags', '+faststart',
        str(output_path)
    ]

    print(f"  Encoding with CRF {crf}, preset {preset}...")
    result = subprocess.run(cmd, capture_output=True, check=False)
    return result.returncode == 0


def calculate_ssim(original_path, compared_path, fps=30):
    """
    Calculate SSIM between two videos.

    Args:
        original_path: Path to original video
        compared_path: Path to comparison video
        fps: Normalized frame rate for comparison

    Returns:
        dict: SSIM values for Y, U, V, and All channels
    """
    import re

    cmd = [
        'ffmpeg',
        '-i', str(original_path),
        '-i', str(compared_path),
        '-lavfi', f"[0:v]fps={fps}[v0];[1:v]fps={fps}[v1];[v0][v1]ssim",
        '-f', 'null', '-'
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)

    # Parse SSIM from stderr (ffmpeg outputs stats there)
    # Format: [Parsed_ssim_2 @ 0x...] SSIM Y:0.967112 (14.829573) U:0.965018 ... All:0.969542 (15.163048)
    output = result.stderr

    for line in output.split('\n'):
        if 'SSIM' in line and 'All:' in line:
            try:
                # Use regex to reliably extract Y and All values
                y_match = re.search(r'Y:(\d+\.\d+)', line)
                all_match = re.search(r'All:(\d+\.\d+)', line)

                ssim_y = float(y_match.group(1)) if y_match else None
                ssim_all = float(all_match.group(1)) if all_match else None

                return {
                    'all': ssim_all,
                    'y': ssim_y,
                    'raw_line': line.strip()
                }
            except (ValueError, AttributeError):
                pass

    return None


def calculate_psnr(original_path, compared_path, fps=30):
    """
    Calculate PSNR between two videos.

    Args:
        original_path: Path to original video
        compared_path: Path to comparison video
        fps: Normalized frame rate for comparison

    Returns:
        dict: PSNR values
    """
    cmd = [
        'ffmpeg',
        '-i', str(original_path),
        '-i', str(compared_path),
        '-lavfi', f"[0:v]fps={fps}[v0];[1:v]fps={fps}[v1];[v0][v1]psnr",
        '-f', 'null', '-'
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    output = result.stderr

    for line in output.split('\n'):
        if 'PSNR' in line and 'average:' in line:
            try:
                # Parse: PSNR y:39.655321 u:43.632549 v:46.817613 average:40.816429 min:27.646195 max:47.225387
                for i, p in enumerate(line.split()):
                    if p.startswith('average:'):
                        avg = float(p.split(':')[1])
                    if p.startswith('min:'):
                        min_val = float(p.split(':')[1])
                    if p.startswith('max:'):
                        max_val = float(p.split(':')[1])
                    if p.startswith('y:'):
                        y_val = float(p.split(':')[1])

                return {
                    'average': avg,
                    'min': min_val,
                    'max': max_val,
                    'y': y_val,
                    'raw_line': line.strip()
                }
            except (ValueError, IndexError, UnboundLocalError):
                pass

    return None


def extract_comparison_frames(original_path, compared_path, output_dir, duration):
    """
    Extract frames at multiple points for visual comparison.

    Args:
        original_path: Path to original video
        compared_path: Path to comparison video
        output_dir: Directory for output frames
        duration: Video duration in seconds

    Returns:
        list: Paths to extracted frame pairs
    """
    frames = []
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for i, pct in enumerate(FRAME_EXTRACTION_POINTS):
        timestamp = duration * pct
        orig_frame = output_dir / f"frame_{i+1:02d}_original.png"
        comp_frame = output_dir / f"frame_{i+1:02d}_converted.png"

        # Extract original frame
        subprocess.run(
            ['ffmpeg', '-y', '-ss', str(timestamp), '-i', str(original_path),
             '-frames:v', '1', str(orig_frame)],
            capture_output=True, check=False
        )

        # Extract comparison frame
        subprocess.run(
            ['ffmpeg', '-y', '-ss', str(timestamp), '-i', str(compared_path),
             '-frames:v', '1', str(comp_frame)],
            capture_output=True, check=False
        )

        if orig_frame.exists() and comp_frame.exists():
            frames.append({
                'timestamp': timestamp,
                'original': orig_frame,
                'converted': comp_frame
            })

    return frames


def interpret_ssim(ssim_value):
    """Return human-readable interpretation of SSIM value."""
    if ssim_value >= 0.98:
        return "Imperceptible difference"
    elif ssim_value >= 0.95:
        return "Nearly indistinguishable (excellent for archival)"
    elif ssim_value >= 0.90:
        return "Minor visible differences"
    elif ssim_value >= 0.85:
        return "Noticeable differences"
    else:
        return "Significant quality loss"


def interpret_psnr(psnr_value):
    """Return human-readable interpretation of PSNR value."""
    if psnr_value >= 45:
        return "Excellent (near-lossless)"
    elif psnr_value >= 40:
        return "Very good (broadcast quality)"
    elif psnr_value >= 35:
        return "Good (acceptable)"
    elif psnr_value >= 30:
        return "Fair (some artifacts)"
    else:
        return "Poor (significant loss)"


# ============================================================================
# MAIN ANALYSIS
# ============================================================================

def analyze_quality(original_path, compared_path, sample_duration=None, output_dir=None):
    """
    Perform full quality analysis between original and compared video.

    Args:
        original_path: Path to original video
        compared_path: Path to comparison video
        sample_duration: If set, only analyze first N seconds
        output_dir: Directory for output files (frames, report)

    Returns:
        dict: Analysis results
    """
    original_path = Path(original_path)
    compared_path = Path(compared_path)

    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix='quality_analysis_'))
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 70}")
    print("Video Quality Analysis")
    print('=' * 70)

    # Get video info
    print("\nGathering video information...")
    orig_info = get_video_info(original_path)
    comp_info = get_video_info(compared_path)

    if not orig_info or not comp_info:
        print("ERROR: Could not read video information")
        return None

    # Print file info
    print(f"\n  Original: {original_path.name}")
    print(f"    Codec: {orig_info['codec']}")
    print(f"    Resolution: {orig_info['width']}x{orig_info['height']}")
    print(f"    Duration: {orig_info['duration']:.1f}s")
    print(f"    Bitrate: {orig_info['bitrate'] / 1000:.1f} kbps")
    print(f"    Size: {orig_info['size'] / 1024 / 1024:.1f} MB")

    print(f"\n  Compared: {compared_path.name}")
    print(f"    Codec: {comp_info['codec']}")
    print(f"    Resolution: {comp_info['width']}x{comp_info['height']}")
    print(f"    Duration: {comp_info['duration']:.1f}s")
    print(f"    Bitrate: {comp_info['bitrate'] / 1000:.1f} kbps")
    print(f"    Size: {comp_info['size'] / 1024 / 1024:.1f} MB")

    # Calculate compression ratio
    if orig_info['size'] > 0:
        compression = (1 - comp_info['size'] / orig_info['size']) * 100
        print(f"\n  Compression: {compression:.1f}% size reduction")

    # Prepare sample clips if needed
    analysis_duration = min(sample_duration or orig_info['duration'], orig_info['duration'])

    if sample_duration and sample_duration < orig_info['duration']:
        print(f"\n  Analyzing first {sample_duration} seconds...")
        orig_sample = output_dir / "sample_original.mov"
        comp_sample = output_dir / "sample_compared.mp4"

        create_sample_clip(original_path, orig_sample, sample_duration)
        create_sample_clip(compared_path, comp_sample, sample_duration)

        analysis_orig = orig_sample
        analysis_comp = comp_sample
    else:
        analysis_orig = original_path
        analysis_comp = compared_path

    # Calculate SSIM
    print("\n  Calculating SSIM (structural similarity)...")
    ssim = calculate_ssim(analysis_orig, analysis_comp)

    # Calculate PSNR
    print("  Calculating PSNR (peak signal-to-noise ratio)...")
    psnr = calculate_psnr(analysis_orig, analysis_comp)

    # Extract comparison frames
    print("  Extracting comparison frames...")
    frames = extract_comparison_frames(
        analysis_orig, analysis_comp,
        output_dir / "frames",
        analysis_duration
    )

    # Print results
    print(f"\n{'=' * 70}")
    print("Quality Metrics")
    print('=' * 70)

    if ssim:
        print(f"\n  SSIM (All): {ssim['all']:.6f}")
        print(f"    → {interpret_ssim(ssim['all'])}")

    if psnr:
        print(f"\n  PSNR (Average): {psnr['average']:.2f} dB")
        print(f"    → {interpret_psnr(psnr['average'])}")
        print(f"    Min: {psnr['min']:.2f} dB, Max: {psnr['max']:.2f} dB")

    # Overall verdict
    print(f"\n{'=' * 70}")
    print("Verdict")
    print('=' * 70)

    if ssim and psnr:
        if ssim['all'] >= 0.95 and psnr['average'] >= 38:
            print("\n  ✓ VISUALLY LOSSLESS - Safe to use for archival")
        elif ssim['all'] >= 0.90 and psnr['average'] >= 35:
            print("\n  ⚠ GOOD QUALITY - Minor differences, acceptable for most uses")
        else:
            print("\n  ✗ NOTICEABLE LOSS - Consider higher quality settings")

    # Frame comparison info
    if frames:
        print(f"\n  Comparison frames saved to: {output_dir / 'frames'}")
        print(f"  Open with: open \"{output_dir / 'frames'}\"")

    # Save report
    report_path = output_dir / "quality_report.txt"
    with open(report_path, 'w') as f:
        f.write(f"Video Quality Analysis Report\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n")
        f.write(f"{'=' * 50}\n\n")
        f.write(f"Original: {original_path}\n")
        f.write(f"  Codec: {orig_info['codec']}, {orig_info['width']}x{orig_info['height']}\n")
        f.write(f"  Bitrate: {orig_info['bitrate'] / 1000:.1f} kbps\n")
        f.write(f"  Size: {orig_info['size'] / 1024 / 1024:.1f} MB\n\n")
        f.write(f"Compared: {compared_path}\n")
        f.write(f"  Codec: {comp_info['codec']}, {comp_info['width']}x{comp_info['height']}\n")
        f.write(f"  Bitrate: {comp_info['bitrate'] / 1000:.1f} kbps\n")
        f.write(f"  Size: {comp_info['size'] / 1024 / 1024:.1f} MB\n\n")
        f.write(f"Compression: {compression:.1f}% size reduction\n\n")
        f.write(f"Quality Metrics:\n")
        if ssim:
            f.write(f"  SSIM: {ssim['all']:.6f} - {interpret_ssim(ssim['all'])}\n")
        if psnr:
            f.write(f"  PSNR: {psnr['average']:.2f} dB - {interpret_psnr(psnr['average'])}\n")
            f.write(f"        Min: {psnr['min']:.2f} dB, Max: {psnr['max']:.2f} dB\n")

    print(f"\n  Full report saved to: {report_path}")

    return {
        'original': orig_info,
        'compared': comp_info,
        'ssim': ssim,
        'psnr': psnr,
        'frames': frames,
        'output_dir': output_dir
    }


def compare_crf_values(original_path, crf_values, sample_duration=60, output_dir=None):
    """
    Compare multiple CRF values to find the optimal setting.

    Args:
        original_path: Path to original video
        crf_values: List of CRF values to test
        sample_duration: Duration to test (seconds)
        output_dir: Output directory for test files and results

    Returns:
        list: Results for each CRF value
    """
    original_path = Path(original_path)

    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix='crf_comparison_'))
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 70}")
    print(f"CRF Comparison Analysis")
    print('=' * 70)
    print(f"\nTesting CRF values: {crf_values}")
    print(f"Sample duration: {sample_duration} seconds")

    # Get original info
    orig_info = get_video_info(original_path)

    if not orig_info:
        print("ERROR: Could not read original video")
        return None

    # Create sample of original
    print("\nPreparing sample clip...")
    sample_path = output_dir / "original_sample.mov"
    create_sample_clip(original_path, sample_path, sample_duration)

    sample_info = get_video_info(sample_path)
    orig_sample_size = sample_info['size'] if sample_info else 0

    results = []

    for crf in crf_values:
        print(f"\n{'-' * 50}")
        print(f"Testing CRF {crf}")
        print('-' * 50)

        encoded_path = output_dir / f"test_crf{crf}.mp4"

        # Encode
        if not encode_test_version(sample_path, encoded_path, crf):
            print(f"  ERROR: Encoding failed for CRF {crf}")
            continue

        # Get encoded info
        enc_info = get_video_info(encoded_path)

        if not enc_info:
            continue

        # Calculate metrics
        print("  Calculating quality metrics...")
        ssim = calculate_ssim(sample_path, encoded_path)
        psnr = calculate_psnr(sample_path, encoded_path)

        compression = (1 - enc_info['size'] / orig_sample_size) * 100 if orig_sample_size > 0 else 0

        result = {
            'crf': crf,
            'size': enc_info['size'],
            'bitrate': enc_info['bitrate'],
            'compression': compression,
            'ssim': ssim['all'] if ssim else None,
            'psnr': psnr['average'] if psnr else None,
            'path': encoded_path
        }
        results.append(result)

        print(f"  Size: {enc_info['size'] / 1024 / 1024:.1f} MB ({compression:.1f}% reduction)")
        print(f"  Bitrate: {enc_info['bitrate'] / 1000:.1f} kbps")

        if ssim:
            print(f"  SSIM: {ssim['all']:.6f} - {interpret_ssim(ssim['all'])}")

        if psnr:
            print(f"  PSNR: {psnr['average']:.2f} dB - {interpret_psnr(psnr['average'])}")

    # Print comparison table
    print(f"\n{'=' * 70}")
    print("CRF Comparison Summary")
    print('=' * 70)

    print(f"\n  {'CRF':>4} | {'Size':>8} | {'Bitrate':>10} | {'Compress':>8} | {'SSIM':>8} | {'PSNR':>8} | Quality")
    print(f"  {'-' * 4}-+-{'-' * 8}-+-{'-' * 10}-+-{'-' * 8}-+-{'-' * 8}-+-{'-' * 8}-+--------")

    for r in results:
        ssim_str = f"{r['ssim']:.4f}" if r['ssim'] else "N/A"
        psnr_str = f"{r['psnr']:.1f} dB" if r['psnr'] else "N/A"
        quality = interpret_ssim(r['ssim'])[:20] if r['ssim'] else "N/A"

        print(f"  {r['crf']:>4} | {r['size']/1024/1024:>6.1f}MB | {r['bitrate']/1000:>8.0f}kb | {r['compression']:>6.1f}% | {ssim_str:>8} | {psnr_str:>8} | {quality}")

    # Recommendation
    print(f"\n{'=' * 70}")
    print("Recommendation")
    print('=' * 70)

    # Find best CRF that maintains SSIM >= 0.95
    good_results = [r for r in results if r['ssim'] and r['ssim'] >= 0.95]

    if good_results:
        # Pick highest CRF (smallest file) that's still good quality
        best = max(good_results, key=lambda r: r['crf'])
        print(f"\n  Recommended CRF: {best['crf']}")
        print(f"    Provides {best['compression']:.1f}% compression while maintaining SSIM {best['ssim']:.4f}")
    else:
        print("\n  No CRF value tested achieved SSIM >= 0.95")
        print("  Consider testing lower CRF values (18, 16, etc.)")

    print(f"\n  Test files saved to: {output_dir}")

    return results


# ============================================================================
# CLI
# ============================================================================

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Compare video quality between original and re-encoded versions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Compare two existing files
  python3 analyze_quality.py original.mov converted.mp4

  # Test specific CRF values
  python3 analyze_quality.py original.mov --test-crf 18 20 22

  # Quick analysis (first 60 seconds only)
  python3 analyze_quality.py original.mov converted.mp4 --duration 60

Quality Reference:
  SSIM 0.95+ and PSNR 38+ dB = Visually lossless for most content
  SSIM 0.98+ = Imperceptible difference even on close inspection
        """
    )

    parser.add_argument(
        'original',
        help="Path to original video file"
    )
    parser.add_argument(
        'compared',
        nargs='?',
        help="Path to comparison video file (optional if using --test-crf)"
    )
    parser.add_argument(
        '--test-crf',
        nargs='+',
        type=int,
        metavar='CRF',
        help="Test one or more CRF values (creates test encodes)"
    )
    parser.add_argument(
        '--duration',
        type=int,
        default=None,
        metavar='SECONDS',
        help="Only analyze first N seconds (faster for long videos)"
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        default=None,
        help="Directory for output files (default: temp directory)"
    )

    args = parser.parse_args()

    # Validate inputs
    if not Path(args.original).exists():
        print(f"ERROR: Original file not found: {args.original}")
        sys.exit(1)

    if args.test_crf:
        # CRF comparison mode
        compare_crf_values(
            args.original,
            args.test_crf,
            sample_duration=args.duration or 60,
            output_dir=args.output_dir
        )
    elif args.compared:
        # Direct comparison mode
        if not Path(args.compared).exists():
            print(f"ERROR: Comparison file not found: {args.compared}")
            sys.exit(1)

        analyze_quality(
            args.original,
            args.compared,
            sample_duration=args.duration,
            output_dir=args.output_dir
        )
    else:
        print("ERROR: Either provide a comparison file or use --test-crf")
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
