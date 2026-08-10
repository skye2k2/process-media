#!/usr/bin/env python3
"""
Turn detect_splices.py findings into decisions: when did this happen, and what got in?

The detector answers "which files hold data belonging to other files". That alone does
not tell you what to do. Two further questions decide everything:

WHEN     Clustering by year separates a bounded historical event from ongoing rot, and
         the answer changes whether the storage is still trustworthy. On the home-movies
         share the split was stark: 43.5% of 2009 and 34.3% of 2010 affected, and 0.0%
         of every year from 2011 onward across 1,235 files. That is damage inherited
         from a specific era, not a failing pool.

WHAT GOT IN  Whether a damaged source reached the archive decides between "the archive
         is contaminated" and "the archive is merely incomplete" — very different
         problems. This is knowable exactly rather than by heuristic, because the
         conversion index recorded which source produced which archived file.

Also lists the sources holding no footage of their own. Those are not damaged, they are
absent: no transcode recovers them and their reported durations are fiction.

Read-only.

Usage:
    python3 attribute_splices.py --findings splices.json
    python3 attribute_splices.py --findings splices.json --source-root /Volumes/home-movies
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

try:
    from conversion_index import load_index
    CONVERSION_INDEX_AVAILABLE = True
except ImportError:
    CONVERSION_INDEX_AVAILABLE = False

FOREIGN_STATUSES = {'spliced', 'entirely foreign'}

# Above this share of a year's files, the year is called out. Chosen to make a real
# cluster obvious without flagging a single bad file in a thin year.
CLUSTER_RATE = 0.10


def year_of(path_text):
    """Extract a four-digit year folder from a path, or 'unfoldered'."""
    for part in Path(path_text).parts:
        if len(part) == 4 and part.isdigit() and part.startswith(('19', '20')):
            return part

    return 'unfoldered'


def load_archive_map():
    """
    Return {source_path: archived_output} from the conversion index.

    Empty when the index is unavailable, in which case the archive-impact section is
    skipped rather than guessed at — a converted file shares no bytes and usually no
    name with its source, so there is nothing to fall back on.
    """
    if not CONVERSION_INDEX_AVAILABLE:
        return {}

    try:
        index = load_index()
    except Exception:
        return {}

    entries = index.get('entries') or index.get('conversions') or {}

    return {
        value['original_path']: value['output_path']
        for value in entries.values()
        if isinstance(value, dict)
        and value.get('original_path') and value.get('output_path')
    }


def report_statuses(findings):
    """Print the status spread and return the subset holding foreign content."""
    print("=" * 76)
    print("  FINDINGS")
    print("=" * 76)

    if not findings:
        print("  no findings — every container is structurally continuous\n")
        return []

    for status, count in Counter(f['status'] for f in findings).most_common():
        print(f"    {status:24s} {count:6,}")

    foreign = [f for f in findings if f['status'] in FOREIGN_STATUSES]
    total_bytes = sum(f.get('bytes_foreign', 0) or 0 for f in foreign)

    print(f"\n  {len(foreign)} file(s) hold content that is not their own")

    if total_bytes:
        print(f"  {total_bytes / 1e9:.2f} GB is definitely not the media it claims to be")

    print()
    return foreign


def report_clustering(foreign, source_root):
    """
    Print the per-year rate, which is what separates an event from ongoing rot.

    The denominator comes from the filesystem rather than the findings, because clean
    files produce no finding and a rate needs to know how many were checked.
    """
    print("=" * 76)
    print("  CLUSTERING BY YEAR — one event, or ongoing rot?")
    print("=" * 76)

    checked = Counter()

    if source_root and Path(source_root).is_dir():
        for path in Path(source_root).rglob('*'):
            if path.is_file() and not path.name.startswith('.'):
                checked[year_of(str(path))] += 1
    else:
        print("\n  (no --source-root given; showing affected counts without rates)")

    affected = defaultdict(int)

    for finding in foreign:
        affected[year_of(finding['path'])] += 1

    print(f"\n  {'year':12s} {'files':>8s} {'affected':>9s} {'rate':>8s}")

    for year in sorted(set(checked) | set(affected)):
        total = checked.get(year, 0)
        bad = affected.get(year, 0)

        if total == 0 and bad == 0:
            continue

        rate = f"{100 * bad / total:.1f}%" if total else "n/a"
        marker = '  <<<' if total and (bad / total) > CLUSTER_RATE else ''
        print(f"  {year:12s} {total:8,} {bad:9,} {rate:>8s}{marker}")

    print()


def report_archive_impact(foreign, archive_map):
    """Print whether damaged sources reached the archive, and which are total losses."""
    print("=" * 76)
    print("  ARCHIVE IMPACT")
    print("=" * 76)

    if not archive_map:
        print("\n  conversion index unavailable — cannot determine what was imported\n")
        return

    converted = [(f, archive_map[f['path']]) for f in foreign
                 if f['path'] in archive_map]
    held_back = [f for f in foreign if f['path'] not in archive_map]

    print(f"\n  held back, never converted : {len(held_back)}")
    print(f"  converted into the archive : {len(converted)}")

    if converted:
        print("\n  Converted despite holding foreign content:\n")

        for finding, output in sorted(converted, key=lambda pair: pair[0]['path']):
            source = Path(finding['path'])
            print(f"    {source.parent.name}/{source.name}  [{finding['status']}]")
            print(f"      {finding.get('detail', '')[:110]}")
            print(f"      -> {output}")

    entirely = [f for f in foreign if f['status'] == 'entirely foreign']

    if entirely:
        print(f"\n  {len(entirely)} source(s) hold no footage of their own. These are not")
        print("  damaged, they are absent — no transcode recovers them and their")
        print("  reported durations are fiction:\n")

        rows = []

        for finding in entirely:
            source = Path(finding['path'])
            size = 0

            try:
                size = source.stat().st_size
            except OSError:
                pass

            rows.append((size, source, finding.get('foreign_verdict', '')))

        for size, source, verdict in sorted(rows, reverse=True):
            print(f"    {size / 1e6:8.1f} MB  {source.parent.name}/{source.name:16s} "
                  f"{verdict}")

    print()


def main():
    """Attribute a set of splice findings by year and by archive impact."""
    parser = argparse.ArgumentParser(
        description="Attribute detect_splices.py findings by era and archive impact")
    parser.add_argument('--findings', type=Path, required=True,
                        help="JSON output from detect_splices.py")
    parser.add_argument('--source-root', type=Path,
                        help="Tree the findings came from, used as the rate denominator")

    args = parser.parse_args()

    if not args.findings.exists():
        print(f"No such findings file: {args.findings}")
        sys.exit(1)

    try:
        findings = json.loads(args.findings.read_text())
    except json.JSONDecodeError as error:
        print(f"Could not parse {args.findings}: {error}")
        sys.exit(1)

    foreign = report_statuses(findings)

    if not foreign:
        return

    report_clustering(foreign, args.source_root)
    report_archive_impact(foreign, load_archive_map())


if __name__ == '__main__':
    main()
