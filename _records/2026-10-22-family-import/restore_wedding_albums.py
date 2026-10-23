#!/usr/bin/env python3
"""
One-off repair: reunite flattened wedding-album photos into event folders.

organize_media's find_google_photos_dirs only checks direct children of
TO_PROCESS, so the nested takeout's project folders were never processed as
albums — their photos were swept loose into year/month folders by date. The
filename prefixes map 1:1 onto the six album folders (verified against the
surviving sidecars), so this moves them into the folders the project-folder
machinery would have created: Organized_Photos/2023/06 <Album>/.

Usage: .venv/bin/python .TMP_restore_wedding_albums.py [--live]
"""

import re
import sys
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PHOTOS = SCRIPT_DIR / "Organized_Photos"
WEDDING_YEAR_DIR = PHOTOS / "2023"

# Case-sensitive prefix -> album folder (from surviving sidecar paths).
PREFIX_TO_ALBUM = {
    "CeremonyA": "Carina + Charlie - Ceremony - Singles",
    "CeremonyB": "Carina + Charlie - Ceremony - Singles",
    "CeremonyC": "Carina + Charlie - Ceremony - Singles",
    "Portraits": "Carina + Charlie - Couples Portraits - Singles",
    "Family": "Carina + Charlie - Family Photos - Singles",
    "GettingReady": "Carina + Charlie - Getting Ready - Singles",
    "ReceptionA": "Carina + Charlie - Reception - Singles",
    "ReceptionB": "Carina + Charlie - Reception - Singles",
    "Bridesmaids": "Carina + Charlie - Wedding Party - Singles",
    "FullParty": "Carina + Charlie - Wedding Party - Singles",
    "Groomsmen": "Carina + Charlie - Wedding Party - Singles",
}
WEDDING_NAME = re.compile(
    r"^(" + "|".join(PREFIX_TO_ALBUM) + r")-\d+(-edited)?(_\d+)?\.(jpg|jpeg|png)$")

# Where the date sweep put them: all of 2023 plus the one 2022-12 stray.
SEARCH_ROOTS = [WEDDING_YEAR_DIR, PHOTOS / "2022"]


def main():
    """Main entry point."""
    live = "--live" in sys.argv
    moves = []

    for root in SEARCH_ROOTS:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            # Never pull a file back OUT of an album folder we created.
            if "Carina + Charlie" in path.parent.name:
                continue
            match = WEDDING_NAME.match(path.name)
            if not match:
                continue
            album = PREFIX_TO_ALBUM[match.group(1)]
            dst = WEDDING_YEAR_DIR / f"06 {album}" / path.name
            moves.append((path, dst))

    counts = Counter(dst.parent.name for _, dst in moves)
    print(f"{'LIVE' if live else 'DRY RUN'}: {len(moves)} files to reunite")
    for folder, count in sorted(counts.items()):
        print(f"  {count:4d} -> 2023/{folder}")

    collisions = [dst for _, dst in moves if dst.exists()]
    if collisions:
        print(f"\nABORT: {len(collisions)} destination collisions, e.g. {collisions[0]}")
        return 1

    if live:
        for src, dst in moves:
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
        print("Moved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
