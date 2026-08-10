#!/usr/bin/env python3
"""
Verify that a video conversion batch did not degrade the archive.

"ffmpeg exited zero" is not evidence. It exits zero on a file it decoded halfway before
hitting an unrecoverable error, producing a short but structurally valid output — which
is exactly what happened to five AVCHD sources whose damage was only found later, by
comparing durations.

Two tiers, because the cheap check catches a different failure than the expensive one:

TIER 1, every pair — parity against the source: duration, resolution, frame count,
    surviving audio, and whether the output probes at all. A silent truncation shows up
    here as a short duration, and this is fast enough to run on every conversion.

TIER 2, a stratified sample — the actual fidelity question, measured with ffmpeg's SSIM
    and PSNR filters. Sampled evenly across the encoder's own size range rather than at
    random, because degradation concentrates in the busiest footage and a random sample
    is mostly short simple clips.

The source-to-output mapping comes from the conversion index, which recorded it at
conversion time. Nothing is inferred from filenames — a converted file shares no bytes
and usually no name with its source.

Read-only. Never modifies sources or the archive.

Usage:
    python3 verify_conversions.py
    python3 verify_conversions.py --source-filter /Volumes/home-movies/
    python3 verify_conversions.py --parity-only
    python3 verify_conversions.py --sample 24 --output verification.json
"""

import argparse
import json
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from analyze_video_quality import calculate_psnr, calculate_ssim
from conversion_index import load_index

VIDEO_ROOT = REPO / 'Organized_Videos'

# Container duration can legitimately shift by a frame or two across a re-mux, but not
# by a second — that would mean lost footage.
DURATION_TOLERANCE_S = 0.5
FRAME_TOLERANCE = 2

# Bands matching the project's documented interpretation. The 0.92 floor comes from a
# by-eye review: artifacts became visible around 0.965 and objectionable below 0.96,
# and the worst real case at 0.9282 was judged not worth caring about.
SSIM_IMPERCEPTIBLE = 0.98
SSIM_NEARLY_INDISTINGUISHABLE = 0.95
SSIM_MINOR_VISIBLE = 0.90
SSIM_KEEPER_FLOOR = 0.92

PARITY_WORKERS = 8
SAMPLE_SIZE = 16


def metric_value(result):
    """
    Pull the scalar out of an analyze_video_quality result.

    The two functions disagree on their key: calculate_ssim returns {'all': ...} while
    calculate_psnr returns {'average': ...}. Reading 'all' for both looks like it works,
    because SSIM answers and PSNR silently comes back None — which is precisely the bug
    that made an earlier verification report "PSNR unavailable" against a healthy tool.
    """
    if isinstance(result, (int, float)):
        return result

    if not isinstance(result, dict):
        return None

    for key in ('all', 'average', 'mean'):
        value = result.get(key)

        if isinstance(value, (int, float)):
            return value

    return None


def probe(path):
    """
    Return duration, dimensions, frame count and audio presence for one file.

    nb_frames is unreliable on some containers, so a missing value is reported as None
    rather than guessed at, and the caller treats it as "cannot compare" instead of
    inventing a mismatch.
    """
    command = [
        'ffprobe', '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,nb_frames,duration',
        '-show_entries', 'format=duration',
        '-of', 'json', str(path),
    ]

    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   check=False, timeout=120)
        data = json.loads(completed.stdout or '{}')
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None

    streams = data.get('streams') or []

    if not streams:
        return None

    stream = streams[0]

    def number(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    duration = (number(data.get('format', {}).get('duration'))
                or number(stream.get('duration')))

    try:
        audio = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries',
             'stream=codec_type', '-of', 'csv=p=0', str(path)],
            capture_output=True, text=True, check=False, timeout=60
        ).stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        audio = ''

    return {
        'duration': duration,
        'width': stream.get('width'),
        'height': stream.get('height'),
        'frames': number(stream.get('nb_frames')),
        'has_audio': bool(audio),
    }


def check_parity(source, output):
    """
    Compare an output against its source on everything cheap.

    Returns (verdict, detail). A missing source is reported distinctly from a bad
    output, because an unmounted share is an operator problem rather than a data one.
    """
    if not source.exists():
        return 'source missing', 'cannot verify — source unreachable'

    if not output.exists():
        return 'OUTPUT MISSING', str(output)

    source_info = probe(source)
    output_info = probe(output)

    if source_info is None:
        return 'source unprobeable', 'source will not probe (may itself be damaged)'

    if output_info is None:
        return 'OUTPUT UNPROBEABLE', 'output will not probe — the encode is broken'

    problems = []

    if source_info['duration'] and output_info['duration']:
        delta = abs(source_info['duration'] - output_info['duration'])

        if delta > DURATION_TOLERANCE_S:
            problems.append(
                f"duration {source_info['duration']:.2f}s -> "
                f"{output_info['duration']:.2f}s (off by {delta:.2f}s)"
            )

    if (source_info['width'], source_info['height']) != \
            (output_info['width'], output_info['height']):
        problems.append(
            f"resolution {source_info['width']}x{source_info['height']} -> "
            f"{output_info['width']}x{output_info['height']}"
        )

    if source_info['frames'] and output_info['frames']:
        frame_delta = abs(source_info['frames'] - output_info['frames'])

        if frame_delta > FRAME_TOLERANCE:
            problems.append(
                f"frames {source_info['frames']:.0f} -> {output_info['frames']:.0f}")

    if source_info['has_audio'] and not output_info['has_audio']:
        problems.append('audio stream lost')

    if problems:
        return 'MISMATCH', '; '.join(problems)

    return 'ok', ''


def resolve_output(relative, filename_index):
    """
    Find an archived output, tolerating a move since the conversion was recorded.

    `create_event_folders.py` relocates files into named event subfolders after import,
    which leaves the conversion index pointing at a path that no longer exists. Twelve
    of 646 home-movies conversions had moved into folders like "Home Walkthroughs", and
    reporting those as missing outputs every run would make the whole report ignorable.

    Falls back to the filename, which is safe here because conversion output names carry
    a second-resolution timestamp and are unique across the archive.

    Args:
        relative:       Output path as recorded, relative to Organized_Videos
        filename_index: {filename: [paths]} built once over the archive

    Returns:
        tuple (Path, bool moved) — the resolved path and whether it had to be searched
    """
    direct = VIDEO_ROOT / relative

    if direct.exists():
        return direct, False

    candidates = filename_index.get(Path(relative).name, [])

    if len(candidates) == 1:
        return candidates[0], True

    # Ambiguous or absent: report the indexed location so the failure is honest
    return direct, False


def build_filename_index():
    """Map every archived video filename to where it actually is now."""
    index = {}

    if not VIDEO_ROOT.is_dir():
        return index

    for path in VIDEO_ROOT.rglob('*'):
        if path.is_file() and not path.name.startswith('.'):
            index.setdefault(path.name, []).append(path)

    return index


def load_pairs(source_filter=None):
    """
    Return (source, output, original_size) for everything in the conversion index.

    Args:
        source_filter: Only include sources containing this substring, e.g.
                       '/Volumes/home-movies/' to verify one batch
    """
    index = load_index()
    entries = None

    for key in ('entries', 'conversions'):
        if isinstance(index.get(key), dict):
            entries = index[key]
            break

    if entries is None:
        entries = {k: v for k, v in index.items() if isinstance(v, dict)}

    filename_index = build_filename_index()
    pairs = []
    moved = 0

    for value in entries.values():
        original = value.get('original_path')
        output = value.get('output_path')

        if not original or not output:
            continue

        if source_filter and source_filter not in original:
            continue

        resolved, was_moved = resolve_output(output, filename_index)
        moved += was_moved
        pairs.append((Path(original), resolved, value.get('original_size', 0)))

    if moved:
        print(f"  {moved} output(s) found in event subfolders rather than the "
              f"location the index recorded")

    return pairs


def run_parity(pairs):
    """Run tier 1 across every pair and report the verdict spread."""
    print("TIER 1 — duration, resolution, frame count, audio, decodability")
    print(f"  checking all {len(pairs)} pairs with {PARITY_WORKERS} workers...\n")

    verdicts = Counter()
    failures = []

    with ThreadPoolExecutor(max_workers=PARITY_WORKERS) as executor:
        futures = {
            executor.submit(check_parity, source, output): (source, output)
            for source, output, _ in pairs
        }

        for position, future in enumerate(as_completed(futures), start=1):
            source, output = futures[future]
            verdict, detail = future.result()
            verdicts[verdict] += 1

            if verdict != 'ok':
                failures.append((source, output, verdict, detail))

            if position % 100 == 0:
                print(f"  {position}/{len(pairs)}...", flush=True)

    print()

    for verdict, count in verdicts.most_common():
        print(f"  {verdict:22s} {count:5d}")

    if failures:
        print(f"\n  {len(failures)} pair(s) need attention:\n")

        for source, output, verdict, detail in failures[:25]:
            print(f"    [{verdict}] {source.name}")
            print(f"        {detail[:110]}")

        if len(failures) > 25:
            print(f"    ... and {len(failures) - 25} more")

    return verdicts, failures


def run_fidelity(pairs, sample_size):
    """Run tier 2 on a stratified sample and report the SSIM/PSNR spread."""
    ordered = sorted((p for p in pairs if p[0].exists() and p[1].exists()),
                     key=lambda p: p[2])

    if not ordered:
        print("\nNo verifiable pairs for fidelity measurement.")
        return []

    step = max(len(ordered) // sample_size, 1)
    sample = ordered[::step][:sample_size]

    print()
    print("TIER 2 — SSIM and PSNR against the source")
    print(f"  {len(sample)} files, sampled evenly across the size range")
    print(f"  (SSIM: >{SSIM_IMPERCEPTIBLE} imperceptible, "
          f">{SSIM_NEARLY_INDISTINGUISHABLE} nearly indistinguishable, "
          f"{SSIM_KEEPER_FLOOR} archive floor)\n")

    print(f"  {'source MB':>9} {'out MB':>7} {'ratio':>6} {'SSIM':>7} {'PSNR dB':>8}  file")

    measurements = []

    for source, output, size in sample:
        ssim = metric_value(calculate_ssim(source, output))
        psnr = metric_value(calculate_psnr(source, output))

        out_size = output.stat().st_size
        ssim_text = f"{ssim:.4f}" if ssim is not None else "n/a"
        psnr_text = f"{psnr:.2f}" if psnr is not None else "n/a"

        print(f"  {size / 1e6:9.1f} {out_size / 1e6:7.1f} "
              f"{out_size / max(size, 1):6.2f} {ssim_text:>7} {psnr_text:>8}  "
              f"{source.parent.name}/{source.name}", flush=True)

        measurements.append({
            'source': str(source), 'output': str(output),
            'ssim': ssim, 'psnr': psnr,
            'source_bytes': size, 'output_bytes': out_size,
        })

    ssim_values = sorted(m['ssim'] for m in measurements if m['ssim'] is not None)
    psnr_values = sorted(m['psnr'] for m in measurements if m['psnr'] is not None)

    print()
    print("=" * 70)
    print("  FIDELITY VERDICT")
    print("=" * 70)

    if ssim_values:
        print(f"  SSIM  n={len(ssim_values)}  worst={ssim_values[0]:.4f}  "
              f"median={ssim_values[len(ssim_values) // 2]:.4f}  "
              f"best={ssim_values[-1]:.4f}")

        bands = Counter()

        for value in ssim_values:
            if value >= SSIM_IMPERCEPTIBLE:
                bands['imperceptible (>=0.98)'] += 1
            elif value >= SSIM_NEARLY_INDISTINGUISHABLE:
                bands['nearly indistinguishable (0.95-0.98)'] += 1
            elif value >= SSIM_MINOR_VISIBLE:
                bands['minor visible differences (0.90-0.95)'] += 1
            else:
                bands['NOTICEABLE (<0.90)'] += 1

        for band, count in bands.most_common():
            print(f"    {band:40s} {count}")

        below = [v for v in ssim_values if v < SSIM_KEEPER_FLOOR]

        if below:
            print(f"\n  {len(below)} sample(s) fall below the {SSIM_KEEPER_FLOOR} "
                  f"archive floor — worst {below[0]:.4f}")
    else:
        print("  SSIM unavailable")

    if psnr_values:
        print(f"\n  PSNR  n={len(psnr_values)}  worst={psnr_values[0]:.2f} dB  "
              f"median={psnr_values[len(psnr_values) // 2]:.2f} dB")
        print("    (above 40 dB is generally considered excellent for lossy video)")
    else:
        print("\n  PSNR unavailable")

    return measurements


def main():
    """Verify a conversion batch on both tiers."""
    parser = argparse.ArgumentParser(
        description="Verify a video conversion batch did not degrade the archive")
    parser.add_argument('--sample', type=int, default=SAMPLE_SIZE,
                        help="How many files to measure with SSIM/PSNR (default 16)")
    parser.add_argument('--parity-only', action='store_true',
                        help="Skip the expensive fidelity tier")
    parser.add_argument('--source-filter',
                        help="Only verify sources whose path contains this substring, "
                             "e.g. /Volumes/home-movies/ for one batch")
    parser.add_argument('--output', type=Path, help="Write results as JSON")

    args = parser.parse_args()

    pairs = load_pairs(args.source_filter)

    label = f" matching {args.source_filter}" if args.source_filter else ""
    print(f"Conversions in the index{label}: {len(pairs)}\n")

    if not pairs:
        print("Nothing to verify.")
        sys.exit(1)

    verdicts, failures = run_parity(pairs)

    measurements = []

    if not args.parity_only:
        measurements = run_fidelity(pairs, args.sample)

    if args.output:
        args.output.write_text(json.dumps({
            'pairs': len(pairs),
            'parity': dict(verdicts),
            'failures': [
                {'source': str(s), 'output': str(o), 'verdict': v, 'detail': d}
                for s, o, v, d in failures
            ],
            'fidelity': measurements,
        }, indent=2))
        print(f"\n  results written to {args.output}")

    if verdicts.get('MISMATCH') or verdicts.get('OUTPUT MISSING') \
            or verdicts.get('OUTPUT UNPROBEABLE'):
        sys.exit(1)


if __name__ == '__main__':
    main()
