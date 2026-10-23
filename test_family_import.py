#!/usr/bin/env python3
"""
Unit tests for the family-history scan routing layer.

The classifier decides whether a takeout file keeps its real date, gets a
circa year, or goes to the holding folder — a wrong bucket scatters scans
into the real 2013-2014 archive, which is the failure this feature exists
to prevent. Buckets and pinned examples come from the design spec
(docs/superpowers/specs/2026-10-21-family-history-import-and-backup-design.md).

Usage:
    .venv/bin/python test_family_import.py -v
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backup_archive import build_manifest
from family_scan_classifier import (
    classify_file,
    extract_batch_prefix,
    extract_filename_year,
)
from route_family_scans import (
    _run_exiftool_argfile,
    apply_estimated_dates,
    execute_moves,
    plan_routes,
    tag_files,
)


def make_sidecar(media_path, taken_timestamp):
    """Write a real-shape Takeout supplemental sidecar next to a media file."""
    sidecar = media_path.parent / f"{media_path.name}.supplemental-metadata.json"
    sidecar.write_text(json.dumps({
        "title": media_path.name,
        "photoTakenTime": {"timestamp": str(taken_timestamp)},
        "creationTime": {"timestamp": str(taken_timestamp)},
        "geoData": {"latitude": 0.0, "longitude": 0.0, "altitude": 0.0},
    }))
    return sidecar


def make_takeout_fixture(root):
    """
    Build a miniature two-part takeout exercising every routing bucket.

    Timestamps: 1392052564 = 2014-02-10 (scan era), 333988070 = 1980-08-01.
    """
    root = Path(root)
    album_2013 = root / "Takeout" / "Google Photos" / "Photos from 2013"
    album_1980 = root / "Takeout" / "Google Photos" / "Photos from 1980"
    album_dup = root / "Takeout 3" / "Google Photos" / "Photos from 2013"
    wedding = root / "Takeout" / "Google Photos" / "Carina + Charlie - Ceremony - Singles"
    for folder in (album_2013, album_1980, album_dup, wedding):
        folder.mkdir(parents=True)

    unknown = album_2013 / "cars-045.jpg"
    unknown.write_bytes(b"unknown-scan-bytes")
    make_sidecar(unknown, 1392052564)

    circa = album_2013 / "1980-youth-065.jpg"
    circa.write_bytes(b"circa-scan-bytes")
    make_sidecar(circa, 1392052564)

    backdated = album_1980 / "scan-001.jpg"
    backdated.write_bytes(b"backdated-bytes")
    make_sidecar(backdated, 333988070)

    modern = album_2013 / "IMG_20130501_101010.jpg"
    modern.write_bytes(b"modern-bytes")
    make_sidecar(modern, 1367403010)

    # Google also places project-album photos in the year albums; the router
    # must leave those for organize_media's own project dedupe.
    project_twin = album_2013 / "CeremonyA-19.jpg"
    project_twin.write_bytes(b"wedding-bytes")
    make_sidecar(project_twin, 1685899253)

    duplicate = album_dup / "cars-045.jpg"
    duplicate.write_bytes(b"unknown-scan-bytes")
    make_sidecar(duplicate, 1392052564)

    wedding_file = wedding / "CeremonyA-19.jpg"
    wedding_file.write_bytes(b"wedding-bytes")

    return root


class TestPlanRoutes(unittest.TestCase):
    """plan_routes assigns the spec's buckets and destinations."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.input_root = make_takeout_fixture(Path(self.tmp.name) / "takeout")
        self.output_root = Path(self.tmp.name) / "Organized_Photos"
        self.actions = plan_routes(self.input_root, self.output_root)
        self.by_name = {action.src.name: action for action in self.actions}

    def tearDown(self):
        self.tmp.cleanup()

    def test_unknown_routes_to_family_history_batch_folder(self):
        actions = [a for a in self.actions if a.src.name == "cars-045.jpg"]
        self.assertTrue(all(a.bucket == "unknown" for a in actions))
        self.assertTrue(all(
            a.dst == self.output_root / "_FAMILY_HISTORY_" / "cars" / "cars-045.jpg"
            for a in actions))

    def test_circa_routes_to_year_circa_folder(self):
        action = self.by_name["1980-youth-065.jpg"]
        self.assertEqual(action.bucket, "circa")
        self.assertEqual(action.year, 1980)
        self.assertEqual(action.dst,
                         self.output_root / "1980" / "00 Circa" / "1980-youth-065.jpg")

    def test_backdated_stays_in_place(self):
        action = self.by_name["scan-001.jpg"]
        self.assertEqual(action.bucket, "backdated")
        self.assertEqual(action.dst, action.src)

    def test_modern_file_is_left_for_the_normal_workflow(self):
        action = self.by_name["IMG_20130501_101010.jpg"]
        self.assertEqual(action.bucket, "modern")
        self.assertEqual(action.dst, action.src)

    def test_project_folders_are_never_touched(self):
        wedding_srcs = [a.src for a in self.actions
                        if "Carina + Charlie" in str(a.src)]
        self.assertEqual(wedding_srcs, [])

    def test_year_album_copy_of_project_file_is_left_alone(self):
        # The year-album twin of a project-folder photo is organize_media's
        # dedupe target, never routing material.
        action = self.by_name["CeremonyA-19.jpg"]
        self.assertEqual(action.bucket, "project-owned")
        self.assertEqual(action.dst, action.src)


class TestExecuteMoves(unittest.TestCase):
    """File movement, cross-part dedupe, and dry-run inertness."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.input_root = make_takeout_fixture(Path(self.tmp.name) / "takeout")
        self.output_root = Path(self.tmp.name) / "Organized_Photos"
        self.actions = plan_routes(self.input_root, self.output_root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_identical_duplicate_across_parts_is_deleted_not_suffixed(self):
        summary = execute_moves(self.actions, dry_run=False)

        dst = self.output_root / "_FAMILY_HISTORY_" / "cars" / "cars-045.jpg"
        self.assertTrue(dst.exists())
        self.assertFalse((dst.parent / "cars-045_1.jpg").exists())
        self.assertEqual(summary["duplicates_deleted"], 1)
        # Both sources and both sidecars are gone from the takeout.
        leftovers = list(self.input_root.rglob("cars-045*"))
        self.assertEqual(leftovers, [])

    def test_sidecar_travels_with_the_media_file(self):
        execute_moves(self.actions, dry_run=False)
        moved_sidecar = (self.output_root / "1980" / "00 Circa" /
                         "1980-youth-065.jpg.supplemental-metadata.json")
        self.assertTrue(moved_sidecar.exists())

    def test_dry_run_leaves_the_tree_byte_identical(self):
        before = build_manifest(self.input_root)
        execute_moves(self.actions, dry_run=True)
        after = build_manifest(self.input_root)
        self.assertEqual(before, after)
        self.assertFalse(self.output_root.exists())


class TestTagFiles(unittest.TestCase):
    """The tag pass must report failures, never silently skip (Review Focus 4)."""

    def test_text_masquerading_as_jpg_is_reported_as_failure(self):
        with tempfile.TemporaryDirectory() as root:
            fake = Path(root) / "cards-010.jpg"
            fake.write_text("this is not a jpeg")
            failures = tag_files([fake], "Clifford Bergmann", [])
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0][0], fake)

    def test_real_jpeg_gets_all_three_person_fields(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as root:
            real = Path(root) / "family-BB-016.jpg"
            Image.new("RGB", (4, 4)).save(real)
            failures = tag_files([real], "Clifford Bergmann", ["date-estimated"])
            self.assertEqual(failures, [])

            readback = subprocess.run(
                ["exiftool", "-XMP-iptcExt:PersonInImage", "-XMP-dc:Subject",
                 "-IPTC:Keywords", "-s", str(real)],
                capture_output=True, text=True)
            self.assertEqual(readback.stdout.count("Clifford Bergmann"), 3)
            self.assertIn("date-estimated", readback.stdout)


class TestExtractFilenameYear(unittest.TestCase):
    """A leading 4-digit year 1900-2012 followed by - or _ is a circa year."""

    def test_accepts_hyphenated_scan_batch(self):
        self.assertEqual(extract_filename_year("1980-youth-065.jpg"), 1980)

    def test_accepts_underscore_style(self):
        self.assertEqual(extract_filename_year("1990_13.jpg"), 1990)
        self.assertEqual(extract_filename_year("1997_8.jpg"), 1997)

    def test_rejects_scan_era_years(self):
        # 2013+ is the scan era; a leading 2013 is not a depicted-era hint.
        self.assertIsNone(extract_filename_year("2013-something-01.jpg"))

    def test_rejects_full_camera_timestamps(self):
        self.assertIsNone(extract_filename_year("20240520_191937921.jpg"))

    def test_rejects_year_without_separator(self):
        self.assertIsNone(extract_filename_year("1990.jpg"))

    def test_rejects_pre_1900(self):
        self.assertIsNone(extract_filename_year("1850-engraving-01.jpg"))

    def test_accepts_tilde_circa_and_space_separated_years(self):
        # Real scan names: "~1960 Eugen Bergmann.jpg", "2006 Kaethe_and_Eugen.jpg"
        self.assertEqual(extract_filename_year("~1960 Eugen Bergmann.jpg"), 1960)
        self.assertEqual(extract_filename_year("2006 Kaethe_and_Eugen.jpg"), 2006)


class TestExtractBatchPrefix(unittest.TestCase):
    """Pinned examples from the spec; the prefix becomes the holding subfolder."""

    def test_pinned_examples(self):
        self.assertEqual(extract_batch_prefix("cars-045.jpg"), "cars")
        self.assertEqual(extract_batch_prefix("family-BB-016.jpg"), "family-BB")
        self.assertEqual(extract_batch_prefix("FH000011.JPG"), "FH")
        self.assertEqual(extract_batch_prefix("0NBergm-R1-040-18A.jpg"), "0NBergm-R1")

    def test_takeout_dedupe_counter_is_stripped(self):
        # Real takeout data carries Google's own collision counters.
        self.assertEqual(extract_batch_prefix("FH000022(13).JPG"), "FH")

    def test_edited_variant_joins_its_batch(self):
        self.assertEqual(extract_batch_prefix("cars-045-edited.jpg"), "cars")

    def test_all_digit_stem_falls_back_to_misc(self):
        self.assertEqual(extract_batch_prefix("1060605356.jpg"), "misc")

    def test_strip_never_empties_the_stem(self):
        self.assertEqual(extract_batch_prefix("045.jpg"), "misc")


class TestEstimatedDates(unittest.TestCase):
    """The estimated-date marker is unconditional (spec §1), not a --person rider."""

    def test_apply_estimated_dates_writes_marker_and_dates(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as root:
            photo = Path(root) / "1980-youth-001.jpg"
            Image.new("RGB", (4, 4)).save(photo)
            failures = apply_estimated_dates([photo], 1980)
            self.assertEqual(failures, [])

            readback = subprocess.run(
                ["exiftool", "-DateTimeOriginal", "-XMP-dc:Subject",
                 "-IPTC:Keywords", "-s", str(photo)],
                capture_output=True, text=True)
            self.assertIn("1980:01:01 00:00:00", readback.stdout)
            self.assertEqual(readback.stdout.count("date-estimated"), 2)


class TestExiftoolFailureDetection(unittest.TestCase):
    """A nonzero exiftool exit with no 'Error:' lines must still fail (Review Focus 4)."""

    def test_exit_code_failure_without_error_lines_is_reported(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as root:
            photo = Path(root) / "ok.jpg"
            Image.new("RGB", (4, 4)).save(photo)
            # A nonexistent tag makes exiftool print only a Warning and
            # "Nothing to do." yet exit 1 — the silent-success trap.
            failures = _run_exiftool_argfile(["-NotARealTagXYZ=x"], [photo])
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0][0], photo)


class TestBackdatedTwinGuard(unittest.TestCase):
    """
    Google's year view duplicates backdated album photos into scan-year albums.
    Moving the twin lets organize_media's name dedupe delete the backdated
    original (this ate 580 placements live on 2026-10-22) — an identical-bytes
    twin must be deleted at routing time, never moved.
    """

    def test_identical_twin_of_backdated_file_is_deleted_not_routed(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        input_root = make_takeout_fixture(Path(self.tmp.name) / "takeout")
        output_root = Path(self.tmp.name) / "Organized_Photos"

        # Identical bytes of the 1980-album backdated file, under its scan-date
        # sidecar in the 2013 album — exactly the year-view twin shape.
        album_2013 = input_root / "Takeout" / "Google Photos" / "Photos from 2013"
        twin = album_2013 / "scan-001.jpg"
        twin.write_bytes(b"backdated-bytes")
        make_sidecar(twin, 1392052564)

        actions = plan_routes(input_root, output_root)
        summary = execute_moves(actions, dry_run=False)

        self.assertEqual(summary["backdated_twins_deleted"], 1)
        self.assertFalse(twin.exists())
        self.assertEqual(list(output_root.rglob("scan-001*")), [])
        backdated = (input_root / "Takeout" / "Google Photos" /
                     "Photos from 1980" / "scan-001.jpg")
        self.assertTrue(backdated.exists())


class TestClassifyFile(unittest.TestCase):
    """Bucket decisions, in the spec's pinned priority order."""

    def test_negative_epoch_platform_support(self):
        # 1963 sidecars carry negative epoch timestamps; prove the platform
        # converts them before trusting any 1963 classification downstream.
        taken = datetime.fromtimestamp(-220924800, tz=timezone.utc)
        self.assertEqual(taken.year, 1963)

    def test_backdated_year_wins(self):
        result = classify_file("Photos from 1963", "scan-001.jpg",
                               taken_year=1963, camera_model=None)
        self.assertEqual(result, "backdated")

    def test_full_filename_date_is_modern_even_with_scan_year(self):
        result = classify_file("Photos from 2024", "IMG_20240520_191937921.jpg",
                               taken_year=2024, camera_model=None)
        self.assertEqual(result, "modern")

    def test_filename_year_is_circa(self):
        result = classify_file("Photos from 2013", "1980-youth-065.jpg",
                               taken_year=2013, camera_model=None)
        self.assertEqual(result, "circa")

    def test_camera_model_rescues_ambiguous_modern_file(self):
        result = classify_file("Photos from 2023", "1060605356.jpg",
                               taken_year=2023, camera_model="Pixel 6")
        self.assertEqual(result, "modern")

    def test_no_signals_fails_safe_to_unknown(self):
        result = classify_file("Photos from 2014", "cars-045.jpg",
                               taken_year=2014, camera_model=None)
        self.assertEqual(result, "unknown")

    def test_missing_sidecar_with_no_signals_is_unknown(self):
        # taken_year=None must never fabricate a date or crash.
        result = classify_file("Photos from 2014", "cards-010.jpg",
                               taken_year=None, camera_model=None)
        self.assertEqual(result, "unknown")


if __name__ == "__main__":
    unittest.main()
