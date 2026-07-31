#!/usr/bin/env python3
"""
Photo Review Workflow

Orchestrates the full photo review pipeline for already-organized photos:
  1. Blur calculation + duplicate detection  (auto-triage --dry-run)
  2. Review report generation                (review-issues)
  3. Browse-all report generation            (browse)

This is a convenience wrapper around photo_triage.py subcommands. Each step
can also be run individually — this script just chains them together so you
don't have to remember the incantation.

Usage:
    python3 workflow_review.py                            # Default: Organized_Photos/
    python3 workflow_review.py Organized_Photos/2024/     # Specific year
    python3 workflow_review.py --open                     # Open reports in browser
    python3 workflow_review.py --no-duplicates            # Skip duplicate detection
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DEFAULT_PHOTO_DIR = SCRIPT_DIR / "Organized_Photos"


def format_elapsed(seconds):
    """Format seconds into a concise human-readable string."""
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)

    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"

    if minutes > 0:
        return f"{minutes}m {secs}s"

    return f"{secs}s"


def run_step(step_number, description, cmd):
    """
    Run a pipeline step as a subprocess.

    Prints a banner, executes the command, and reports elapsed time.

    Args:
        step_number: Display step number (1-indexed)
        description: Human-readable description of the step
        cmd: List of command arguments for subprocess.run

    Returns:
        bool: True if the step completed successfully
    """
    print()
    print('=' * 70)
    print(f"  Step {step_number}: {description}")
    print('=' * 70)
    print()

    step_start = time.time()

    try:
        result = subprocess.run(cmd, check=False)
        elapsed = time.time() - step_start
        success = result.returncode == 0

        if success:
            print(f"\n  Step {step_number} completed in {format_elapsed(elapsed)}")
        else:
            print(f"\n  Step {step_number} FAILED (exit code {result.returncode}) after {format_elapsed(elapsed)}")

        return success

    except KeyboardInterrupt:
        elapsed = time.time() - step_start
        print(f"\n  Step {step_number} interrupted by user after {format_elapsed(elapsed)}")
        return False


def main():
    """Run the full photo review pipeline."""
    parser = argparse.ArgumentParser(
        description="Run the full photo review pipeline: blur + duplicates + HTML reports",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Pipeline steps:
  1. Calculate blur scores and detect duplicates (auto-triage --dry-run)
     This populates the .analysis_cache.json files without moving anything.
  2. Generate the review-issues HTML report (blurry + duplicate photos)
  3. Generate the browse-all HTML report (every photo, by directory)

Examples:
    %(prog)s                              # Review all of Organized_Photos/
    %(prog)s Organized_Photos/2024/ --open  # Review one year, open in browser
    %(prog)s --no-duplicates --open       # Skip duplicate detection (faster)
        """
    )

    parser.add_argument(
        'directory',
        nargs='?',
        default=None,
        help="Directory to review (default: Organized_Photos/)"
    )

    parser.add_argument(
        '--open',
        action='store_true',
        help="Open HTML reports in browser after generation"
    )

    parser.add_argument(
        '--no-duplicates',
        action='store_true',
        help="Skip duplicate detection (faster, but review report won't show dupes)"
    )

    parser.add_argument(
        '--skip-cache',
        action='store_true',
        help="Skip the cache-warming step (use when blur cache is already populated)"
    )

    args = parser.parse_args()

    # Resolve target directory
    target_dir = str(Path(args.directory)) if args.directory else str(DEFAULT_PHOTO_DIR)

    if not Path(target_dir).exists():
        print(f"ERROR: Directory not found: {target_dir}")
        sys.exit(1)

    triage_script = str(SCRIPT_DIR / 'photo_triage.py')
    pipeline_start = time.time()
    step_count = 0
    failures = 0

    # Header
    print()
    print('=' * 70)
    print("  Photo Review Pipeline")
    print('=' * 70)
    print(f"  Target: {target_dir}")
    print(f"  Duplicates: {'skip' if args.no_duplicates else 'detect'}")
    print(f"  Open reports: {'yes' if args.open else 'no'}")

    # ---- Step 1: Warm blur cache + detect duplicates ----
    if not args.skip_cache:
        step_count += 1
        cache_cmd = [
            sys.executable, triage_script,
            'auto-triage', target_dir, '--dry-run'
        ]

        if not run_step(step_count, "Calculate blur scores and detect duplicates", cache_cmd):
            failures += 1
            # Non-fatal — reports can still use whatever cache exists

    # ---- Step 2: Review-issues report ----
    step_count += 1
    review_cmd = [
        sys.executable, triage_script,
        'review-issues', target_dir
    ]

    if args.no_duplicates:
        review_cmd.append('--no-duplicates')

    if args.open:
        review_cmd.append('--open')

    if not run_step(step_count, "Generate review-issues HTML report", review_cmd):
        failures += 1

    # ---- Step 3: Browse-all report ----
    step_count += 1
    browse_cmd = [
        sys.executable, triage_script,
        'browse', target_dir
    ]

    if args.open:
        browse_cmd.append('--open')

    if not run_step(step_count, "Generate browse-all HTML report", browse_cmd):
        failures += 1

    # ---- Summary ----
    total_elapsed = time.time() - pipeline_start

    print()
    print('=' * 70)
    print("  Pipeline Complete")
    print('=' * 70)
    print(f"  Total time: {format_elapsed(total_elapsed)}")

    if failures > 0:
        print(f"  Warnings: {failures} step(s) had issues")

    print()
    print("  Next steps:")
    print("    1. Review the HTML reports in your browser")
    print("    2. Use KEEP/REMOVE buttons, then export the removal script")
    print("    3. Optionally run:  python3 photo_triage.py auto-triage --symlinks")
    print()


if __name__ == '__main__':
    main()
