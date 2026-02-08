#!/usr/bin/env python3
"""
Camcorder Video Conversion Workflow

Orchestrates the video conversion process for older codecs (H.264, MPEG-2, AVCHD)
to H.265/HEVC. This workflow script handles:
- Command-line argument parsing
- User prompts and confirmations
- Timing and progress tracking
- Summary statistics

The actual conversion logic lives in camcorder_convert.py.

Usage:
    python3 workflow_camcorder.py [input_dir]
    python3 workflow_camcorder.py --dry-run [input_dir]
    python3 workflow_camcorder.py --keep-originals [input_dir]

Default input directory: TO_PROCESS/
"""

import argparse
import sys
import time
from pathlib import Path

from build_file_index import build_file_index
from camcorder_convert import (
    DEFAULT_INPUT_DIR,
    FFMPEG_CRF,
    FFMPEG_PRESET,
    NOISE_THRESHOLD_BPP,
    VIDEO_OUTPUT_DIR,
    process_file,
    scan_video_files,
)
from conversion_index import (
    load_index,
    print_index_summary,
    save_index,
)


def print_header(dry_run=False):
    """Print the workflow header banner."""
    print("\n" + "=" * 70)
    print("Video Codec Conversion (H.264/MPEG-2 → H.265)")
    print("=" * 70)

    if dry_run:
        print("\n*** DRY RUN MODE - No changes will be made ***\n")


def print_summary(converted, skipped_codec, skipped_indexed, skipped_duplicate,
                  failed, elapsed, original_bytes, converted_bytes, dry_run,
                  encoder_stats=None):
    """
    Print final summary statistics.

    Args:
        converted: Count of successfully converted files
        skipped_codec: Count skipped due to already-efficient codec
        skipped_indexed: Count skipped due to persistent index match
        skipped_duplicate: Count skipped due to filename duplicate
        failed: Count of failed conversions
        elapsed: Total elapsed time in seconds
        original_bytes: Total original file sizes
        converted_bytes: Total converted file sizes
        dry_run: Whether this was a dry run
        encoder_stats: Dict with encoder selection statistics
    """
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)

    print(f"\n  Converted:          {converted}")
    print(f"  Skipped (codec):    {skipped_codec}")
    print(f"  Skipped (indexed):  {skipped_indexed}")
    print(f"  Skipped (exists):   {skipped_duplicate}")
    print(f"  Failed:             {failed}")

    # Encoder breakdown with time estimates (only if we have stats)
    if encoder_stats and (encoder_stats['libx265_count'] > 0 or encoder_stats['videotoolbox_count'] > 0):
        print("\n" + "-" * 40)
        print("  Encoder Selection:")
        print(f"    libx265 (noisy):      {encoder_stats['libx265_count']} files, {encoder_stats['libx265_duration']:.0f}s video")
        print(f"    VideoToolbox (clean): {encoder_stats['videotoolbox_count']} files, {encoder_stats['videotoolbox_duration']:.0f}s video")

        # Time estimates based on benchmarks:
        # libx265 CRF 26: ~1.6x realtime (57s to encode 35s video)
        # VideoToolbox: ~0.12x realtime (5.5s to encode 46s video)
        libx265_time = encoder_stats['libx265_duration'] * 1.6
        videotoolbox_time = encoder_stats['videotoolbox_duration'] * 0.12

        total_est_seconds = libx265_time + videotoolbox_time
        hours = int(total_est_seconds // 3600)
        minutes = int((total_est_seconds % 3600) // 60)

        print("\n  Estimated conversion time:")
        print(f"    libx265 portion:      {libx265_time / 60:.0f} min")
        print(f"    VideoToolbox portion: {videotoolbox_time / 60:.0f} min")
        print(f"    Total:                {hours}h {minutes}m")

        # BPP distribution
        if encoder_stats['bpp_values']:
            bpp_sorted = sorted(encoder_stats['bpp_values'])
            bpp_min = bpp_sorted[0]
            bpp_max = bpp_sorted[-1]
            bpp_median = bpp_sorted[len(bpp_sorted) // 2]
            print(f"\n  Complexity (bits-per-pixel):")
            print(f"    Min: {bpp_min:.3f}, Median: {bpp_median:.3f}, Max: {bpp_max:.3f}")
            print(f"    Threshold: {NOISE_THRESHOLD_BPP} (above = noisy → libx265)")

    # Size summary - show for both dry run (original only) and actual run (with savings)
    if original_bytes > 0:
        orig_mb = original_bytes / (1024 * 1024)
        orig_gb = orig_mb / 1024

        if dry_run:
            print(f"\n  Total to process:   {orig_gb:.2f} GB ({orig_mb:.0f} MB)")
        else:
            conv_mb = converted_bytes / (1024 * 1024)
            conv_gb = conv_mb / 1024
            savings_mb = orig_mb - conv_mb
            savings_gb = savings_mb / 1024
            pct = (savings_mb / orig_mb) * 100 if orig_mb > 0 else 0

            print(f"\n  Original:   {orig_gb:.2f} GB ({orig_mb:.0f} MB)")
            print(f"  Converted:  {conv_gb:.2f} GB ({conv_mb:.0f} MB)")
            print(f"  Savings:    {savings_gb:.2f} GB ({pct:.1f}%)")

    # Timing - label changes based on dry run vs actual
    time_label = "Analysis time" if dry_run else "Total time"
    if elapsed >= 3600:
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        print(f"\n  {time_label}:       {hours}h {minutes}m")
    elif elapsed >= 60:
        print(f"\n  {time_label}:       {elapsed / 60:.1f} minutes")
    else:
        print(f"\n  {time_label}:       {elapsed:.1f} seconds")

    print("")


def confirm_deletion():
    """
    Prompt user to confirm original file deletion.

    Returns:
        bool: True if user confirms, False to cancel
    """
    print("\n⚠️  Original files will be DELETED after successful conversion")
    confirm = input("Continue? (Y/n): ").strip().upper()
    return confirm in ('Y', 'YES', '')


def run_conversion_workflow(input_dir, dry_run=False, keep_originals=False,
                             crf=FFMPEG_CRF, preset=FFMPEG_PRESET, force_software=False):
    """
    Execute the full video conversion workflow.

    Args:
        input_dir: Path to directory containing video files
        dry_run: If True, don't make any changes
        keep_originals: If True, don't delete source files
        crf: H.265 CRF value (lower = better quality)
        preset: x265 encoding preset
        force_software: If True, always use libx265 instead of auto-selecting VideoToolbox

    Returns:
        int: Exit code (0 = success, 1 = failures occurred)
    """
    print_header(dry_run)

    # Validate input directory
    if not input_dir.exists():
        print(f"\nERROR: Input directory not found: {input_dir}")
        print("\nCreate the directory and add your video files, or specify a different path.")
        return 1

    # Scan for video files
    files = scan_video_files(input_dir)

    if not files:
        print(f"\nNo video files found in: {input_dir}")
        return 0

    print(f"\nFound {len(files)} video file(s) to analyze")
    print(f"Output directory: {VIDEO_OUTPUT_DIR}")
    if force_software:
        print(f"Encoding: H.265 (libx265 forced), CRF {crf}, preset {preset}")
    else:
        print(f"Encoding: H.265 (auto-select: VideoToolbox for clean, libx265 CRF {crf} for noisy)")
    print("Files already in H.265/HEVC/AV1/VP9 will be skipped")

    # Confirm deletion if needed
    if not keep_originals and not dry_run:
        if not confirm_deletion():
            print("\nCancelled by user")
            return 0

    # Build file index for duplicate detection
    print("\n" + "-" * 70)
    file_index = build_file_index(video_dir=VIDEO_OUTPUT_DIR)

    # Load persistent conversion index for content-based deduplication
    conversion_index = load_index()
    print_index_summary(conversion_index)

    # Process files
    print("\n" + "-" * 70)
    print("Processing files...")

    start_time = time.time()
    converted_count = 0
    skipped_codec_count = 0
    skipped_indexed_count = 0
    skipped_duplicate_count = 0
    fail_count = 0
    total_original_size = 0
    total_converted_size = 0

    # Encoder statistics tracking
    encoder_stats = {
        'libx265_count': 0,
        'libx265_duration': 0,
        'videotoolbox_count': 0,
        'videotoolbox_duration': 0,
        'bpp_values': []
    }

    for file_path in files:
        original_size = file_path.stat().st_size

        result, output_path, _, encoder_info = process_file(
            file_path, file_index, conversion_index, dry_run, keep_originals,
            crf=crf, preset=preset, force_software=force_software
        )

        # Track encoder selection stats (for files that will be converted)
        if encoder_info:
            if encoder_info['encoder'] == 'libx265':
                encoder_stats['libx265_count'] += 1
                encoder_stats['libx265_duration'] += encoder_info['duration']
            else:
                encoder_stats['videotoolbox_count'] += 1
                encoder_stats['videotoolbox_duration'] += encoder_info['duration']

            if encoder_info['bpp']:
                encoder_stats['bpp_values'].append(encoder_info['bpp'])

        if result == 'converted':
            converted_count += 1
            total_original_size += original_size

            if output_path and output_path.exists():
                total_converted_size += output_path.stat().st_size

            # Save index after each successful conversion (crash-safe)
            if not dry_run:
                save_index(conversion_index)

        elif result == 'skipped_codec':
            skipped_codec_count += 1

        elif result == 'skipped_indexed':
            skipped_indexed_count += 1

        elif result == 'skipped_duplicate':
            skipped_duplicate_count += 1

        else:  # 'failed'
            fail_count += 1

    # Print summary
    elapsed = time.time() - start_time
    print_summary(
        converted_count, skipped_codec_count, skipped_indexed_count,
        skipped_duplicate_count, fail_count, elapsed,
        total_original_size, total_converted_size, dry_run,
        encoder_stats=encoder_stats
    )

    return 0 if fail_count == 0 else 1


def parse_args():
    """
    Parse command-line arguments.

    Returns:
        argparse.Namespace: Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="Convert older video codecs (H.264, MPEG-2, etc.) to H.265 and organize by date",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                      # Process files from TO_PROCESS/
  %(prog)s /path/to/videos      # Process files from custom directory
  %(prog)s --dry-run            # Preview without making changes
  %(prog)s --keep-originals     # Keep source files after conversion
        """
    )

    parser.add_argument(
        'input_dir',
        nargs='?',
        default=str(DEFAULT_INPUT_DIR),
        help=f"Directory containing video files (default: {DEFAULT_INPUT_DIR})"
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help="Show what would be done without making changes"
    )

    parser.add_argument(
        '--keep-originals',
        action='store_true',
        help="Keep original files after successful conversion"
    )

    parser.add_argument(
        '--crf',
        type=int,
        default=FFMPEG_CRF,
        help=f"H.265 CRF value (lower=better quality, default: {FFMPEG_CRF})"
    )

    parser.add_argument(
        '--preset',
        choices=['ultrafast', 'superfast', 'veryfast', 'faster', 'fast',
                 'medium', 'slow', 'slower', 'veryslow'],
        default=FFMPEG_PRESET,
        help=f"x265 encoding preset (default: {FFMPEG_PRESET})"
    )

    parser.add_argument(
        '--force-software',
        action='store_true',
        help="Force libx265 software encoding for all files (ignore noise detection)"
    )

    return parser.parse_args()


def main():
    """Main entry point for the camcorder workflow."""
    args = parse_args()
    input_dir = Path(args.input_dir)

    return run_conversion_workflow(
        input_dir,
        dry_run=args.dry_run,
        keep_originals=args.keep_originals,
        crf=args.crf,
        preset=args.preset,
        force_software=args.force_software
    )


if __name__ == "__main__":
    sys.exit(main())
