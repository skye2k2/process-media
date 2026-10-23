#!/usr/bin/env python3
"""
Pre-organize routing for scanned family-history photos in a Google Takeout.

Runs BEFORE workflow_takeout.py. organize_media.py trusts filename dates
first and sidecar JSON second, so a scan whose photoTakenTime is its 2013-2014
SCAN date would file into the real 2013-2014 archive — the scattering the
design spec forbids. This script classifies every file in the takeout's
standard "Photos from YYYY" albums (family_scan_classifier) and:

    backdated - tags person metadata in place; organize_media files it later
                by its real pre-2013 sidecar date
    circa     - moves it to <output>/<year>/00 Circa/, merges its sidecar,
                then overwrites dates to Jan 1 <year> + 'date-estimated'
    unknown   - moves it to <output>/_FAMILY_HISTORY_/<batch>/, merges its
                sidecar; the scan date stays (it is factual there)
    modern    - untouched; the normal workflow owns it

Project folders (wedding albums) and comma-named shared folders are never
touched. Core processing (organize_media.py et al.) is never modified.

Usage:
    .venv/bin/python route_family_scans.py --input-dir "TO_PROCESS/<takeout>" \
        [--output-root Organized_Photos] [--person "Clifford Bergmann"] [--dry-run]
"""

import argparse
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from backup_archive import md5_of_file
from family_scan_classifier import classify_file, extract_batch_prefix, extract_filename_year
from media_utils import MEDIA_EXTENSIONS, get_metadata_path, parse_json_metadata
from organize_media import is_project_folder

SCRIPT_DIR = Path(__file__).parent
DEFAULT_OUTPUT_ROOT = SCRIPT_DIR / "Organized_Photos"
FAMILY_HISTORY_DIRNAME = "_FAMILY_HISTORY_"
CIRCA_DIRNAME = "00 Circa"

# Standard Google Photos album folders are the ONLY routing scope.
STANDARD_ALBUM_PATTERN = re.compile(r"^Photos from (\d{4})$")

# exiftool argfile batch ceiling; keeps command lines and memory bounded.
EXIFTOOL_BATCH_SIZE = 500


@dataclass
class RouteAction:
    """One file's routing decision: where it is, what it is, where it goes."""

    src: Path
    sidecar: Path
    bucket: str
    year: int
    batch: str
    dst: Path


def iter_standard_albums(input_dir):
    """Yield every 'Google Photos/Photos from YYYY' folder under the takeout."""
    for candidate in sorted(Path(input_dir).rglob("Photos from *")):
        if (candidate.is_dir()
                and STANDARD_ALBUM_PATTERN.match(candidate.name)
                and candidate.parent.name == "Google Photos"):
            yield candidate


def read_camera_models(paths):
    """
    Batch-read EXIF Model for ambiguous files; {path: model or None}.

    Only files rules 1-3 left undecided get this lookup, so the exiftool cost
    scales with the ambiguous remainder, not the whole takeout.
    """
    models = {}
    path_list = list(paths)
    for start in range(0, len(path_list), EXIFTOOL_BATCH_SIZE):
        models.update(_parse_models_json(path_list[start:start + EXIFTOOL_BATCH_SIZE]))
    return models


def _parse_models_json(chunk):
    """Read Model via exiftool -json, which is unambiguous to parse."""
    import json as jsonlib

    result = subprocess.run(
        ["exiftool", "-json", "-Model", "-m"] + [str(p) for p in chunk],
        capture_output=True, text=True)
    models = {Path(p): None for p in chunk}
    if result.stdout.strip():
        try:
            for entry in jsonlib.loads(result.stdout):
                models[Path(entry["SourceFile"])] = entry.get("Model")
        except (ValueError, KeyError):
            pass
    return models


def collect_project_filenames(input_dir):
    """
    Basenames of every media file inside the takeout's project folders.

    Google also places project-album photos in the year albums. organize_media
    processes project folders first and deletes the year-album twins as
    duplicates — so the router must leave those twins alone (bucket
    'project-owned'), or wedding photos would land in the holding folder.
    """
    names = set()
    for google_photos in Path(input_dir).rglob("Google Photos"):
        if not google_photos.is_dir():
            continue
        for folder in google_photos.iterdir():
            if not folder.is_dir() or not is_project_folder(folder.name):
                continue
            for path in folder.rglob("*"):
                if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
                    names.add(path.name)
    return names


def plan_routes(input_dir, output_root):
    """
    Classify every media file in the takeout's standard albums into actions.

    Pure planning: nothing moves here. Ambiguous files get one batched EXIF
    Model lookup before final classification (camera EXIF rescues genuine
    digital photos whose names carry no date).
    """
    output_root = Path(output_root)
    project_names = collect_project_filenames(input_dir)
    provisional = []

    for album in iter_standard_albums(input_dir):
        for path in sorted(album.iterdir()):
            if not path.is_file() or path.suffix.lower() not in MEDIA_EXTENSIONS:
                continue
            sidecar = get_metadata_path(path)
            taken_year = None
            if sidecar:
                photo_taken, _, _ = parse_json_metadata(sidecar)
                if photo_taken:
                    taken_year = photo_taken.year
            provisional.append((album.name, path, sidecar, taken_year))

    ambiguous = [p for album, p, s, y in provisional
                 if p.name not in project_names
                 and classify_file(album, p.name, y, None) == "unknown"]
    models = read_camera_models(ambiguous) if ambiguous else {}

    actions = []
    for album_name, path, sidecar, taken_year in provisional:
        if path.name in project_names:
            actions.append(RouteAction(src=path, sidecar=sidecar,
                                       bucket="project-owned", year=None,
                                       batch=None, dst=path))
            continue
        bucket = classify_file(album_name, path.name, taken_year, models.get(path))

        year = None
        batch = None
        if bucket == "circa":
            year = extract_filename_year(path.name)
            dst = output_root / str(year) / CIRCA_DIRNAME / path.name
        elif bucket == "unknown":
            batch = extract_batch_prefix(path.name)
            dst = output_root / FAMILY_HISTORY_DIRNAME / batch / path.name
        else:
            # backdated and modern stay where they are (tag/no-op respectively)
            dst = path

        actions.append(RouteAction(src=path, sidecar=sidecar, bucket=bucket,
                                   year=year, batch=batch, dst=dst))
    return actions


def _unique_destination(dst):
    """Append _N before the suffix until the name is free (matches organize_media)."""
    counter = 1
    candidate = dst
    while candidate.exists():
        candidate = dst.parent / f"{dst.stem}_{counter}{dst.suffix}"
        counter += 1
    return candidate


def _move_sidecar(action, final_dst):
    """Move the sidecar next to its media file, tracking any _N rename."""
    if not action.sidecar or not action.sidecar.exists():
        return
    suffix = action.sidecar.name.replace(action.src.name, "", 1)
    sidecar_dst = final_dst.parent / f"{final_dst.name}{suffix}"
    if sidecar_dst.exists():
        sidecar_dst = _unique_destination(sidecar_dst)
    action.sidecar.rename(sidecar_dst)


def execute_moves(actions, dry_run=False):
    """
    Perform the circa/unknown moves with content-hash dedupe.

    A destination-name collision is md5-compared: identical bytes mean a
    cross-Takeout-part duplicate (source and sidecar are deleted); different
    bytes get the _N suffix organize_media uses. Dry-run touches nothing.
    Returns a summary dict the report and the tests consume.
    """
    summary = {
        "bucket_counts": Counter(a.bucket for a in actions),
        "batch_counts": Counter(a.batch for a in actions if a.batch),
        "moved": [],
        "duplicates_deleted": 0,
        "backdated_twins_deleted": 0,
        "touched_dirs": set(),
    }

    if dry_run:
        return summary

    # Google's year view duplicates backdated album photos into scan-year
    # albums. Moving such a twin into the archive lets organize_media's
    # name-based dedupe later delete the BACKDATED original (this cost 580
    # placements on 2026-10-22), so an identical-bytes twin dies here instead.
    backdated_by_name = {a.src.name: a.src for a in actions
                         if a.bucket == "backdated"}

    for action in actions:
        if action.bucket not in ("circa", "unknown"):
            continue
        if not action.src.exists():
            continue  # idempotent re-run: already handled

        backdated_src = backdated_by_name.get(action.src.name)
        if (backdated_src and backdated_src.exists()
                and md5_of_file(action.src) == md5_of_file(backdated_src)):
            action.src.unlink()
            if action.sidecar and action.sidecar.exists():
                action.sidecar.unlink()
            summary["backdated_twins_deleted"] += 1
            continue

        action.dst.parent.mkdir(parents=True, exist_ok=True)
        final_dst = action.dst

        if final_dst.exists():
            if md5_of_file(action.src) == md5_of_file(final_dst):
                action.src.unlink()
                if action.sidecar and action.sidecar.exists():
                    action.sidecar.unlink()
                summary["duplicates_deleted"] += 1
                continue
            final_dst = _unique_destination(final_dst)

        action.src.rename(final_dst)
        _move_sidecar(action, final_dst)
        summary["moved"].append((action, final_dst))
        summary["touched_dirs"].add(final_dst.parent)

    return summary


def _run_exiftool_argfile(tag_args, paths):
    """
    Run one exiftool write over an argfile batch; return failing paths.

    exiftool reports per-file problems as 'Error: <why> - <path>' and keeps
    going, so failures are detected by matching each path against error lines
    rather than by exit code alone.
    """
    failures = []
    for start in range(0, len(paths), EXIFTOOL_BATCH_SIZE):
        chunk = paths[start:start + EXIFTOOL_BATCH_SIZE]
        with tempfile.NamedTemporaryFile("w", suffix=".args", delete=False) as argfile:
            for arg in tag_args:
                argfile.write(arg + "\n")
            argfile.write("-overwrite_original\n")
            for path in chunk:
                argfile.write(str(path) + "\n")
            argfile_path = argfile.name

        result = subprocess.run(["exiftool", "-@", argfile_path],
                                capture_output=True, text=True)
        Path(argfile_path).unlink()

        output = result.stdout + result.stderr
        error_lines = [line for line in output.splitlines()
                       if line.startswith("Error")]
        chunk_failures = []
        for path in chunk:
            matching = [line for line in error_lines if str(path) in line]
            if matching:
                chunk_failures.append((path, matching[0]))

        # A nonzero exit with no per-file Error lines (e.g. a rejected tag arg
        # yields only a Warning plus "Nothing to do." and exit 1) means the
        # whole chunk may be untagged — report every file, never exit clean.
        if result.returncode != 0 and not chunk_failures:
            reason = output.strip().splitlines()
            summary_line = reason[0] if reason else f"exiftool exited {result.returncode}"
            chunk_failures = [(path, f"exiftool exit {result.returncode}: {summary_line}")
                              for path in chunk]
        failures.extend(chunk_failures)
    return failures


def tag_files(paths, person, extra_keywords):
    """
    Write the person-tag convention (spec §2) onto media files.

    All three fields, always: PersonInImage (standards-correct), XMP Subject
    and IPTC Keywords (broad compatibility). Never writes Artist — the person
    is the subject, not the photographer. Returns [(path, error)] failures.
    """
    paths = [Path(p) for p in paths]
    if not paths:
        return []
    tag_args = [
        f"-XMP-iptcExt:PersonInImage+={person}",
        f"-XMP-dc:Subject+={person}",
        f"-IPTC:Keywords+={person}",
    ]
    for keyword in extra_keywords:
        tag_args.append(f"-XMP-dc:Subject+={keyword}")
        tag_args.append(f"-IPTC:Keywords+={keyword}")
    return _run_exiftool_argfile(tag_args, paths)


def apply_estimated_dates(paths, year):
    """
    Overwrite all date fields to Jan 1 of the estimated year (after merge).

    The date-estimated marker is written here, in the same pass as the dates
    it describes, because the spec makes it unconditional — it must never
    depend on whether a person tag was requested.
    """
    stamp = f"{year}:01:01 00:00:00"
    tag_args = [
        f"-DateTimeOriginal={stamp}",
        f"-CreateDate={stamp}",
        f"-ModifyDate={stamp}",
        f"-FileCreateDate={stamp}",
        f"-FileModifyDate={stamp}",
        "-XMP-dc:Subject+=date-estimated",
        "-IPTC:Keywords+=date-estimated",
    ]
    return _run_exiftool_argfile(tag_args, [Path(p) for p in paths])


def merge_sidecars(directories):
    """Run the existing merge_metadata.py over each touched destination dir."""
    for directory in sorted(directories):
        subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "merge_metadata.py"),
             str(directory), "--recursive", "--remove-json"],
            check=False)


def print_report(summary, failures):
    """Human-readable outcome; the log of a live run is the audit record."""
    print("\n=== route_family_scans report ===")
    print("Buckets:")
    for bucket, count in sorted(summary["bucket_counts"].items()):
        print(f"  {bucket:10s} {count}")
    if summary["batch_counts"]:
        print("Holding batches:")
        for batch, count in sorted(summary["batch_counts"].items()):
            print(f"  {batch:20s} {count}")
    print(f"Duplicates deleted: {summary['duplicates_deleted']}")
    print(f"Files moved:        {len(summary['moved'])}")
    if failures:
        print(f"\n❌ TAG FAILURES ({len(failures)}):")
        for path, error in failures:
            print(f"  {path}: {error}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--person", default=None,
                        help='Person tag value, e.g. "Clifford Bergmann"')
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"Planning routes for {args.input_dir} ...")
    actions = plan_routes(args.input_dir, args.output_root)
    summary = execute_moves(actions, dry_run=args.dry_run)

    failures = []
    if not args.dry_run:
        # Merge sidecar JSON into EXIF first — the circa date overwrite must
        # come AFTER the merge, or the merge re-writes the scan date on top.
        merge_sidecars(summary["touched_dirs"])

        circa_by_year = defaultdict(list)
        unknown_moved = []
        for action, final_dst in summary["moved"]:
            if action.bucket == "circa":
                circa_by_year[action.year].append(final_dst)
            else:
                unknown_moved.append(final_dst)

        if args.person:
            backdated_in_place = [a.src for a in actions
                                  if a.bucket == "backdated" and a.src.exists()]
            failures += tag_files(backdated_in_place, args.person, [])
            failures += tag_files(unknown_moved, args.person, [])
            for moved in circa_by_year.values():
                failures += tag_files(moved, args.person, [])

        # Dates AND the date-estimated marker: unconditional, person or not.
        for year, moved in circa_by_year.items():
            failures += apply_estimated_dates(moved, year)

    print_report(summary, failures)
    if failures:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
