#!/usr/bin/env python3
"""
Detect foreign content spliced into media files — data belonging to a different file.

This is a distinct failure from anything else checked here, and the existing tools are
blind to it by design. `check_media_health.py --deep` asks "does this decode", which
catches the symptom but attributes it to codec damage. It cannot tell that the reason
2010/00065.MTS stops decoding 49 MB in is that the remaining 20 MB belongs to a
different recording, or that 2010/00066.MTS is not a video at all but 174 MB of MP3
fragments wearing an .MTS name.

Why that distinction changes decisions:

    codec damage    the footage is degraded but present; a transcode salvages what it can
    foreign content the footage is GONE, replaced by unrelated bytes. No recovery is
                    possible from this copy, and the file's reported duration is a lie.

Detection principle — structural continuity. Every container we hold is a chain with a
predictable next step, and foreign data breaks the chain in a way random corruption does
not:

    MPEG-TS   0x47 sync byte every 192 bytes (AVCHD BDAV), for the whole file
    ISOBMFF   box chain: 4-byte size, 4-byte ASCII type, seek, repeat
    JPEG      marker segments to a single End-of-Image
    PNG       length-prefixed chunks to IEND

The strongest signal comes from transport streams, because a chunk lifted from another
.MTS still holds sync every 192 bytes — just at a different PHASE, since the splice
point does not respect the donor file's packet grid. Measuring that phase distinguishes
"blocks from another video" from "blocks from an audio file" from "unstructured data".
Observed in practice: host files at phase 4, donor data at phase 64.

WHAT THIS CANNOT SEE: transport streams are sampled (see PROBE_BYTES), so foreign
regions smaller than roughly one megabyte are invisible. Every case found so far spans
20-140 MB, but --full disables sampling if exhaustiveness matters more than time.

Read-only. Never moves, deletes, or repairs anything.

Usage:
    python3 detect_splices.py /Volumes/home-movies
    python3 detect_splices.py Organized_Videos --output splices.json
    python3 detect_splices.py Organized_Photos --workers 8
    python3 detect_splices.py /some/tree --full        # no sampling
"""

import argparse
import json
import math
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from media_utils import AVCHD_EXTENSIONS, PHOTO_EXTENSIONS, VIDEO_EXTENSIONS

# --- MPEG-TS ---------------------------------------------------------------------
SYNC_BYTE = 0x47
# AVCHD .MTS is BDAV: a 4-byte TP_extra_header ahead of each 188-byte TS packet.
# Plain .ts broadcast captures use 188. Both are tried.
TS_STRIDES = (192, 188)
TS_HEAD_PACKETS = 400  # packets inspected to establish the file's own phase
TS_MIN_HEAD_RATIO = 0.90  # below this at every phase, the file has no TS structure
WINDOW_BYTES = 1 << 20
PROBE_BYTES = 1 << 16  # bytes actually read per window when sampling
COLLAPSE_RATIO = 0.50  # a window below this holds no TS structure
RECOVERY_PACKETS = 64  # consecutive misses before declaring a splice, not a glitch

# --- ISOBMFF ---------------------------------------------------------------------
ISOBMFF_SUFFIXES = {'.mp4', '.m4v', '.mov', '.heic', '.heif', '.m4a'}
BOX_TYPE_PATTERN = re.compile(rb'^[\x20-\x7e]{4}$')
MAX_BOXES = 4096  # a real file has tens; this only stops a runaway on garbage

# --- JPEG ------------------------------------------------------------------------
JPEG_SUFFIXES = {'.jpg', '.jpeg', '.jpe'}
# Markers carrying no length field
JPEG_STANDALONE = {0x01, 0xd8, 0xd9} | set(range(0xd0, 0xd8))
# Trailing data after End-of-Image is legitimate for these. Motion photos and MPO
# stereo pairs deliberately append a second payload, and flagging them would bury
# real findings under thousands of false positives.
JPEG_LEGIT_TRAILERS = (
    (b'\xff\xd8\xff', 'MPO / second JPEG image'),
    (b'ftyp', 'appended MP4 (motion photo)'),
    (b'MotionPhoto', 'Google motion photo marker'),
    (b'Android', 'Android appended metadata'),
    # Samsung Extended Format, appended by every Galaxy camera.
    (b'SEFH', 'Samsung Extended Format trailer'),
    (b'Image_UTC_Data', 'Samsung capture-time trailer'),
    # Motorola/Lenovo camera app settings block, e.g.
    # "<camera>appversion=8.18.8.0_230518,cameraid=3,modeid=AUTO_CAPTURE_MODE,..."
    (b'<camera>', 'Motorola camera settings trailer'),
)

# Together these two vendor trailers account for 3,950 archived photos. Omitting them
# made the first report 2,044 findings long with one real item in it, which is the
# failure mode that trains you to ignore the tool.
JPEG_TRAILER_SLACK = 64  # bytes of padding after EOI that are not worth reporting

# --- PNG -------------------------------------------------------------------------
PNG_MAGIC = b'\x89PNG\r\n\x1a\n'

# --- Foreign format signatures ---------------------------------------------------
# Deliberately specific. A bare MP3 frame sync (0xFFE) matches constantly inside
# compressed video payload and is useless on its own.
FOREIGN_SIGNATURES = (
    ('MP3 (LAME tag)', re.compile(rb'LAME[0-9]\.[0-9]{2}')),
    ('MP3 (ID3 tag)', re.compile(rb'ID3[\x02\x03\x04]\x00')),
    ('MP3 (Xing header)', re.compile(rb'Xing\x00\x00\x00')),
    ('JPEG', re.compile(rb'\xff\xd8\xff[\xe0\xe1\xdb]')),
    ('PNG', re.compile(rb'\x89PNG\r\n\x1a\n')),
    ('ZIP / Office document', re.compile(rb'PK\x03\x04\x14\x00')),
    ('PDF', re.compile(rb'%PDF-1\.')),
    ('ISO-BMFF (MP4/MOV)', re.compile(rb'ftyp(isom|mp42|qt  |M4V |avc1)')),
    ('RIFF (AVI/WAV)', re.compile(rb'RIFF....(AVI |WAVE)', re.DOTALL)),
)

MP3_FRAME_SYNC = re.compile(rb'\xff[\xfa\xfb\xf2\xf3]')

PROGRESS_INTERVAL = 100


def shannon_entropy(data):
    """
    Bits of entropy per byte, used to separate compressed payload from padding.

    Compressed media sits near 7.9; zero-fill or text sits far lower. This is how a
    foreign region gets described when no format signature matches it.
    """
    if not data:
        return 0.0

    counts = Counter(data)
    total = len(data)
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


def sync_ratio(data, stride, phase):
    """Fraction of expected TS sync positions in `data` that actually hold 0x47."""
    expected = 0
    hits = 0

    for index in range(phase, len(data), stride):
        expected += 1

        if data[index] == SYNC_BYTE:
            hits += 1

    if expected == 0:
        return 0.0

    return hits / expected


def best_ts_phase(data, stride):
    """
    Return (phase, ratio) for the phase that best explains `data` as a transport stream.

    Trying every phase is the whole trick: foreign TS data scores near 1.0 at some phase
    other than the host file's, which identifies it as another recording's blocks rather
    than noise.
    """
    best = (0, 0.0)
    sample = data[:stride * TS_HEAD_PACKETS]

    for phase in range(stride):
        ratio = sync_ratio(sample, stride, phase)

        if ratio > best[1]:
            best = (phase, ratio)

    return best


def classify_foreign(data):
    """
    Describe what a foreign byte region actually contains.

    Returns (verdict, evidence). Order matters: a positive TS phase match is the most
    specific answer available and is checked before falling back to entropy.
    """
    matches = []

    for label, pattern in FOREIGN_SIGNATURES:
        count = len(pattern.findall(data))

        if count:
            matches.append(f"{label} x{count}")

    # Another transport stream? Check the strides at every phase.
    #
    # The length guard matters: over a 98-byte buffer, range(phase, 98, 192) yields a
    # single position, so one chance 0x47 scores a perfect 1.000. That produced 20
    # confident "another transport stream" verdicts on scraps of Samsung metadata.
    for stride in TS_STRIDES:
        if len(data) < stride * 32:
            break

        phase, ratio = best_ts_phase(data, stride)

        if ratio > 0.90:
            evidence = f"TS grid at stride {stride} phase {phase}, sync {ratio:.3f}"

            if matches:
                evidence += f"; also {', '.join(matches)}"

            return 'another transport stream', evidence

    mp3_syncs = len(MP3_FRAME_SYNC.findall(data))
    entropy = shannon_entropy(data)

    if matches:
        return 'foreign format', f"{', '.join(matches)}; entropy {entropy:.2f}"

    if mp3_syncs > len(data) / 2000:
        return 'probable MP3 audio', f"{mp3_syncs} frame syncs, entropy {entropy:.2f}"

    if entropy > 7.5:
        return 'unidentified compressed data', f"entropy {entropy:.2f} bits/byte"

    if entropy < 1.0:
        return 'zero or constant fill', f"entropy {entropy:.2f} bits/byte"

    return 'unidentified data', f"entropy {entropy:.2f} bits/byte"


def locate_ts_splice(handle, phase, stride, search_from, search_to):
    """
    Return the byte offset where the packet grid breaks and does not recover.

    Walks the grid rather than scanning for absent sync bytes, so the result is the true
    end of valid video instead of the first chance mismatch. A run of RECOVERY_PACKETS
    misses is required, because a single corrupt packet inside otherwise-sound video is
    ordinary damage, not a splice.
    """
    handle.seek(search_from)
    data = handle.read(search_to - search_from)

    if not data:
        return None

    index = (phase - search_from) % stride
    limit = len(data) - stride * RECOVERY_PACKETS

    while index < limit:
        if data[index] != SYNC_BYTE:
            recovered = False

            for lookahead in range(1, RECOVERY_PACKETS):
                position = index + lookahead * stride

                if position < len(data) and data[position] == SYNC_BYTE:
                    recovered = True
                    break

            if not recovered:
                return search_from + index

        index += stride

    return None


def analyze_transport_stream(path, size, full_read):
    """
    Profile an MPEG-TS file's sync continuity and identify any foreign region.

    Returns a finding dict, or None when the file is structurally continuous.
    """
    with path.open('rb') as handle:
        head = handle.read(max(TS_STRIDES) * TS_HEAD_PACKETS)

        if len(head) < max(TS_STRIDES) * 8:
            return {'status': 'too small to profile', 'detail': f"{size} bytes"}

        chosen = None

        for stride in TS_STRIDES:
            phase, ratio = best_ts_phase(head, stride)

            if ratio >= TS_MIN_HEAD_RATIO:
                chosen = (stride, phase, ratio)
                break

        # No TS structure at the very start: the whole file is foreign content.
        if chosen is None:
            handle.seek(0)
            sample = handle.read(4 << 20)
            verdict, evidence = classify_foreign(sample)

            return {
                'status': 'entirely foreign',
                'detail': f"no TS structure anywhere at the start; content is {verdict}",
                'foreign_verdict': verdict,
                'evidence': evidence,
                'splice_offset': 0,
                'bytes_foreign': size,
                'fraction_foreign': 1.0,
            }

        stride, phase, head_ratio = chosen

        # Profile the WHOLE file rather than stopping at the first collapse. Damaged
        # files here carry several separate foreign regions with sound video between
        # them, and reporting only the first one then treating everything after it as
        # lost overstates a partly-recoverable file as a total loss.
        probe = WINDOW_BYTES if full_read else PROBE_BYTES

        # Each window is classified into one of three states, because collapsing them
        # into "good or foreign" gets the accounting wrong in both directions:
        #
        #   aligned    holds sync on this file's own grid -- continuous video
        #   shifted    holds sync at a DIFFERENT phase. Ambiguous by nature: either a
        #              donor file's blocks or this recording resuming after a gap,
        #              since resumed data has no reason to land back on the old grid.
        #   foreign    holds no TS structure at any phase -- definitely not video
        #
        # Only `foreign` supports a confident claim that footage is gone. Reporting
        # `shifted` as lost turned a 35%-recoverable file into "99.5% destroyed".
        classified = []
        position = 0

        while position < size:
            handle.seek(position)
            chunk = handle.read(probe)

            if len(chunk) < stride * 2:
                break

            if sync_ratio(chunk, stride, (phase - position) % stride) >= COLLAPSE_RATIO:
                classified.append((position, 'aligned', phase))
            else:
                # Only failing windows pay for the all-phase probe, which keeps a
                # healthy file's cost essentially unchanged.
                other_phase, other_ratio = best_ts_phase(chunk, stride)

                if other_ratio > 0.90:
                    classified.append((position, 'shifted', other_phase))
                else:
                    classified.append((position, 'foreign', None))

            position += WINDOW_BYTES

        if all(state == 'aligned' for _, state, _ in classified):
            return None

        # Group contiguous windows sharing a state
        regions = []

        for window_start, state, window_phase in classified:
            if state == 'aligned':
                continue

            if regions and regions[-1]['state'] == state and \
                    window_start == regions[-1]['end']:
                regions[-1]['end'] = min(window_start + WINDOW_BYTES, size)
            else:
                regions.append({
                    'state': state,
                    'start': window_start,
                    'end': min(window_start + WINDOW_BYTES, size),
                    'phase': window_phase,
                })

        # Refine the first region's start to the exact byte; that is the number worth
        # quoting, and refining every region multiplies reads for little gain.
        if regions:
            first_region = regions[0]
            exact = locate_ts_splice(
                handle, phase, stride,
                max(first_region['start'] - WINDOW_BYTES, 0),
                min(first_region['end'] + WINDOW_BYTES, size),
            )

            if exact is not None and first_region['start'] - WINDOW_BYTES <= exact:
                first_region['start'] = exact

        for region in regions:
            handle.seek(region['start'])
            sample = handle.read(min(4 << 20, size - region['start']))
            verdict, evidence = classify_foreign(sample)
            region['verdict'] = verdict
            region['evidence'] = evidence
            region['bytes'] = max(region['end'] - region['start'], 0)

    definitely_foreign = sum(r['bytes'] for r in regions if r['state'] == 'foreign')
    phase_shifted = sum(r['bytes'] for r in regions if r['state'] == 'shifted')
    first = regions[0]
    verdicts = sorted({r['verdict'] for r in regions})

    parts = [f"continuous transport stream to {first['start']:,} bytes "
             f"({100 * first['start'] / size:.1f}%)"]

    if definitely_foreign:
        parts.append(f"{definitely_foreign / 1e6:.1f} MB is not a transport stream "
                     f"at all ({', '.join(verdicts)})")

    if phase_shifted:
        parts.append(f"{phase_shifted / 1e6:.1f} MB is transport-stream data on a "
                     f"different packet grid (donor blocks, or this recording "
                     f"resuming after a gap)")

    return {
        'status': 'spliced',
        'detail': '; '.join(parts),
        'foreign_verdict': first['verdict'],
        'foreign_verdicts': verdicts,
        'evidence': f"host grid stride {stride} phase {phase}; {first['evidence']}",
        'splice_offset': first['start'],
        'regions': regions,
        'region_count': len(regions),
        'bytes_foreign': definitely_foreign,
        'bytes_phase_shifted': phase_shifted,
        'fraction_foreign': definitely_foreign / size,
        'fraction_discontinuous': (definitely_foreign + phase_shifted) / size,
        # Region ends are known only to WINDOW_BYTES, so totals are approximate.
        # True footage loss is measured by decoding, not by byte accounting.
        'foreign_bytes_approximate': not full_read,
    }


def analyze_isobmff(path, size):
    """
    Walk an MP4/MOV/HEIC top-level box chain, reporting where it stops making sense.

    Only box headers are read, so cost is a handful of seeks regardless of file size.
    A broken chain means the bytes stopped being this file partway through.
    """
    with path.open('rb') as handle:
        position = 0
        boxes = 0

        while position < size and boxes < MAX_BOXES:
            handle.seek(position)
            header = handle.read(8)

            if len(header) < 8:
                # Trailing bytes too short to be a box.
                if size - position > JPEG_TRAILER_SLACK:
                    return {
                        'status': 'trailing data',
                        'detail': f"{size - position} bytes after the last valid box",
                        'splice_offset': position,
                        'bytes_foreign': size - position,
                        'fraction_foreign': (size - position) / size,
                    }
                return None

            box_size = int.from_bytes(header[:4], 'big')
            box_type = header[4:8]

            if not BOX_TYPE_PATTERN.match(box_type):
                handle.seek(position)
                foreign = handle.read(4 << 20)
                verdict, evidence = classify_foreign(foreign)

                return {
                    'status': 'spliced',
                    'detail': (f"box chain breaks at {position:,} "
                               f"({100 * position / size:.1f}%): type "
                               f"{box_type!r} is not a box; content is {verdict}"),
                    'foreign_verdict': verdict,
                    'evidence': evidence,
                    'splice_offset': position,
                    'bytes_foreign': size - position,
                    'fraction_foreign': (size - position) / size,
                }

            if box_size == 0:
                # Extends to end of file: a legitimate terminator.
                return None

            if box_size == 1:
                extended = handle.read(8)

                if len(extended) < 8:
                    return None

                box_size = int.from_bytes(extended, 'big')

            if box_size < 8:
                return {
                    'status': 'spliced',
                    'detail': (f"box chain breaks at {position:,}: "
                               f"{box_type.decode('ascii', 'replace')} claims "
                               f"size {box_size}"),
                    'splice_offset': position,
                    'bytes_foreign': size - position,
                    'fraction_foreign': (size - position) / size,
                }

            if position + box_size > size:
                shortfall = position + box_size - size
                return {
                    'status': 'truncated',
                    'detail': (f"{box_type.decode('ascii', 'replace')} box at "
                               f"{position:,} runs {shortfall:,} bytes past end of file"),
                    'splice_offset': position,
                    'bytes_foreign': 0,
                    'fraction_foreign': 0.0,
                }

            position += box_size
            boxes += 1

    return None


def jpeg_logical_end(data):
    """
    Return the offset just past the JPEG's End-of-Image marker, or None if absent.

    Walks marker segments properly, including the entropy-coded scan after SOS where
    0xFF00 is a stuffed literal and 0xFFD0-D7 are restart markers rather than segment
    boundaries. A naive search for the last 0xFFD9 finds compressed data by chance.
    """
    if len(data) < 4 or data[0] != 0xff or data[1] != 0xd8:
        return None

    position = 2
    length = len(data)

    while position < length - 1:
        if data[position] != 0xff:
            position += 1
            continue

        marker = data[position + 1]

        if marker == 0xff:
            position += 1
            continue

        if marker == 0xd9:
            return position + 2

        if marker in JPEG_STANDALONE:
            position += 2
            continue

        if position + 4 > length:
            return None

        segment = int.from_bytes(data[position + 2:position + 4], 'big')

        if segment < 2:
            return None

        if marker == 0xda:
            # Start of Scan: skip the header, then hunt for the next real marker.
            position += 2 + segment

            while position < length - 1:
                if data[position] != 0xff:
                    position += 1
                    continue

                following = data[position + 1]

                # 0xFF00 is a stuffed literal, 0xFFD0-D7 are restart markers. Both
                # live inside the entropy-coded data and are not segment boundaries.
                if following == 0x00 or 0xd0 <= following <= 0xd7:
                    position += 2
                    continue

                # A run of 0xFF is legal fill before a marker, NOT a marker itself.
                # Breaking here derailed the walk on every file that uses restart
                # intervals: it exited the scan at the fill byte, then read compressed
                # bytes as markers and either ran off the end ("no end marker") or hit
                # a chance 0xFFD9 and reported a false early End-of-Image, inventing
                # hundreds of kilobytes of "trailing data" out of ordinary image data.
                if following == 0xff:
                    position += 1
                    continue

                break

            continue

        position += 2 + segment

    return None


def analyze_jpeg(path, size):
    """
    Report unexplained data after a JPEG's logical end.

    Motion photos and MPO stereo pairs append a legitimate second payload, so trailing
    data is only a finding when it matches none of the known-good trailer signatures.
    Without that allowance this check would flag thousands of healthy phone photos.
    """
    data = path.read_bytes()

    end = jpeg_logical_end(data)

    if end is None:
        return {
            'status': 'no end marker',
            'detail': 'no End-of-Image marker reachable by a marker walk',
            'splice_offset': None,
            'bytes_foreign': 0,
            'fraction_foreign': 0.0,
        }

    trailing = size - end

    if trailing <= JPEG_TRAILER_SLACK:
        return None

    tail = data[end:end + (4 << 20)]

    for signature, explanation in JPEG_LEGIT_TRAILERS:
        if signature in tail[:4096]:
            return None

    verdict, evidence = classify_foreign(tail)

    return {
        'status': 'trailing data',
        'detail': (f"{trailing:,} unexplained bytes after End-of-Image at {end:,} "
                   f"({100 * trailing / size:.1f}% of the file); content is {verdict}"),
        'foreign_verdict': verdict,
        'evidence': evidence,
        'splice_offset': end,
        'bytes_foreign': trailing,
        'fraction_foreign': trailing / size,
    }


def analyze_png(path, size):
    """
    Walk a PNG chunk chain to IEND and report anything after it.

    PNG carries explicit chunk lengths, so a broken chain is unambiguous.
    """
    with path.open('rb') as handle:
        if handle.read(8) != PNG_MAGIC:
            return {
                'status': 'entirely foreign',
                'detail': 'PNG magic bytes absent',
                'splice_offset': 0,
                'bytes_foreign': size,
                'fraction_foreign': 1.0,
            }

        position = 8
        chunks = 0

        while position < size and chunks < MAX_BOXES:
            handle.seek(position)
            header = handle.read(8)

            if len(header) < 8:
                return None

            chunk_length = int.from_bytes(header[:4], 'big')
            chunk_type = header[4:8]

            if not BOX_TYPE_PATTERN.match(chunk_type):
                return {
                    'status': 'spliced',
                    'detail': f"chunk chain breaks at {position:,}: {chunk_type!r}",
                    'splice_offset': position,
                    'bytes_foreign': size - position,
                    'fraction_foreign': (size - position) / size,
                }

            # 8-byte header + payload + 4-byte CRC
            position += 12 + chunk_length

            if chunk_type == b'IEND':
                trailing = size - position

                if trailing > JPEG_TRAILER_SLACK:
                    handle.seek(position)
                    verdict, evidence = classify_foreign(handle.read(4 << 20))

                    return {
                        'status': 'trailing data',
                        'detail': (f"{trailing:,} bytes after IEND; "
                                   f"content is {verdict}"),
                        'foreign_verdict': verdict,
                        'evidence': evidence,
                        'splice_offset': position,
                        'bytes_foreign': trailing,
                        'fraction_foreign': trailing / size,
                    }

                return None

            chunks += 1

    return None


def analyze_file(path, full_read=False):
    """
    Dispatch one file to the handler matching its container, returning a finding or None.

    Chosen by suffix rather than magic bytes on purpose: a .MTS holding MP3 data is
    precisely the finding wanted, and sniffing content would silently reclassify it as a
    healthy audio file.
    """
    try:
        size = path.stat().st_size
    except OSError as error:
        return {'status': 'unreadable', 'detail': str(error)}

    if size == 0:
        return {'status': 'empty', 'detail': '0 bytes'}

    suffix = path.suffix.lower()

    try:
        if suffix in {extension.lower() for extension in AVCHD_EXTENSIONS} | {'.ts', '.m2t'}:
            return analyze_transport_stream(path, size, full_read)

        if suffix in ISOBMFF_SUFFIXES:
            return analyze_isobmff(path, size)

        if suffix in JPEG_SUFFIXES:
            return analyze_jpeg(path, size)

        if suffix == '.png':
            return analyze_png(path, size)

    except OSError as error:
        return {'status': 'unreadable', 'detail': str(error)}

    return None


def collect_files(root):
    """Return every file under `root` whose container this tool can verify."""
    checkable = (
        {extension.lower() for extension in AVCHD_EXTENSIONS}
        | {extension.lower() for extension in VIDEO_EXTENSIONS}
        | {extension.lower() for extension in PHOTO_EXTENSIONS}
        | ISOBMFF_SUFFIXES | JPEG_SUFFIXES | {'.png', '.ts', '.m2t'}
    )

    found = []

    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.name.startswith('.'):
            continue

        if path.suffix.lower() in checkable:
            found.append(path)

    return found


def main():
    """Scan a tree for spliced-in foreign content and report what was found."""
    parser = argparse.ArgumentParser(
        description="Find media files containing data that belongs to other files")
    parser.add_argument('root', type=Path, help="Directory to scan")
    parser.add_argument('--output', type=Path, help="Write findings as JSON")
    parser.add_argument('--workers', type=int, default=6,
                        help="Concurrent readers (I/O bound; default 6)")
    parser.add_argument('--full', action='store_true',
                        help="Read transport streams entirely instead of sampling")

    args = parser.parse_args()

    if not args.root.is_dir():
        print(f"Not a directory: {args.root}")
        sys.exit(1)

    print(f"Scanning {args.root} for spliced foreign content")

    files = collect_files(args.root)
    print(f"  {len(files):,} verifiable files")

    if not args.full:
        print(f"  transport streams sampled at {PROBE_BYTES // 1024} KB per "
              f"{WINDOW_BYTES // (1 << 20)} MB — foreign regions under ~1 MB "
              f"will not be seen (use --full to read everything)")

    print(f"  {args.workers} workers\n")

    findings = []
    statuses = Counter()
    started = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(analyze_file, path, args.full): path
            for path in files
        }

        for position, future in enumerate(as_completed(futures), start=1):
            path = futures[future]

            try:
                finding = future.result()
            except Exception as error:  # a scan must never die on one bad file
                finding = {'status': 'scan error', 'detail': repr(error)}

            if finding is not None:
                finding['path'] = str(path)
                findings.append(finding)
                statuses[finding['status']] += 1
            else:
                statuses['ok'] += 1

            if position % PROGRESS_INTERVAL == 0:
                elapsed = time.time() - started
                rate = position / max(elapsed, 0.001)
                print(f"  {position:,}/{len(files):,} checked "
                      f"({rate:.1f}/s, {len(findings)} findings)", flush=True)

    elapsed = time.time() - started

    print()
    print("=" * 72)
    print("  SPLICE DETECTION REPORT")
    print("=" * 72)
    print(f"  scanned {len(files):,} files in {elapsed:.0f}s\n")

    for status, count in statuses.most_common():
        print(f"    {status:24s} {count:6,}")

    spliced = [f for f in findings if f['status'] in {'spliced', 'entirely foreign'}]

    if spliced:
        confident = sum(f.get('bytes_foreign', 0) for f in spliced)
        shifted = sum(f.get('bytes_phase_shifted', 0) for f in spliced)

        print(f"\n  {len(spliced)} file(s) contain content that is not their own")
        print(f"    {confident / 1e9:.2f} GB is definitely not video "
              f"(no container structure at any offset)")

        if shifted:
            print(f"    {shifted / 1e9:.2f} GB is video on a different packet grid "
                  f"— donor blocks or a resumed recording, not distinguishable here")

        print("\n  Byte totals are approximate. True footage loss is measured by "
              "decoding\n  (check_media_health.py --deep), not by byte accounting.\n")

        verdicts = Counter(f.get('foreign_verdict', 'unknown') for f in spliced)
        print("  Foreign content identified as:")

        for verdict, count in verdicts.most_common():
            print(f"    {verdict:32s} {count}")

        print("\n  Worst affected:")
        ordered = sorted(spliced,
                         key=lambda f: -f.get('fraction_discontinuous',
                                              f.get('fraction_foreign', 0)))

        for finding in ordered[:20]:
            path = Path(finding['path'])
            discontinuous = finding.get('fraction_discontinuous',
                                        finding.get('fraction_foreign', 0))
            print(f"    {100 * discontinuous:5.1f}% not its own content  "
                  f"{path.parent.name}/{path.name}")
            print(f"           {finding['detail'][:130]}")

    other = [f for f in findings if f['status'] not in {'spliced', 'entirely foreign'}]

    if other:
        print(f"\n  {len(other)} other structural finding(s):")

        for finding in other[:15]:
            path = Path(finding['path'])
            print(f"    [{finding['status']}] {path.parent.name}/{path.name}")
            print(f"           {finding['detail'][:110]}")

        if len(other) > 15:
            print(f"    ... and {len(other) - 15} more")

    if args.output:
        args.output.write_text(json.dumps(findings, indent=2))
        print(f"\n  findings written to {args.output}")

    if not findings:
        print("\n  No foreign content found. Every container is structurally continuous.")


if __name__ == '__main__':
    main()
