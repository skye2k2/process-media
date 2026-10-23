#!/usr/bin/env python3
"""
One-off repair: restore real dates to backdated scans that lost them to dedupe.

Google's year view duplicated every "Photos from YYYY" (YYYY < 2013) album file
into the 2013/2014 albums with scan-date sidecars. The router moved those twins
first (circa/holding), and organize_media's name-based dedupe then deleted the
backdated originals — so the surviving copies carry estimated or scan dates
even though real dates existed. The pre-routing backup snapshot preserves every
original sidecar; this script reads the real dates from there and re-places the
survivors into their true YYYY/MM folders with corrected EXIF.

Usage: .venv/bin/python .TMP_restore_backdated_dates.py [--live]
"""

import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from media_utils import MEDIA_EXTENSIONS, MONTH_NAMES, parse_json_metadata

SCRIPT_DIR = Path(__file__).parent
PHOTOS = SCRIPT_DIR / "Organized_Photos"
SNAPSHOT_TAKEOUT = Path(
    "/Volumes/MEDIA_BACKUP/process-media/snapshots/2026-10-22-0743/"
    "TO_PROCESS/thebergmannfamily google takeout")
ALBUM_PATTERN = re.compile(r"^Photos from (\d{4})$")
SCAN_ERA_START = 2013
SIDECAR_SUFFIX = re.compile(r"\.supplemental-metadata(\(\d+\))?\.json$")


def collect_real_dates():
    """Map basename -> real photoTakenTime from pre-2013 album sidecars on the backup."""
    dates = {}
    for sidecar in sorted(SNAPSHOT_TAKEOUT.rglob("*.json")):
        album_match = ALBUM_PATTERN.match(sidecar.parent.name)
        if not album_match or int(album_match.group(1)) >= SCAN_ERA_START:
            continue
        if not SIDECAR_SUFFIX.search(sidecar.name):
            continue
        media_name = SIDECAR_SUFFIX.sub("", sidecar.name)
        taken, _, _ = parse_json_metadata(sidecar)
        if taken and taken.year < SCAN_ERA_START:
            dates[media_name] = taken
    return dates


def index_survivors():
    """Map basename -> [paths] for every media file in the organized photo tree."""
    index = defaultdict(list)
    for path in PHOTOS.rglob("*"):
        if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
            index[path.name].append(path)
    return index


def main():
    """Main entry point."""
    live = "--live" in sys.argv
    if not SNAPSHOT_TAKEOUT.is_dir():
        print(f"ERROR: backup snapshot not reachable at {SNAPSHOT_TAKEOUT}")
        return 2

    real_dates = collect_real_dates()
    print(f"Real dates recovered from backup sidecars: {len(real_dates)}")

    survivors = index_survivors()
    moves = []
    missing = []

    for media_name, taken in sorted(real_dates.items()):
        stem = Path(media_name).stem
        suffix = Path(media_name).suffix
        variants = [media_name, f"{stem}-edited{suffix}"]
        found_any = False
        for variant in variants:
            for src in survivors.get(variant, []):
                dst_dir = PHOTOS / str(taken.year) / MONTH_NAMES[taken.month - 1]
                if src.parent == dst_dir:
                    continue
                moves.append((src, dst_dir / src.name, taken))
                found_any = True
        if not found_any and not survivors.get(media_name):
            missing.append(media_name)

    print(f"{'LIVE' if live else 'DRY RUN'}: {len(moves)} files to re-place, "
          f"{len(missing)} names with no surviving copy")
    for name in missing[:10]:
        print(f"  MISSING: {name}")

    by_dest = defaultdict(int)
    for _, dst, _ in moves:
        by_dest[f"{dst.parent.parent.name}/{dst.parent.name}"] += 1
    for dest in sorted(by_dest):
        print(f"  {by_dest[dest]:4d} -> {dest}")

    collisions = [dst for _, dst, _ in moves if dst.exists()]
    if collisions:
        print(f"ABORT: {len(collisions)} collisions, e.g. {collisions[0]}")
        return 1

    if not live:
        return 0

    for src, dst, taken in moves:
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        stamp = taken.strftime("%Y:%m:%d %H:%M:%S")
        subprocess.run(
            ["exiftool", "-overwrite_original", "-q",
             f"-DateTimeOriginal={stamp}", f"-CreateDate={stamp}",
             f"-ModifyDate={stamp}", f"-FileCreateDate={stamp}",
             f"-FileModifyDate={stamp}",
             "-XMP-dc:Subject-=date-estimated", "-IPTC:Keywords-=date-estimated",
             str(dst)],
            check=False)
    print("Re-placed with real dates; date-estimated markers removed.")

    # Remove any now-empty Circa/holding folders the moves vacated.
    for folder in sorted({src.parent for src, _, _ in moves}, reverse=True):
        try:
            folder.rmdir()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
