#!/usr/bin/env python3
"""
Salvage whatever is still readable from files containing foreign content.

The originating SD cards are gone, so the damaged copies on the NAS are the only
surviving record. That makes salvage a one-shot job: whatever this extracts is what
survives, and the sources must never be modified.

Two very different situations, and lumping them together loses footage:

SPLICED  Real video, then somebody else's bytes. The valid prefix is intact AVCHD and
         re-encodes at full quality if it is cut on a packet boundary first. Handing
         the whole file to ffmpeg instead makes it fight through the foreign region,
         which is how five of these ended up short when they were first converted.

FOREIGN  No footage of their own -- but they are not empty. They hold other real files:
         roughly six hours of MP3 audio, a JPEG, an m4v, and two that ffprobe reads as
         transport streams with h264 video despite having no TS structure at the start.
         Deleting them would destroy that content too, so each is extracted as whatever
         it actually is rather than forced into a video pipeline.

Everything lands in _RESCUED/ with `_DAMAGED` in the name, so a partial recovery can
never be mistaken for a clean original once it is sitting beside real footage.

Read-only with respect to every source. Nothing is moved, deleted, or overwritten.

Usage:
    python3 rescue_damaged_media.py --findings .TMP_splices/04_home_movies.json
    python3 rescue_damaged_media.py --findings f.json --dry-run
    python3 rescue_damaged_media.py --findings f.json --only 00030
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent
RESCUE_ROOT = REPO / '_RESCUED'
SCRATCH = Path('/private/tmp/process-media-rescue')

# Matches camcorder_convert.py, so rescued footage sits beside the archive on the same
# terms rather than introducing a second quality standard.
FFMPEG_CRF = 26
FFMPEG_PRESET = 'slow'
FFMPEG_AUDIO_BITRATE = '192k'

DAMAGED_MARKER = '_DAMAGED'

# Rescued files carry a second marker when more than one piece came out of one source.
# "extracted" rather than "carved": it describes the result, not the technique, and the
# same word then covers a whole-file decode, a prefix cut and a region carve alike.
EXTRACTED_MARKER = '_extracted'

# Error-tolerant demuxing. These files are damaged by definition, so ffmpeg's default
# strictness throws away material it could otherwise carry through.
TOLERANT_INPUT = ['-err_detect', 'ignore_err', '-fflags', '+genpts+igndts']

TIMEOUT_PROBE = 120
TIMEOUT_ENCODE = 7200



def output_name(source, captured, suffix, index=None):
    """
    Build a rescued file's name: capture date first, then provenance, then markers.

    The date leads because the archive is ordered that way -- everything around these
    files is named `20091225_202803_CAM.h265.mp4`, so a name starting with the source's
    reel number sorts to the top of the folder and breaks the chronology the folder
    exists to express.

    The original stem is kept after the date so the file can always be traced back to
    the damaged source it came from, and `_DAMAGED` stays so a partial recovery can
    never be mistaken for a clean original.

    Args:
        source:   Path of the damaged source file
        captured: datetime the footage was recorded, or None if unrecoverable
        suffix:   Output extension, including the dot
        index:    1-based sequence number when one source yields several outputs

    Returns:
        str: e.g. '20091225_191220_00006_DAMAGED_extracted1.mp4'
    """
    parts = []

    if captured is not None:
        parts.append(f"{captured:%Y%m%d_%H%M%S}")

    parts.append(source.stem)
    name = '_'.join(parts) + DAMAGED_MARKER

    if index is not None:
        name += f"{EXTRACTED_MARKER}{index}"

    return f"{name}{suffix}"


def probe(path, extra=None):
    """
    Return ffprobe's view of a file as a dict, or None when it cannot read it.

    Used to decide strategy and to measure what a rescue actually recovered, so it
    reports rather than raises on failure.
    """
    command = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=format_name,duration',
        '-show_entries', 'stream=codec_type,codec_name,width,height',
        '-of', 'json',
    ]

    if extra:
        command.extend(extra)

    command.append(str(path))

    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   check=False, timeout=TIMEOUT_PROBE)
        return json.loads(completed.stdout or '{}')
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None


def source_capture_date(source):
    """
    Return when the damaged source was actually recorded, or None.

    A rescued file is a fresh encode, so it carries no capture metadata of its own and
    its mtime is the moment of rescue. Without this, organize_archive.py falls through
    to the mtime and files a 2009 home movie under the current month -- all 29 rescues
    landed in one 2026 folder, wrong by seventeen years.
    """
    try:
        from camcorder_convert import get_creation_date
        result = get_creation_date(source)
    except Exception:
        return None

    # get_creation_date returns (datetime, provenance)
    if isinstance(result, tuple):
        result = result[0] if result else None

    return result


def stamp_dates(path, when):
    """
    Write a capture date onto a rescued file, in metadata and on the filesystem.

    Both matter and for different reasons: the organizer prefers embedded EXIF, but
    falls back to mtime, and the mtime is what survives a copy to a share that strips
    metadata. Failure is reported rather than raised -- a rescued file with a wrong date
    is still worth keeping.
    """
    if when is None:
        return False, 'no source date available'

    stamped = False

    if path.suffix.lower() in {'.mp4', '.m4v', '.mov', '.jpg', '.jpeg'}:
        try:
            completed = subprocess.run(
                ['exiftool', '-overwrite_original', '-q',
                 f'-CreateDate={when:%Y:%m:%d %H:%M:%S}',
                 f'-ModifyDate={when:%Y:%m:%d %H:%M:%S}',
                 str(path)],
                capture_output=True, text=True, check=False, timeout=TIMEOUT_PROBE)
            stamped = completed.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            stamped = False

    try:
        timestamp = when.timestamp()
        import os
        os.utime(path, (timestamp, timestamp))
    except (OSError, OverflowError, ValueError) as error:
        return stamped, f"mtime not set: {error}"

    return True, 'metadata and mtime' if stamped else 'mtime only'


def count_frames(path):
    """
    Return the number of video frames actually present in a file.

    Frames, not duration, measure how much picture survived. A salvaged file keeps the
    original timestamps, so recovered frames sit scattered across the source's timeline
    with gaps where the damage was: 00003's rescue reports 27.19s but holds 242 frames,
    an average of 8.9 fps. Judging that as "27 seconds recovered" would flatter it, and
    comparing two rescues by duration can pick the gappier one.
    """
    command = [
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-count_frames', '-show_entries', 'stream=nb_read_frames',
        '-of', 'csv=p=0', str(path),
    ]

    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   check=False, timeout=TIMEOUT_ENCODE)
        return int((completed.stdout or '0').strip().rstrip(',') or 0)
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return 0


def describe(info):
    """Summarize a probe result as (duration_seconds, stream_kinds)."""
    if not info:
        return 0.0, set()

    duration = info.get('format', {}).get('duration')

    try:
        duration = float(duration)
    except (TypeError, ValueError):
        duration = 0.0

    kinds = set()

    for stream in info.get('streams') or []:
        kind = stream.get('codec_type')

        if kind:
            kinds.add(kind)

    return duration, kinds


def cut_valid_prefix(source, splice_offset, destination):
    """
    Copy the bytes before the splice into a standalone file.

    Byte-exact, no decoding: the prefix is intact AVCHD and stays that way. The offset
    comes from detect_splices.py, which walks the packet grid, so the cut lands on a
    packet boundary rather than mid-packet.
    """
    remaining = splice_offset
    chunk_size = 8 << 20

    with source.open('rb') as reader, destination.open('wb') as writer:
        while remaining > 0:
            chunk = reader.read(min(chunk_size, remaining))

            if not chunk:
                break

            writer.write(chunk)
            remaining -= len(chunk)

    return destination.stat().st_size


def encode_video(source, destination, note):
    """
    Transcode to H.265 on the archive's own terms.

    Returns (ok, detail). Failure is reported rather than raised so one unsalvageable
    file cannot abort the run -- with the cards gone there is no second attempt.
    """
    command = ['ffmpeg', '-y', '-v', 'error']
    command.extend(TOLERANT_INPUT)
    command.extend([
        '-i', str(source),
        '-c:v', 'libx265',
        '-crf', str(FFMPEG_CRF),
        '-preset', FFMPEG_PRESET,
        '-x265-params', 'pools=*:frame-threads=0',
        '-tag:v', 'hvc1',
        '-c:a', 'aac',
        '-b:a', FFMPEG_AUDIO_BITRATE,
        '-movflags', '+faststart',
        '-metadata', f'comment={note}',
        str(destination),
    ])

    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   check=False, timeout=TIMEOUT_ENCODE)
    except subprocess.TimeoutExpired:
        return False, 'ffmpeg timed out'

    if completed.returncode != 0 or not destination.exists():
        return False, (completed.stderr or '').strip()[:200]

    if destination.stat().st_size == 0:
        return False, 'produced an empty file'

    return True, ''


def copy_stream(source, destination, kind):
    """
    Extract a stream without re-encoding, for content that is already final.

    The MP3s and the JPEG inside these files are somebody's actual media. Re-encoding
    them would add loss for no reason, so they are copied out as-is.
    """
    command = ['ffmpeg', '-y', '-v', 'error']
    command.extend(TOLERANT_INPUT)
    command.extend(['-i', str(source)])

    if kind == 'audio':
        command.extend(['-map', '0:a:0', '-c:a', 'copy'])
    elif kind == 'image':
        command.extend(['-map', '0:v:0', '-frames:v', '1', '-c:v', 'copy'])
    else:
        command.extend(['-c', 'copy'])

    command.append(str(destination))

    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   check=False, timeout=TIMEOUT_ENCODE)
    except subprocess.TimeoutExpired:
        return False, 'ffmpeg timed out'

    if completed.returncode != 0 or not destination.exists() \
            or destination.stat().st_size == 0:
        return False, (completed.stderr or '').strip()[:200]

    return True, ''


# --- Carving -----------------------------------------------------------------------
# For files ffprobe cannot open at all. It probes only the start, so a file whose first
# bytes are unstructured reads as empty even when it holds 50 MB of transport stream
# three quarters of the way in -- which is exactly the case for 2009/00006.MTS.
CARVE_WINDOW = 1 << 20
CARVE_PROBE = 1 << 18
CARVE_MAX_BYTES = 1 << 30  # refuse to read anything absurd into memory
MIN_CARVED_REGION = 4 << 20  # smaller regions are not worth a transcode
MIN_CARVED_JPEG = 12 << 10
SYNC_BYTE = 0x47
TS_STRIDE = 192


def classify_window(chunk):
    """
    Name the kind of data in one window: 'ts', 'mp3', 'jpeg', or 'unknown'.

    Deliberately cheaper and coarser than detect_splices.classify_foreign, because this
    runs across every megabyte of a large file rather than on a handful of samples.
    """
    if len(chunk) < TS_STRIDE * 32:
        return 'unknown'

    # Transport stream at any phase
    sample = chunk[:TS_STRIDE * 400]

    for phase in range(TS_STRIDE):
        positions = range(phase, len(sample), TS_STRIDE)
        hits = sum(1 for index in positions if sample[index] == SYNC_BYTE)
        expected = len(range(phase, len(sample), TS_STRIDE))

        if expected and hits / expected > 0.95:
            return 'ts'

    lowered = chunk[:CARVE_PROBE]

    if b'LAME' in lowered or b'ID3' in lowered[:4096]:
        return 'mp3'

    if lowered.count(b'\xff\xfb') + lowered.count(b'\xff\xfa') > len(lowered) / 2000:
        return 'mp3'

    if b'\xff\xd8\xff' in lowered:
        return 'jpeg'

    return 'unknown'


def profile_carve_regions(path):
    """
    Walk a whole file and group it into contiguous regions by content type.

    Returns a list of (kind, start, end). This is what turns "ffprobe finds nothing"
    into an actionable map of what is actually inside.
    """
    size = path.stat().st_size
    regions = []

    with path.open('rb') as handle:
        position = 0

        while position < size:
            handle.seek(position)
            chunk = handle.read(CARVE_PROBE)

            if not chunk:
                break

            kind = classify_window(chunk)

            if regions and regions[-1][0] == kind and regions[-1][2] == position:
                regions[-1][2] = min(position + CARVE_WINDOW, size)
            else:
                regions.append([kind, position, min(position + CARVE_WINDOW, size)])

            position += CARVE_WINDOW

    return regions


def align_to_sync(data):
    """
    Trim leading bytes so a carved transport stream starts on a packet boundary.

    Without this ffmpeg has to guess where the packet grid begins and often refuses the
    file outright.
    """
    for start in range(min(len(data) - TS_STRIDE * 32, TS_STRIDE * 2)):
        if data[start] != SYNC_BYTE:
            continue

        if all(data[start + step * TS_STRIDE] == SYNC_BYTE for step in range(1, 32)):
            return start

    return 0


def carve_jpegs(data, output_dir, source, captured, start_index, limit=40):
    """
    Extract complete JPEG images from a byte range, keeping only ones that decode.

    Validation matters: a naive SOI-to-EOI carve produces mostly garbage, and garbage
    images in a rescue folder are worse than none because they have to be reviewed.

    `start_index` continues the caller's numbering so that images and video fragments
    pulled from one source share a single sequence rather than each starting at 1.
    """
    try:
        from PIL import Image, ImageFile
        ImageFile.LOAD_TRUNCATED_IMAGES = False
    except ImportError:
        return []

    import io

    saved = []
    position = 0

    while len(saved) < limit:
        start = data.find(b'\xff\xd8\xff', position)

        if start < 0:
            break

        end = data.find(b'\xff\xd9', start)

        if end < 0:
            break

        end += 2
        candidate = data[start:end]
        position = end

        if len(candidate) < MIN_CARVED_JPEG:
            continue

        try:
            image = Image.open(io.BytesIO(candidate))
            image.load()

            if min(image.size) < 120:
                continue

        except Exception:
            continue

        destination = output_dir / output_name(source, captured, ".jpg", start_index + len(saved))
        destination.write_bytes(candidate)
        saved.append((destination, image.size))

    return saved


def rescue_by_carving(finding, dry_run, captured=None):
    """
    Last resort for files ffprobe cannot open: map their contents and extract each part.

    Two sources here hold 333 MB between them and read as completely unreadable, yet one
    carries transport-stream video in its final quarter and the other holds JPEGs and
    MP3 audio throughout. With the original cards gone, writing those off untried would
    be discarding the only copy.
    """
    source = Path(finding['path'])
    size = source.stat().st_size

    if size > CARVE_MAX_BYTES:
        return {'source': str(source), 'strategy': 'carve', 'status': 'too large',
                'detail': f"{size:,} bytes exceeds the carving limit"}

    regions = profile_carve_regions(source)
    worthwhile = [r for r in regions
                  if r[0] != 'unknown' and (r[2] - r[1]) >= MIN_CARVED_REGION]
    summary = ', '.join(f"{kind} {(end - start) / 1e6:.0f}MB"
                        for kind, start, end in worthwhile) or 'nothing identifiable'

    if dry_run:
        return {'source': str(source), 'strategy': 'carve',
                'status': 'would carve' if worthwhile else 'nothing to carve',
                'detail': summary}

    if not worthwhile:
        return {'source': str(source), 'strategy': 'carve', 'status': 'unidentifiable',
                'detail': 'no region large enough to be worth extracting'}

    year = year_for(source)
    output_dir = RESCUE_ROOT / year
    output_dir.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)

    produced = []
    recovered_seconds = 0.0

    for index, (kind, start, end) in enumerate(worthwhile, start=1):
        with source.open('rb') as handle:
            handle.seek(start)
            data = handle.read(end - start)

        if kind == 'jpeg':
            images = carve_jpegs(data, output_dir, source, captured, len(produced) + 1)
            produced.extend(str(p.relative_to(REPO)) for p, _ in images)
            continue

        if kind == 'ts':
            offset = align_to_sync(data)
            fragment = SCRATCH / f"{source.stem}_carve{index}.mts"
            fragment.write_bytes(data[offset:])
            destination = output_dir / output_name(source, captured, ".mp4", len(produced) + 1)
            note = (f"Carved from {source.name} bytes {start}-{end}; the source holds "
                    f"no footage of its own")
            ok, _ = encode_video(fragment, destination, note)
            fragment.unlink(missing_ok=True)

            if ok:
                duration, _ = describe(probe(destination))
                recovered_seconds += duration
                produced.append(str(destination.relative_to(REPO)))
            continue

        if kind == 'mp3':
            destination = output_dir / output_name(source, captured, ".mp3", len(produced) + 1)
            destination.write_bytes(data)
            duration, kinds = describe(probe(destination))

            # Raw bytes only count as a rescue if a decoder can actually read them
            if 'audio' in kinds:
                recovered_seconds += duration
                produced.append(str(destination.relative_to(REPO)))
            else:
                destination.unlink(missing_ok=True)

    if not produced:
        return {'source': str(source), 'strategy': 'carve', 'status': 'unidentifiable',
                'detail': f"regions found ({summary}) but nothing decoded"}

    return {
        'source': str(source), 'strategy': 'carve', 'status': 'rescued',
        'output': '; '.join(produced[:6]),
        'detail': f"{len(produced)} file(s) carved — {summary}",
        'duration': recovered_seconds,
        'carved': produced,
    }


def year_for(source):
    """Pick the output subfolder from the source's own path."""
    for part in source.parts:
        if len(part) == 4 and part.isdigit() and part.startswith(('19', '20')):
            return part

    return 'undated'


def rescue_spliced(finding, dry_run, captured=None):
    """
    Recover as much video as possible from a spliced file, by measuring rather than
    assuming which approach wins.

    The intuition that a clean cut at the first splice beats letting ffmpeg fight
    through the foreign region is WRONG, and measurably so. On 2009/00009.MTS the
    prefix cut yielded 13.3s where a whole-file decode yielded 30.6s; on 00017 it was
    15.0s against 41.9s. Valid video resumes after the first foreign region -- the
    phase-shifted stretches detect_splices.py refuses to call lost are, at least partly,
    the recording continuing -- so cutting at the first splice discards all of it.

    The cut still wins where damage begins early and never recovers, so both are
    encoded and the longer result is kept. With the source cards gone, an extra encode
    is cheap next to silently discarding half the surviving footage.
    """
    source = Path(finding['path'])
    splice = finding.get('splice_offset') or 0
    year = year_for(source)
    output_dir = RESCUE_ROOT / year
    destination = output_dir / output_name(source, captured, ".mp4")

    # Deliberately low. 192 KB of AVCHD is only a second or two, but the originating
    # cards are gone, so a second of footage that exists nowhere else is worth an
    # encode. Let ffmpeg decide whether it is decodable rather than pre-judging by size.
    if splice < (192 << 10):
        return {
            'source': str(source), 'strategy': 'spliced',
            'status': 'too little valid video',
            'detail': f"only {splice:,} bytes precede the splice",
        }

    if dry_run:
        return {
            'source': str(source), 'strategy': 'spliced', 'status': 'would rescue',
            'detail': f"{splice / 1e6:.1f} MB of valid video -> {destination.name}",
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)

    note = (f"Partial recovery from damaged source {source.name}: "
            f"first foreign data at byte {splice}")

    # Candidate A: the clean prefix, cut on a packet boundary
    prefix = SCRATCH / f"{source.stem}_prefix.mts"
    cut_output = SCRATCH / f"{source.stem}_cut.mp4"
    cut_duration = 0.0

    try:
        cut_valid_prefix(source, splice, prefix)
        cut_ok, cut_detail = encode_video(prefix, cut_output, note)

        if cut_ok:
            cut_duration, _ = describe(probe(cut_output))
    finally:
        prefix.unlink(missing_ok=True)

    # Candidate B: the whole file, decoded with error tolerance
    whole_output = SCRATCH / f"{source.stem}_whole.mp4"
    whole_ok, whole_detail = encode_video(source, whole_output, note)
    whole_duration = 0.0

    if whole_ok:
        whole_duration, _ = describe(probe(whole_output))

    if not cut_ok and not whole_ok:
        cut_output.unlink(missing_ok=True)
        whole_output.unlink(missing_ok=True)
        return {'source': str(source), 'strategy': 'spliced', 'status': 'failed',
                'detail': (cut_detail or whole_detail)[:200]}

    # Compare on frames, not duration. A gappy recovery can span a longer timeline while
    # holding less actual picture, and duration would hand it the win.
    cut_frames = count_frames(cut_output) if cut_ok else 0
    whole_frames = count_frames(whole_output) if whole_ok else 0

    if whole_frames >= cut_frames:
        winner, loser, approach = whole_output, cut_output, 'whole-file decode'
    else:
        winner, loser, approach = cut_output, whole_output, 'prefix cut'

    destination.unlink(missing_ok=True)
    shutil.move(str(winner), str(destination))
    loser.unlink(missing_ok=True)

    duration, kinds = describe(probe(destination))
    frames = max(cut_frames, whole_frames)

    return {
        'source': str(source), 'strategy': 'spliced', 'status': 'rescued',
        'output': str(destination.relative_to(REPO)),
        'detail': (f"{frames} frames over {duration:.1f}s via {approach} "
                   f"(prefix cut {cut_frames}f/{cut_duration:.1f}s vs whole file "
                   f"{whole_frames}f/{whole_duration:.1f}s)"),
        'duration': duration,
        'frames': frames,
        'approach': approach,
        'prefix_cut_frames': cut_frames,
        'whole_file_frames': whole_frames,
        'prefix_cut_seconds': round(cut_duration, 2),
        'whole_file_seconds': round(whole_duration, 2),
        'streams': sorted(kinds),
    }


def rescue_foreign(finding, dry_run, captured=None):
    """
    Extract whatever real content a foreign file holds, as its own type.

    These carry no footage of their own, but they are far from empty, and forcing them
    through a video pipeline would discard hours of audio.
    """
    source = Path(finding['path'])
    info = probe(source)
    duration, kinds = describe(info)
    container = (info or {}).get('format', {}).get('format_name', '') or ''
    year = year_for(source)
    output_dir = RESCUE_ROOT / year

    # ffprobe only inspects the beginning, so "no readable stream" means "nothing at the
    # start" rather than "nothing at all". Fall through to carving before giving up.
    if not kinds:
        return rescue_by_carving(finding, dry_run, captured)

    # Video wins when present: two of these read as transport streams carrying h264
    # despite having no TS structure at the start, which detect_splices.py could not
    # see because it only inspects the first 400 packets.
    if 'video' in kinds and container not in {'jpeg_pipe', 'png_pipe', 'image2'}:
        destination = output_dir / output_name(source, captured, ".mp4")
        kind, action = 'video', 'transcode'
    elif 'video' in kinds:
        destination = output_dir / output_name(source, captured, ".jpg")
        kind, action = 'image', 'copy'
    elif 'audio' in kinds:
        suffix = '.mp3' if 'mp3' in container else '.m4a'
        destination = output_dir / output_name(source, captured, suffix)
        kind, action = 'audio', 'copy'
    else:
        return {'source': str(source), 'strategy': 'foreign',
                'status': 'unidentifiable',
                'detail': f"streams {sorted(kinds)} in {container}"}

    if dry_run:
        return {
            'source': str(source), 'strategy': 'foreign', 'status': 'would rescue',
            'detail': (f"holds {kind} ({container}, {duration:.0f}s) -> "
                       f"{destination.name} by {action}"),
        }

    output_dir.mkdir(parents=True, exist_ok=True)

    if action == 'transcode':
        note = f"Recovered foreign content from {source.name}, which holds no footage of its own"
        ok, detail = encode_video(source, destination, note)
    else:
        ok, detail = copy_stream(source, destination, kind)

    if not ok:
        return {'source': str(source), 'strategy': 'foreign',
                'status': 'failed', 'detail': detail}

    recovered, _ = describe(probe(destination))

    return {
        'source': str(source), 'strategy': 'foreign', 'status': 'rescued',
        'output': str(destination.relative_to(REPO)),
        'detail': f"{kind} recovered ({recovered:.0f}s)" if recovered
                  else f"{kind} recovered",
        'duration': recovered,
        'streams': sorted(kinds),
    }


def main():
    """Rescue every damaged source named in a detect_splices.py findings file."""
    parser = argparse.ArgumentParser(
        description="Salvage readable content from files holding foreign data")
    parser.add_argument('--findings', type=Path, required=True,
                        help="JSON output from detect_splices.py")
    parser.add_argument('--dry-run', action='store_true',
                        help="Report what would be rescued without encoding")
    parser.add_argument('--only', help="Substring filter on the source filename")
    parser.add_argument('--force-carve', action='store_true',
                        help="Carve every target, even ones ffprobe opens successfully. "
                             "Worth it when direct extraction returns far less than the "
                             "source size suggests: 2010/00057.MTS is 142.6 MB and gave "
                             "up only 21 seconds through ffprobe.")

    args = parser.parse_args()

    if not args.findings.exists():
        print(f"No such findings file: {args.findings}")
        sys.exit(1)

    findings = json.loads(args.findings.read_text())
    targets = [f for f in findings
               if f.get('status') in {'spliced', 'entirely foreign'}]

    if args.only:
        targets = [f for f in targets if args.only in Path(f['path']).name]

    targets.sort(key=lambda f: f['path'])

    print(f"Rescue targets: {len(targets)}")
    print(f"  output: {RESCUE_ROOT}")
    print(f"  every filename carries {DAMAGED_MARKER}, so a partial recovery cannot be "
          f"mistaken for a clean original")

    if args.dry_run:
        print("  DRY RUN — nothing will be written")

    print()

    results = []
    started = time.time()

    for position, finding in enumerate(targets, start=1):
        source = Path(finding['path'])

        if not source.exists():
            print(f"  [{position}/{len(targets)}] {source.name} — source unreachable")
            results.append({'source': str(source), 'status': 'source missing',
                            'strategy': '-', 'detail': 'share not mounted?'})
            continue

        print(f"  [{position}/{len(targets)}] {source.parent.name}/{source.name} "
              f"({finding['status']})", flush=True)

        # Resolved before dispatch rather than after, because the capture date is now
        # the leading element of every output filename, not just metadata written later.
        captured = source_capture_date(source)

        if args.force_carve:
            outcome = rescue_by_carving(finding, args.dry_run, captured)
        elif finding['status'] == 'spliced':
            outcome = rescue_spliced(finding, args.dry_run, captured)
        else:
            outcome = rescue_foreign(finding, args.dry_run, captured)

        # Stamp the capture date onto every output, in one place rather than at each
        # strategy's return site. A rescued file is a fresh encode with no capture
        # metadata, so without this the organizer falls back to its mtime and files a
        # 2009 recording under the current month.
        if outcome['status'] == 'rescued' and not args.dry_run:
            outputs = list(outcome.get('carved') or [])

            if outcome.get('output'):
                outputs.append(outcome['output'])

            stamped = 0

            for relative in outputs:
                candidate = REPO / relative

                if candidate.exists() and stamp_dates(candidate, captured)[0]:
                    stamped += 1

            outcome['capture_date'] = captured.isoformat() if captured else None
            outcome['stamped_outputs'] = stamped

            if captured is None:
                print("        WARNING: no capture date on the source; outputs will "
                      "date to now")

        results.append(outcome)
        print(f"        {outcome['status']}: {outcome.get('detail', '')[:110]}",
              flush=True)

    elapsed = time.time() - started

    print()
    print("=" * 72)
    print("  RESCUE SUMMARY")
    print("=" * 72)
    print(f"  {len(targets)} source(s) in {elapsed / 60:.1f} minutes\n")

    statuses = Counter(r['status'] for r in results)

    for status, count in statuses.most_common():
        print(f"    {status:24s} {count}")

    recovered = [r for r in results if r['status'] == 'rescued']

    if recovered:
        total = sum(r.get('duration', 0) or 0 for r in recovered)
        print(f"\n  {total / 60:.1f} minutes of content recovered across "
              f"{len(recovered)} file(s)")

    failed = [r for r in results if r['status'] in {'failed', 'unidentifiable',
                                                    'too little valid video'}]

    if failed:
        print(f"\n  {len(failed)} source(s) yielded nothing:")

        for outcome in failed:
            print(f"    {Path(outcome['source']).name}: {outcome['detail'][:90]}")

    manifest = RESCUE_ROOT / 'rescue_manifest.json'

    if not args.dry_run:
        RESCUE_ROOT.mkdir(parents=True, exist_ok=True)

        # Merge rather than overwrite. Rescues are run in several passes -- spliced
        # files re-done with a better strategy, thin ones re-carved -- and overwriting
        # left the manifest holding only the last pass. That silently disabled the
        # provenance check in preflight_import.py, which is the only thing that can tell
        # a rescued file is already archived under a different name.
        merged = {}

        if manifest.exists():
            try:
                for record in json.loads(manifest.read_text()):
                    merged[record.get('source')] = record
            except (json.JSONDecodeError, OSError):
                merged = {}

        for record in results:
            merged[record.get('source')] = record

        manifest.write_text(json.dumps(list(merged.values()), indent=2))
        print(f"\n  manifest written to {manifest.relative_to(REPO)} "
              f"({len(merged)} sources recorded)")
        print("  Nothing was imported into the archive. Review before organizing.")
        print("  Run preflight_import.py before any import — a rescued file whose source "
              "was\n  already converted duplicates archived content that no hash can "
              "match.")


if __name__ == '__main__':
    main()
