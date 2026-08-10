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
    videos  ffprobe on the container by default; --deep fully decodes the stream.
            The container alone cannot see mid-stream damage: five AVCHD files
            reported clean durations while carrying 46-244 decode errors, and lost
            footage when transcoded.
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
import zipfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image, ImageFile

from media_utils import AVCHD_EXTENSIONS, PHOTO_EXTENSIONS, VIDEO_EXTENSIONS

# Refuse PIL's default tolerance. Silently accepting short files is precisely the
# behaviour that let a damaged photo pass unnoticed.
ImageFile.LOAD_TRUNCATED_IMAGES = False

# HEIC needs an explicit opener registration before PIL will touch it. Without this
# every iPhone photo reports "cannot identify image file" and gets flagged as
# damaged — a first run of this tool produced 103 such false positives across the
# archive, all of them perfectly readable files.
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIC_AVAILABLE = True
except ImportError:
    HEIC_AVAILABLE = False

HEIC_SUFFIXES = {'.heic', '.heif'}

# ZIP containers with per-member CRCs. Office and OpenDocument formats are ZIPs, so
# these get the strongest verification available here.
ZIP_FAMILY_SUFFIXES = {
    '.zip', '.docx', '.xlsx', '.pptx', '.odt', '.ods', '.odp', '.epub', '.numbers',
    '.pages', '.key',
}

PDF_SUFFIXES = {'.pdf'}

# Containers ffprobe can validate that are NOT in VIDEO_EXTENSIONS. Their absence
# there is deliberate -- the organizing workflows skip AVCHD because
# workflow_camcorder.py owns it -- but integrity still needs checking. Without this
# the home-movies share reported 741 of 1,465 files as unvalidatable, which is 750
# AVCHD clips nobody had ever verified.
EXTRA_VIDEO_SUFFIXES = (
    {extension.lower() for extension in AVCHD_EXTENSIONS}
    | {'.mpg', '.mpeg', '.m2v', '.vob', '.flv', '.webm', '.mkv', '.wmv', '.3gp'}
)

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


# What ffprobe should call each container. A file whose detected format is not in this
# set is not the kind of file its name claims, which is a different and worse problem
# than being damaged: the original content is simply absent.
EXPECTED_CONTAINERS = {
    '.mts': {'mpegts'},
    '.m2ts': {'mpegts'},
    '.m2t': {'mpegts'},
    '.ts': {'mpegts'},
    '.mp4': {'mov,mp4,m4a,3gp,3g2,mj2'},
    '.m4v': {'mov,mp4,m4a,3gp,3g2,mj2', 'm4v'},
    '.mov': {'mov,mp4,m4a,3gp,3g2,mj2'},
    '.3gp': {'mov,mp4,m4a,3gp,3g2,mj2'},
    '.avi': {'avi'},
    '.mpg': {'mpeg', 'mpegvideo'},
    '.mpeg': {'mpeg', 'mpegvideo'},
    '.wmv': {'asf'},
    '.mkv': {'matroska,webm'},
    '.webm': {'matroska,webm'},
    '.flv': {'flv'},
}


def check_video(path):
    """
    Probe a video container for structural errors, and for not being a video at all.

    ffprobe writes diagnostics to stderr for truncated or malformed files even when it manages to report a duration, so stderr is inspected rather than trusted to be empty on success.

    Beyond damage, this now verifies the file is the kind of thing its name claims. That gap let eight files pass as healthy home movies when they contained no video whatsoever: 2010/00033.MTS is 94 MB of MP3 audio, and ffprobe reports it as a valid 2,959-second mp3 stream. Asking only "does this decode" gets the answer "yes, beautifully", because it is a perfectly intact file of the wrong content. A missing video stream, or a container that disagrees with the extension, means the footage is gone rather than degraded — and no transcode can recover it.

    NOTE: this reads the CONTAINER, not the stream, so it cannot see mid-stream decode damage. Use check_video_deep() when the answer matters — five AVCHD files passed this check with clean durations while carrying 46 to 244 mid-stream H.264 errors, and lost footage when transcoded. For foreign data spliced into an otherwise valid stream, use detect_splices.py.

    Args:
        path: Path to a video file

    Returns:
        tuple (status, detail)
    """
    try:
        completed = subprocess.run(
            [
                'ffprobe', '-v', 'error',
                '-show_entries', 'format=duration,format_name',
                '-show_entries', 'stream=codec_type',
                '-of', 'json',
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

    try:
        probe = json.loads(completed.stdout or '{}')
    except json.JSONDecodeError:
        return 'unreadable', 'ffprobe returned unparseable output'

    container = probe.get('format', {})
    streams = probe.get('streams') or []
    duration = container.get('duration')

    if stderr:
        # Errors surfaced despite a zero exit — typically truncated moov atoms
        return 'suspect', stderr[:200]

    # Content substitution: the file is intact, but it is not a video.
    stream_types = {stream.get('codec_type') for stream in streams}

    if streams and 'video' not in stream_types:
        present = ', '.join(sorted(kind for kind in stream_types if kind)) or 'none'
        return 'not a video', (f"no video stream; contains {present} only "
                               f"(detected as {container.get('format_name', '?')})")

    expected = EXPECTED_CONTAINERS.get(path.suffix.lower())
    detected = container.get('format_name')

    if expected and detected and detected not in expected:
        return 'wrong container', (f"detected as {detected}, expected "
                                   f"{'/'.join(sorted(expected))} for "
                                   f"{path.suffix.lower()}")

    if not duration:
        return 'unreadable', 'no duration reported'

    return 'ok', ''


def _is_muxer_noise(line):
    """
    Report whether an ffmpeg stderr line is an artifact of how we invoke it.

    Decoding to `-f null -` still runs an output muxer, and that muxer complains about
    timestamps it dislikes. Those complaints describe our command, not the file.

    This matters because counting them made the check useless: a first pass over the
    archive flagged 325 files, and 323 of them were this one warning. A checker that
    reports 11.5% of a healthy archive as damaged just teaches you to ignore it.

    Args:
        line: One line of ffmpeg stderr

    Returns:
        bool: True when the line should not count as evidence of damage
    """
    # The null muxer used by our own -f null output
    if line.lstrip().startswith('[null @'):
        return True

    # Emitted with no component prefix in some builds
    if 'non monotonic' in line or 'Non-monotonous DTS' in line:
        return True

    return False


def check_video_deep(path):
    """
    Decode a video's entire stream and count the errors it produces.

    A container probe is not sufficient, and the gap is not theoretical. Five AVCHD files passed `check_video()` reporting clean durations while carrying 46 to 244 mid-stream H.264 errors. When transcoded, ffmpeg decoded until it hit an unrecoverable error and then stopped — producing short but structurally valid output and exiting zero. One clip lost 72 of its 103 seconds, and nothing noticed until source and output durations were compared.

    Images have always been fully decoded here for exactly this reason. This brings video to the same standard, at the cost of real decode time, so it is opt-in rather than the default.

    Args:
        path: Path to a video file

    Returns:
        tuple (status, detail)
    """
    try:
        completed = subprocess.run(
            ['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'null', '-'],
            capture_output=True, text=True, check=False, timeout=1800
        )

    except FileNotFoundError:
        return 'skipped', 'ffmpeg not installed'

    except subprocess.TimeoutExpired:
        return 'unreadable', 'decode timed out'

    errors = [
        line for line in completed.stderr.split('\n')
        if line.strip() and not _is_muxer_noise(line)
    ]

    if completed.returncode != 0:
        detail = errors[0] if errors else f'ffmpeg exit {completed.returncode}'
        return 'unreadable', detail[:200]

    if errors:
        # Reached the end, but not cleanly. A transcode of this will lose footage.
        return 'stream errors', f"{len(errors)} decode errors; first: {errors[0][:110]}"

    return 'ok', ''


def check_zip_family(path):
    """
    Verify a ZIP-based file by testing the CRC of every member.

    This is the strongest check available anywhere in this module, and it is not
    limited to media. Office documents (.docx, .xlsx, .pptx), OpenDocument files and
    .epub are all ZIP containers, and ZIP stores a CRC32 per member. testzip()
    recomputes every one, so any altered or missing byte is caught outright — no
    heuristics involved.

    That matters more than it first appears: this data has crossed three NAS
    generations and only the current one uses ZFS, so any corruption inherited from
    the earlier two was copied in already damaged and has been checksummed as
    "correct" ever since. A ZFS scrub cannot see it. A CRC test can.

    Args:
        path: Path to a ZIP-based file

    Returns:
        tuple (status, detail)
    """
    try:
        with zipfile.ZipFile(path) as archive:
            bad_member = archive.testzip()

        if bad_member is not None:
            return 'corrupt', f"CRC mismatch in member: {bad_member}"

    except zipfile.BadZipFile as error:
        return 'unreadable', f"not a valid zip container: {error}"

    except OSError as error:
        return 'unreadable', str(error)

    return 'ok', ''


def check_pdf(path):
    """
    Check a PDF for its end-of-file marker.

    PDF requires a trailing `%%EOF`. Its absence means the file was truncated, which
    is the same interrupted-write failure that damaged a photo in the source tree.
    This does not validate the internal object graph — a full parse would need a PDF
    library — so it catches truncation but not deeper corruption.

    Args:
        path: Path to a PDF

    Returns:
        tuple (status, detail)
    """
    try:
        with open(path, 'rb') as handle:
            # The marker may be followed by trailing whitespace or newlines
            handle.seek(0, 2)
            tail_size = min(handle.tell(), 2048)
            handle.seek(-tail_size, 2)
            tail = handle.read()

    except OSError as error:
        return 'unreadable', str(error)

    if not tail.strip().endswith(b'%%EOF'):
        return 'truncated', 'missing %%EOF marker'

    return 'ok', ''


def check_file(path, deep=False):
    """
    Dispatch a single file to the appropriate integrity check.

    Args:
        path: Path to check
        deep: Fully decode video rather than probing its container

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

    # Be honest about an unvalidatable format rather than calling it damaged. If the
    # HEIF opener is missing, HEIC files cannot be judged either way, and reporting
    # them as broken would be a false alarm on thousands of iPhone photos.
    if suffix in HEIC_SUFFIXES and not HEIC_AVAILABLE:
        return path, 'not_checked', 'pillow-heif not installed; cannot validate HEIC'

    if suffix in {extension.lower() for extension in PHOTO_EXTENSIONS}:
        status, detail = check_image(path)
    elif suffix in {extension.lower() for extension in VIDEO_EXTENSIONS} \
            or suffix in EXTRA_VIDEO_SUFFIXES:
        status, detail = check_video_deep(path) if deep else check_video(path)
    elif suffix in ZIP_FAMILY_SUFFIXES:
        status, detail = check_zip_family(path)
    elif suffix in PDF_SUFFIXES:
        status, detail = check_pdf(path)
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
  suspect        probed with warnings (videos)
  stream errors  decoded to the end but with errors; a transcode will lose footage
  corrupt      CRC mismatch inside a zip-based file -- bytes have changed
  not_checked  format cannot be validated generically
        """
    )
    parser.add_argument('directory', help="Directory to scan")
    parser.add_argument(
        '--output', metavar='PATH',
        help="Write the list of damaged files to this JSON file"
    )
    parser.add_argument(
        '--deep', action='store_true',
        help=(
            "Fully decode video instead of probing its container. Far slower, and the only "
            "way to see mid-stream damage: five files passed the fast check with clean "
            "durations while carrying up to 244 decode errors, then lost footage when "
            "transcoded. Use before trusting a transcode as authoritative."
        )
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
        futures = {executor.submit(check_file, path, args.deep): path for path in files}

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
