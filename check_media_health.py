#!/usr/bin/env python3
"""
Media Health Check — find files that are damaged, not merely misplaced.

Every other tool here answers "where does this belong" or "is this a duplicate".
This one answers "is this file actually intact", which nothing was checking. A
truncated JPEG was found in the PhotoSync archive by accident: it decoded far
enough to report its dimensions and pass every existing check, but the final 17
bytes including the End-of-Image marker were missing.

Why that happens: a sync app or copy interrupted mid-write leaves a short file.
The filesystem records whatever arrived. Nothing detects it later, because JPEG has
no length field — a decoder simply runs out of data.

Why it matters more for a source tree than the archive: an interrupted upload years
ago is invisible until you try to view the photo, and if the damaged copy is the one
imported, the intact original may already be gone.

Detection method per type:
    images  full decode, not just a header read. A header read reports dimensions
            happily on a file missing most of its data.
    videos  ffprobe, which reports errors on truncated containers
    other   size only; arbitrary formats cannot be validated generically

Read-only. Never moves, deletes, or repairs anything.

Usage:
    python3 check_media_health.py /Volumes/photosync/Photo\\ Uploads
    python3 check_media_health.py Organized_Photos --output damaged.json
    python3 check_media_health.py /some/tree --workers 6
"""

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image, ImageFile

from media_utils import PHOTO_EXTENSIONS, VIDEO_EXTENSIONS

# Refuse PIL's default tolerance. Silently accepting short files is precisely the
# behaviour that let a damaged photo pass unnoticed.
ImageFile.LOAD_TRUNCATED_IMAGES = False

# I/O bound rather than CPU bound, and often across a network share, so threads
# rather than processes. Capped per the project's convention.
DEFAULT_WORKERS = 8
PROGRESS_INTERVAL = 500


def check_image(path):
    """
    Fully decode an image to prove it is intact.

    A header read is not sufficient: dimensions live in the first few hundred
    bytes, so a file missing 90% of its scan data still reports a size. Only
    load() walks the entire compressed stream.

    Args:
        path: Path to an image file

    Returns:
        tuple (status, detail) where status is 'ok' or a failure category
    """
    try:
        with Image.open(path) as image:
            image.load()

    except FileNotFoundError:
        return 'missing', 'file disappeared during scan'

    except OSError as error:
        message = str(error)

        if 'truncated' in message.lower():
            return 'truncated', message

        return 'unreadable', message

    except Exception as error:
        return 'unreadable', f"{type(error).__name__}: {error}"

    return 'ok', ''


def check_video(path):
    """
    Probe a video container for structural errors.

    ffprobe writes diagnostics to stderr for truncated or malformed files even when
    it manages to report a duration, so stderr is inspected rather than trusted to
    be empty on success.

    Args:
        path: Path to a video file

    Returns:
        tuple (status, detail)
    """
    try:
        completed = subprocess.run(
            [
                'ffprobe', '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'csv=p=0',
                str(path),
            ],
            capture_output=True, text=True, check=False, timeout=120
        )

    except FileNotFoundError:
        return 'skipped', 'ffprobe not installed'

    except subprocess.TimeoutExpired:
        return 'unreadable', 'ffprobe timed out'

    stderr = completed.stderr.strip()

    if completed.returncode != 0:
        return 'unreadable', stderr[:200] or f"ffprobe exit {completed.returncode}"

    if stderr:
        # Errors surfaced despite a zero exit — typically truncated moov atoms
        return 'suspect', stderr[:200]

    if not completed.stdout.strip():
        return 'unreadable', 'no duration reported'

    return 'ok', ''


def check_file(path):
    """
    Dispatch a single file to the appropriate integrity check.

    Args:
        path: Path to check

    Returns:
        tuple (path, status, detail)
    """
    try:
        size = path.stat().st_size
    except OSError as error:
        return path, 'unreadable', str(error)

    if size == 0:
        return path, 'empty', 'zero bytes'

    suffix = path.suffix.lower()

    if suffix in {extension.lower() for extension in PHOTO_EXTENSIONS}:
        status, detail = check_image(path)
    elif suffix in {extension.lower() for extension in VIDEO_EXTENSIONS}:
        status, detail = check_video(path)
    else:
        status, detail = 'not_checked', 'format not validatable'

    return path, status, detail


def collect_files(root):
    """Gather every non-hidden regular file under root."""
    files = []

    for path in Path(root).rglob('*'):
        if path.is_file() and not path.name.startswith('.'):
            files.append(path)

    return files


def main():
    """Scan a tree and report every file that is not provably intact."""
    parser = argparse.ArgumentParser(
        description="Detect truncated, empty, or unreadable media files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Statuses:
  ok           decoded or probed cleanly
  truncated    the file is short -- data is missing from the end
  empty        zero bytes
  unreadable   could not be decoded at all
  suspect      probed with warnings (videos)
  not_checked  format cannot be validated generically
        """
    )
    parser.add_argument('directory', help="Directory to scan")
    parser.add_argument(
        '--output', metavar='PATH',
        help="Write the list of damaged files to this JSON file"
    )
    parser.add_argument(
        '--workers', type=int, default=DEFAULT_WORKERS,
        help=f"Parallel workers (default: {DEFAULT_WORKERS})"
    )

    args = parser.parse_args()
    root = Path(args.directory)

    if not root.is_dir():
        print(f"ERROR: not a directory: {root}")
        sys.exit(1)

    print(f"Scanning {root}")
    files = collect_files(root)
    print(f"  {len(files):,} files to check, {args.workers} workers\n")

    verdicts = Counter()
    damaged = []
    started = time.time()
    completed_count = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(check_file, path): path for path in files}

        for future in as_completed(futures):
            path, status, detail = future.result()
            verdicts[status] += 1
            completed_count += 1

            if status not in ('ok', 'not_checked'):
                damaged.append({
                    'path': str(path),
                    'name': path.name,
                    'status': status,
                    'detail': detail,
                })

            if completed_count % PROGRESS_INTERVAL == 0:
                elapsed = time.time() - started
                rate = completed_count / elapsed if elapsed else 0
                remaining = (len(files) - completed_count) / rate if rate else 0
                print(f"  {completed_count:,}/{len(files):,}  "
                      f"({remaining:.0f}s remaining, {len(damaged)} damaged so far)...",
                      flush=True)

    elapsed = time.time() - started

    print()
    print("=" * 68)
    print("  MEDIA HEALTH REPORT")
    print("=" * 68)
    print(f"  Scanned: {len(files):,} files in {elapsed:.0f}s\n")

    for status, count in verdicts.most_common():
        share = count / max(len(files), 1) * 100
        print(f"  {status:12s} {count:7,}  ({share:5.1f}%)")

    if damaged:
        print(f"\n  {len(damaged)} file(s) are not provably intact:\n")

        for entry in damaged[:40]:
            print(f"    [{entry['status']}] {entry['name'][:56]}")
            print(f"        {entry['detail'][:88]}")

        if len(damaged) > 40:
            print(f"\n    ... and {len(damaged) - 40} more")
    else:
        print("\n  No damaged files found.")

    if args.output:
        Path(args.output).write_text(json.dumps(damaged, indent=2))
        print(f"\n  Damaged-file list written to: {args.output}")

    # Non-zero exit when something is wrong, so a wrapper script can react
    sys.exit(1 if damaged else 0)


if __name__ == '__main__':
    main()
