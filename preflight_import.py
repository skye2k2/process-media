#!/usr/bin/env python3
"""
Predict exactly what an import would do, before it does it.

`--dry-run` on the organizer answers "where does each file go". It does not answer the
questions that actually break an archive: is this content already here under a different
name, will two files land on the same path, is this date trustworthy, and is this file
even the kind of thing the destination expects.

Written after the rescued home-movie files were examined by hand and every one of them
turned out to be a problem:

    dates    all 29 carry no creation metadata, so the mtime fallback dates 2009 and
             2010 recordings to the day they were rescued -- one folder, wrong by 17 years
    routing  recovered MP3s are not videos, so is_video_file() sends 5.8 hours of audio
             into Organized_Photos
    content  the duplicate detector clears all of them ("no date pattern in filename, and
             no identical content in archive") because a re-encode shares no bytes with
             the archived copy of the same footage

That last one is the dangerous case, and no heuristic finds it. It is only knowable from
provenance: the conversion index records which source produced which archived file, and
the rescue manifest records which source produced which rescued file. Join them and the
redundancy is exact rather than guessed.

Every prediction calls the organizer's own functions rather than reimplementing them, so
this cannot drift from what an import would really do.

Read-only. Touches nothing.

Usage:
    python3 preflight_import.py _RESCUED
    python3 preflight_import.py _RESCUED --manifest _RESCUED/rescue_manifest.json
    python3 preflight_import.py TO_PROCESS/some_folder
"""

import argparse
import json
import sys
from datetime import datetime
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

import organize_archive
from duplicate_detector import DuplicateDetector

try:
    from conversion_index import load_index
    CONVERSION_INDEX_AVAILABLE = True
except ImportError:
    CONVERSION_INDEX_AVAILABLE = False

PHOTO_ROOT = REPO / 'Organized_Photos'
VIDEO_ROOT = REPO / 'Organized_Videos'

# Extensions the archive has no home for. Neither organizer branch is right, so they
# would be filed by whichever one wins by default rather than by intent.
AUDIO_SUFFIXES = {'.mp3', '.m4a', '.aac', '.wav', '.flac', '.ogg'}

# A date resolved this way is a guess about when the file was written, not when the
# content was captured, and for anything re-encoded it is simply the encode date.
UNTRUSTWORTHY_DATE_SOURCES = {'file_mtime'}

# An mtime younger than this is the processing date, not a capture date
RECENT_MTIME_DAYS = 30

SEVERITY_ORDER = ['BLOCKER', 'WARNING', 'NOTE']


def load_provenance(manifest_path):
    """
    Map each rescued output back to the archived file made from the same source.

    Returns {output_path_string: (source, archived_relative_path)}. Empty when either
    the manifest or the conversion index is unavailable, in which case the redundancy
    check simply does not run rather than guessing.
    """
    if not manifest_path or not Path(manifest_path).exists():
        return {}

    if not CONVERSION_INDEX_AVAILABLE:
        return {}

    try:
        manifest = json.loads(Path(manifest_path).read_text())
        index = load_index()
    except (json.JSONDecodeError, OSError):
        return {}

    entries = index.get('entries') or index.get('conversions') or {}
    source_to_archive = {
        value['original_path']: value['output_path']
        for value in entries.values()
        if isinstance(value, dict)
        and value.get('original_path') and value.get('output_path')
    }

    provenance = {}

    for record in manifest:
        source = record.get('source')

        if not source:
            continue

        outputs = record.get('carved') or []

        if record.get('output'):
            outputs = list(outputs) + [record['output']]

        archived = source_to_archive.get(source)

        for output in outputs:
            provenance[Path(output).name] = (source, archived)

    return provenance


def predict(path, detector, provenance):
    """
    Work out what would happen to one file, using the organizer's real logic.

    Returns a dict of the prediction plus a list of (severity, message) issues.
    """
    issues = []

    date, date_source = organize_archive.get_creation_date(path)
    is_video = organize_archive.is_video_file(path)

    if date is None:
        issues.append(('BLOCKER', 'no date could be resolved at all'))
        destination = None
        filename = path.name
    else:
        destination = organize_archive.get_destination_folder(date, is_video)
        filename = organize_archive.compute_destination_filename(path)

    if date_source in UNTRUSTWORTHY_DATE_SOURCES and date is not None:
        # An mtime close to now is not a date at all -- it is when the file was written,
        # which for a rescue or a re-encode means today. An older mtime is weak evidence
        # but usually roughly right, and calling it a blocker teaches you to ignore the
        # blockers that matter.
        age_days = (datetime.now() - date).days

        if age_days <= RECENT_MTIME_DAYS:
            issues.append(('BLOCKER',
                           f"date comes from {date_source} and is only {age_days} day(s) "
                           f"old ({date:%Y-%m-%d}) — that is the processing date, not a "
                           f"capture date"))
        else:
            issues.append(('WARNING',
                           f"date comes from {date_source} ({date:%Y-%m-%d}); plausible "
                           f"but not authoritative, since no capture metadata survives"))

    if path.suffix.lower() in AUDIO_SUFFIXES:
        target = 'Organized_Videos' if is_video else 'Organized_Photos'
        issues.append(('BLOCKER',
                       f"audio file would be filed into {target}; the archive has no "
                       f"audio destination"))

    source, archived = provenance.get(path.name, (None, None))

    if archived:
        issues.append(('BLOCKER',
                       f"content is already archived as {archived}, produced from the "
                       f"same source ({Path(source).name})"))

    result = detector.find_duplicate(path)

    if getattr(result, 'is_duplicate', False):
        issues.append(('NOTE',
                       f"duplicate detector matched {getattr(result, 'existing_path', '?')}"))
    elif archived:
        issues.append(('WARNING',
                       'duplicate detector does NOT catch this — a re-encode shares no '
                       'bytes with the archived copy'))

    return {
        'path': path,
        'date': date,
        'date_source': date_source,
        'is_video': is_video,
        'destination': destination,
        'filename': filename,
        'full_destination': (destination / filename) if destination else None,
        'provenance_source': source,
        'archived_counterpart': archived,
        'issues': issues,
    }


def find_sibling_redundancy(predictions):
    """
    Flag several outputs rescued from one source, which are often the same footage twice.

    A rescue can extract the same region two ways -- a whole-file decode and a carve of
    the same bytes -- producing outputs that look independent but hold identical footage.
    00050 yielded a direct extraction of 2,065 frames alongside two carved files holding
    2,007 between them, and importing all three would have filed one clip as three.

    A warning rather than a blocker, because siblings are sometimes genuinely different:
    00006's carve is its only output, since direct extraction produced nothing at all.
    """
    by_source = defaultdict(list)

    for prediction in predictions:
        source = prediction.get('provenance_source')

        if source and prediction['path'].suffix.lower() not in AUDIO_SUFFIXES:
            by_source[source].append(prediction)

    for source, group in by_source.items():
        if len(group) < 2:
            continue

        names = ', '.join(sorted(p['path'].name for p in group))

        for prediction in group:
            prediction['issues'].append(
                ('WARNING',
                 f"{len(group)} outputs rescued from {Path(source).name} ({names}); "
                 f"confirm these are different footage rather than one region extracted "
                 f"two ways, or the same clip is filed several times"))


def find_collisions(predictions):
    """
    Report destination paths claimed by more than one input, or already occupied.

    The organizer resolves collisions by appending _1, _2, which succeeds silently --
    so two versions of the same recording end up side by side looking like two takes.
    """
    by_destination = defaultdict(list)

    for prediction in predictions:
        if prediction['full_destination']:
            by_destination[prediction['full_destination']].append(prediction)

    internal = {dest: group for dest, group in by_destination.items() if len(group) > 1}
    existing = {dest: group for dest, group in by_destination.items() if dest.exists()}

    return internal, existing


def main():
    """Predict and report the outcome of importing a directory."""
    parser = argparse.ArgumentParser(
        description="Predict what an import would do, without doing it")
    parser.add_argument('source', type=Path, help="Directory that would be imported")
    parser.add_argument('--manifest', type=Path,
                        help="Rescue manifest, enabling the provenance redundancy check")
    parser.add_argument('--verbose', action='store_true',
                        help="Show every file, not just ones with issues")

    args = parser.parse_args()

    if not args.source.is_dir():
        print(f"Not a directory: {args.source}")
        sys.exit(2)

    manifest = args.manifest

    if manifest is None:
        candidate = args.source / 'rescue_manifest.json'

        if candidate.exists():
            manifest = candidate

    provenance = load_provenance(manifest)

    files = sorted(path for path in args.source.rglob('*')
                   if path.is_file() and not path.name.startswith('.')
                   and path.suffix.lower() != '.json')

    print(f"Preflight for {args.source}")
    print(f"  {len(files)} file(s)")

    if provenance:
        print(f"  provenance available for {len(provenance)} of them "
              f"(via {manifest})")
    else:
        print("  no provenance available — the already-archived check will not run")

    print()

    detector = DuplicateDetector(PHOTO_ROOT, VIDEO_ROOT)
    predictions = [predict(path, detector, provenance) for path in files]

    find_sibling_redundancy(predictions)
    internal, existing = find_collisions(predictions)

    for destination, group in internal.items():
        for prediction in group:
            prediction['issues'].append(
                ('BLOCKER', f"{len(group)} files claim this same destination; the "
                            f"organizer would silently append _1, _2"))

    for destination, group in existing.items():
        for prediction in group:
            prediction['issues'].append(
                ('BLOCKER', f"destination already exists: {destination.name}"))

    # ---- Report ----
    counts = Counter()
    folders = Counter()

    for prediction in predictions:
        worst = None

        for severity, _ in prediction['issues']:
            if worst is None or SEVERITY_ORDER.index(severity) < SEVERITY_ORDER.index(worst):
                worst = severity

        counts[worst or 'ok'] += 1

        if prediction['destination']:
            folders[str(prediction['destination'].relative_to(REPO))] += 1

    print("=" * 76)
    print("  PREDICTED DESTINATIONS")
    print("=" * 76)

    for folder, count in folders.most_common(12):
        print(f"    {count:4d}  {folder}")

    print()
    print("=" * 76)
    print("  VERDICT")
    print("=" * 76)

    for severity in SEVERITY_ORDER + ['ok']:
        if counts.get(severity):
            print(f"    {severity:10s} {counts[severity]:4d} file(s)")

    problems = [p for p in predictions if p['issues']]

    if problems:
        print(f"\n  {len(problems)} file(s) with issues:\n")

        for prediction in problems if args.verbose else problems[:25]:
            path = prediction['path']
            print(f"    {path.relative_to(args.source)}")

            if prediction['full_destination']:
                print(f"        would become: "
                      f"{prediction['full_destination'].relative_to(REPO)}")

            for severity, message in prediction['issues']:
                print(f"        [{severity}] {message}")

            print()

        if not args.verbose and len(problems) > 25:
            print(f"    ... and {len(problems) - 25} more (use --verbose)")

    if args.verbose:
        clean = [p for p in predictions if not p['issues']]

        if clean:
            print(f"  {len(clean)} file(s) would import cleanly:\n")

            for prediction in clean:
                print(f"    {prediction['path'].name} -> "
                      f"{prediction['full_destination'].relative_to(REPO)}")

    blockers = counts.get('BLOCKER', 0)

    print()

    if blockers:
        print(f"  DO NOT IMPORT. {blockers} file(s) would be filed wrongly, land "
              f"somewhere the archive\n  has no home for, or duplicate content already "
              f"present under a different name.")
        sys.exit(1)

    print("  No blockers found.")


if __name__ == '__main__':
    main()
