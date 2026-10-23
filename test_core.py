#!/usr/bin/env python3
"""
Core unit tests for the process-media toolkit.

Covers the critical calculation functions and business-logic assumptions
that have historically caused silent data-quality bugs. This is not
meant to be a comprehensive integration suite — it specifically targets
the functions whose failures are hard to notice until photos are already
gone or misclassified.

Sections:
    1. Date extraction (organize_archive.py + check_nas_archive.py)
    2. (removed — covered dead code; see the note in that section)
    3. Project-folder classification (is_project_folder, DCIM guard)
    4. Keeper-priority sorting (_sort_paths_by_keeper_priority)
    5. AnalysisCache get/set/invalidation (analyze_photo_quality.py)
    6. Shell-export escaping (both browse and review-issues export paths)
    7. Camera model suffix + destination filename (reconcile_nikon_archive.py)
    8. Event cluster folder adoption (create_event_folders.py, BUG-5)
    9. EXIF-only duplicate detection (duplicate_detector.py, BUG-6)

Usage:
    python3 test_core.py                # Run all tests
    python3 test_core.py -v             # Verbose output
    python3 test_core.py TestDateExtraction  # Run a single class

Caveats:
    - Tests that exercise photo_triage internals import the module directly
      and therefore initialize the module-level cache machinery. This is
      harmless but means the first import of photo_triage.py is slow.
    - Keeper-priority tests use real tempfiles so that Path.stat() works.
      Tests clean up after themselves but may leave debris on hard crash.
"""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Ensure we can import from this directory regardless of cwd
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

import camcorder_convert
import attribute_splices
import check_media_health
import check_nas_archive
import create_event_folders
import detect_splices
import duplicate_detector
import organize_archive
import preflight_import
import reconcile_nikon_archive
import removal_history
import verify_conversions
import rescue_damaged_media
from analyze_photo_quality import ImageAnalysisCache, get_analysis_cache


# ============================================================================
# SECTION 1: Date Extraction
# ============================================================================

class TestDateExtraction(unittest.TestCase):
    """
    Tests for organize_archive.extract_date_from_filename().

    This function is the first step in the processing pipeline — a miss here
    silently falls through to EXIF or mtime, potentially placing a file in
    the wrong year/month folder.
    """

    def _extract(self, filename):
        """Shorthand."""
        return organize_archive.extract_date_from_filename(filename)

    # -- Known-good formats --------------------------------------------------

    def test_vid_prefix(self):
        result = self._extract("VID_20210526_162641582.mp4")
        self.assertEqual(result, datetime(2021, 5, 26, 16, 26, 41))

    def test_img_prefix(self):
        result = self._extract("IMG_20210526_162641.jpg")
        self.assertEqual(result, datetime(2021, 5, 26, 16, 26, 41))

    def test_pxl_prefix(self):
        result = self._extract("PXL_20210526_162641582.mp4")
        self.assertEqual(result, datetime(2021, 5, 26, 16, 26, 41))

    def test_no_prefix(self):
        result = self._extract("20210526_162641.jpg")
        self.assertEqual(result, datetime(2021, 5, 26, 16, 26, 41))

    def test_with_person_suffix(self):
        # Organized filenames include a person suffix after the datetime
        result = self._extract("20210526_162641_Clif.jpg")
        self.assertEqual(result, datetime(2021, 5, 26, 16, 26, 41))

    def test_img_with_milliseconds(self):
        # Some phones append milliseconds after the seconds
        result = self._extract("IMG_20210526_162641582.jpg")
        self.assertEqual(result, datetime(2021, 5, 26, 16, 26, 41))

    # -- DSCN/Nikon DCIM naming - no date in filename ------------------------

    def test_dscn_no_date(self):
        """DSCN_XXXX.JPG filenames carry no embedded date — must return None."""
        result = self._extract("DSCN_1234.JPG")
        self.assertIsNone(result)

    def test_dsc_no_date(self):
        """DSC_XXXX.JPG (Canon/Nikon) carry no embedded date either."""
        result = self._extract("DSC_0001.JPG")
        self.assertIsNone(result)

    # -- Edge / invalid inputs -----------------------------------------------

    def test_returns_none_for_plain_name(self):
        result = self._extract("family_photo.jpg")
        self.assertIsNone(result)

    def test_returns_none_for_invalid_date(self):
        """A pattern match on numerics that happen to be an invalid date should
        return None, not raise an exception."""
        result = self._extract("20001399_990000.jpg")  # month 13, day 99
        self.assertIsNone(result)

    def test_returns_none_for_empty_string(self):
        result = self._extract("")
        self.assertIsNone(result)

    def test_year_2000_boundary(self):
        result = self._extract("IMG_20000101_000000.jpg")
        self.assertEqual(result, datetime(2000, 1, 1, 0, 0, 0))


class TestCheckNasDateExtraction(unittest.TestCase):
    """
    Tests for check_nas_archive.extract_date_from_filename().

    This variant returns a raw YYYYMMDD_HHMMSS string (not a datetime) because
    it is used as a lookup key. Behaviour diverges from organize_archive's
    version — we verify they agree on the extractable substring even when they
    differ in return type.
    """

    def _extract(self, filename):
        return check_nas_archive.extract_date_from_filename(filename)

    def test_vid_prefix_returns_string(self):
        result = self._extract("VID_20210526_162641582.mp4")
        self.assertEqual(result, "20210526_162641")

    def test_img_prefix(self):
        result = self._extract("IMG_20210526_162641.jpg")
        self.assertEqual(result, "20210526_162641")

    def test_no_prefix(self):
        result = self._extract("20210526_162641.jpg")
        self.assertEqual(result, "20210526_162641")

    def test_dscn_no_date(self):
        self.assertIsNone(self._extract("DSCN_1234.JPG"))

    def test_dsc_no_date(self):
        self.assertIsNone(self._extract("DSC_0001.JPG"))

    def test_returns_none_for_plain_name(self):
        self.assertIsNone(self._extract("family_photo.jpg"))


# ============================================================================
# SECTION 2: (removed) organize_archive.find_existing_by_date
# ============================================================================
#
# This section held 8 tests for organize_archive.find_existing_by_date(). That
# function had no call sites -- the live archive import path is
# DuplicateDetector.find_duplicate() -- so the tests validated dead code while
# their docstring claimed to cover "the primary deduplication mechanism for DSCN
# and other EXIF-only files." That false confidence is exactly what hid BUG-6.
#
# The function is deleted; real coverage of the live path lives in Section 9.


# ============================================================================
# SECTION 3: Project-Folder Classification
# ============================================================================

class TestIsProjectFolder(unittest.TestCase):
    r"""
    Tests for organize_archive.is_project_folder().

    This guard determines whether a subdirectory is moved as a unit or has its
    contents scattered by EXIF date. A wrong classification either:
    - Moves an entire camera-bucket (100NIKON) as one event folder, or
    - Scatters a real event folder's files individually by date.

    The DCIM guard regex (^\d{3}[A-Z0-9]+$) was added specifically because
    Nikon/Canon create folders like 100D3000, 101NIKON, 102CANON that look
    superficially similar to project folders.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.input_dir = self.tmp / "TO_PROCESS"
        self.input_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_folder_with_jpg(self, name):
        folder = self.input_dir / name
        folder.mkdir(parents=True)
        (folder / "test.jpg").touch()
        return folder

    # -- Should NOT be treated as project folders ----------------------------

    def test_root_input_dir_excluded(self):
        self.assertFalse(
            organize_archive.is_project_folder(self.input_dir, self.input_dir)
        )

    def test_year_folder_excluded(self):
        folder = self._make_folder_with_jpg("2021")
        self.assertFalse(
            organize_archive.is_project_folder(folder, self.input_dir)
        )

    def test_dcim_100nikon_excluded(self):
        """Standard Nikon DCIM bucket — must NOT be treated as a project."""
        folder = self._make_folder_with_jpg("100NIKON")
        self.assertFalse(
            organize_archive.is_project_folder(folder, self.input_dir)
        )

    def test_dcim_100d3000_excluded(self):
        """Canon DCIM bucket with mixed alpha-numeric suffix."""
        folder = self._make_folder_with_jpg("100D3000")
        self.assertFalse(
            organize_archive.is_project_folder(folder, self.input_dir)
        )

    def test_dcim_101canon_excluded(self):
        folder = self._make_folder_with_jpg("101CANON")
        self.assertFalse(
            organize_archive.is_project_folder(folder, self.input_dir)
        )

    def test_empty_folder_excluded(self):
        """Folder with no media files should not qualify."""
        folder = self.input_dir / "Empty Event"
        folder.mkdir()
        self.assertFalse(
            organize_archive.is_project_folder(folder, self.input_dir)
        )

    # -- Should be treated as project folders --------------------------------

    def test_named_event_folder(self):
        folder = self._make_folder_with_jpg("Christmas 2021")
        self.assertTrue(
            organize_archive.is_project_folder(folder, self.input_dir)
        )

    def test_descriptive_underscore_name(self):
        folder = self._make_folder_with_jpg("Beach_Trip_2019")
        self.assertTrue(
            organize_archive.is_project_folder(folder, self.input_dir)
        )

    def test_single_word_non_year(self):
        folder = self._make_folder_with_jpg("Vacation")
        self.assertTrue(
            organize_archive.is_project_folder(folder, self.input_dir)
        )

    def test_dcim_guard_boundary_two_digits(self):
        """Two-digit prefix does NOT match the three-digit DCIM pattern — should
        be treated normally (has media = project folder)."""
        folder = self._make_folder_with_jpg("10NIKON")
        self.assertTrue(
            organize_archive.is_project_folder(folder, self.input_dir)
        )


# ============================================================================
# SECTION 4: Keeper-Priority Sorting
# ============================================================================

class TestKeeperPrioritySorting(unittest.TestCase):
    """
    Tests for photo_triage._sort_paths_by_keeper_priority().

    This function is the critical business logic that determines which file
    survives when duplicates are found. Incorrect sorting here leads to:
    - Keeping a thumbnail over the full-resolution original
    - Keeping a file with a corrupted mtime over the true original
    - Keeping a file moved to _TO_REVIEW_ while deleting the organized copy

    Tests use real tempfiles (not mocks) so that Path.stat() returns realistic
    data. EXIF date is patched at the function level so tests don't need exiftool.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_file(self, rel_path, size=1000, content=None):
        """Create a real file at tmp/rel_path with a given size."""
        full_path = self.tmp / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        if content:
            full_path.write_bytes(content)
        else:
            full_path.write_bytes(b"x" * size)

        return full_path

    def _sort(self, paths, exif_map=None, dup_type='exact'):
        """
        Run the sort with optional EXIF patching.

        exif_map: {path: datetime | None}  — controls what get_exif_date returns
        """
        import photo_triage

        def fake_exif_date(p):
            if exif_map is None:
                return None
            return exif_map.get(Path(p))

        with patch.object(photo_triage, 'get_exif_date', side_effect=fake_exif_date):
            # Also patch get_image_dimensions so we don't need real image data
            with patch.object(photo_triage, 'get_image_dimensions', return_value=(0, 0)):
                return photo_triage._sort_paths_by_keeper_priority(paths, dup_type=dup_type)

    # -- Criterion 1: organized folder beats review area ---------------------

    def test_organized_beats_review_area(self):
        """A file in Organized_Photos/ must rank above the same file in _TO_REVIEW_."""
        organized = self._make_file("Organized_Photos/2021/05 May/DSC_0001.jpg")
        in_review = self._make_file("_TO_REVIEW_/Duplicates/DSC_0001.jpg")

        result = self._sort([in_review, organized])
        self.assertEqual(result[0], organized, "Organized file should be index-0 keeper")

    def test_blurry_subfolder_deprioritized(self):
        """File inside _TO_REVIEW_/Blurry/ should lose to an organized copy."""
        organized = self._make_file("Organized_Photos/2021/05 May/photo.jpg")
        blurry = self._make_file("_TO_REVIEW_/Blurry/photo.jpg")

        result = self._sort([blurry, organized])
        self.assertEqual(result[0], organized)

    # -- Criterion 3: EXIF date tiebreaker ----------------------------------

    def test_earlier_exif_date_wins(self):
        """The file with the earliest EXIF DateTimeOriginal is the likely original."""
        original = self._make_file("2019/01 January/photo.jpg")
        copy = self._make_file("2019/02 February/photo_copy.jpg")

        exif_map = {
            original: datetime(2019, 1, 15, 12, 0, 0),
            copy: datetime(2019, 2, 10, 12, 0, 0),
        }
        result = self._sort([copy, original], exif_map=exif_map)
        self.assertEqual(result[0], original)

    def test_no_exif_defers_to_size(self):
        """When neither file has EXIF data, larger file (fewer generations of
        re-encoding) should win."""
        large = self._make_file("folder/large.jpg", size=5000)
        small = self._make_file("folder/small.jpg", size=1000)

        result = self._sort([small, large], exif_map={large: None, small: None})
        self.assertEqual(result[0], large)

    # -- Criterion 5: filename length ----------------------------------------

    def test_shorter_filename_wins_on_tie(self):
        """DSC_0001.jpg beats DSC_0001_1.jpg (collision copy) on all else equal."""
        original_name = self._make_file("folder/DSC_0001.jpg", size=1000)
        collision = self._make_file("folder/DSC_0001_1.jpg", size=1000)

        exif_map = {
            original_name: datetime(2021, 1, 1),
            collision: datetime(2021, 1, 1),
        }
        result = self._sort([collision, original_name], exif_map=exif_map)
        self.assertEqual(result[0], original_name)

    # -- Criterion 2: resolution for perceptual-similar groups ---------------

    def test_higher_resolution_wins_for_similar(self):
        """For pHash-similar groups, the higher-resolution image should be keeper."""
        import photo_triage

        hi_res = self._make_file("folder/full_res.jpg")
        lo_res = self._make_file("folder/thumbnail.jpg")

        def fake_exif(p):
            return None

        def fake_dims(p):
            if Path(p).name == "full_res.jpg":
                return (4032, 3024)  # ~12 MP
            return (480, 320)        # thumbnail

        with patch.object(photo_triage, 'get_exif_date', side_effect=fake_exif):
            with patch.object(photo_triage, 'get_image_dimensions', side_effect=fake_dims):
                result = photo_triage._sort_paths_by_keeper_priority(
                    [lo_res, hi_res], dup_type='similar'
                )

        self.assertEqual(result[0], hi_res)

    def test_resolution_ignored_for_exact_duplicates(self):
        """For exact (MD5) duplicates, resolution is not checked — EXIF date wins."""
        import photo_triage

        large_dims = self._make_file("folder/early.jpg", size=1000)
        small_dims = self._make_file("folder/late.jpg", size=1000)

        def fake_exif(p):
            if Path(p).name == "early.jpg":
                return datetime(2019, 1, 1)
            return datetime(2021, 6, 6)

        def fake_dims(p):
            # late.jpg has higher resolution — but for exact dups, this shouldn't matter
            if Path(p).name == "late.jpg":
                return (4032, 3024)
            return (100, 100)

        with patch.object(photo_triage, 'get_exif_date', side_effect=fake_exif):
            with patch.object(photo_triage, 'get_image_dimensions', side_effect=fake_dims):
                result = photo_triage._sort_paths_by_keeper_priority(
                    [small_dims, large_dims], dup_type='exact'
                )

        self.assertEqual(result[0], large_dims, "Earlier EXIF should win for exact dups, not resolution")


# ============================================================================
# SECTION 5: AnalysisCache — persistence and invalidation
# ============================================================================

class TestAnalysisCache(unittest.TestCase):
    """
    Tests for ImageAnalysisCache.

    The cache is the source of truth for blur scores, hashes, and (as of this
    session) image dimensions. Silent cache-read failures are particularly
    dangerous because they cause re-analysis to be skipped while returning
    stale data.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cache_path = self.tmp / ".analysis_cache.json"
        self.image_file = self.tmp / "test_image.jpg"
        self.image_file.write_bytes(b"fake jpeg content")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_cache(self):
        return ImageAnalysisCache(self.cache_path)

    # -- Blur round-trip -----------------------------------------------------

    def test_blur_set_and_get(self):
        cache = self._make_cache()
        cache.set_blur(self.image_file, 123.45)
        cache.save()

        cache2 = self._make_cache()
        result = cache2.get_blur(self.image_file)
        self.assertAlmostEqual(result, 123.45, places=2)

    def test_blur_invalidated_on_mtime_change(self):
        cache = self._make_cache()
        cache.set_blur(self.image_file, 123.45)
        cache.save()

        # Simulate the file being modified
        time.sleep(0.01)
        self.image_file.write_bytes(b"updated content")

        cache2 = self._make_cache()
        self.assertIsNone(cache2.get_blur(self.image_file),
                          "Stale cache entry should be invalidated after file change")

    # -- Hash round-trip -----------------------------------------------------

    def test_hashes_set_and_get(self):
        cache = self._make_cache()
        cache.set_hashes(self.image_file, "abc123", "def456")
        cache.save()

        cache2 = self._make_cache()
        result = cache2.get_hashes(self.image_file)
        self.assertIsNotNone(result)
        self.assertEqual(result["md5"], "abc123")
        self.assertEqual(result["phash"], "def456")

    def test_hashes_invalidated_on_size_change(self):
        cache = self._make_cache()
        cache.set_hashes(self.image_file, "abc123", "def456")
        cache.save()

        # Overwrite with different content (different size)
        self.image_file.write_bytes(b"completely different content that is longer")
        time.sleep(0.01)

        cache2 = self._make_cache()
        self.assertIsNone(cache2.get_hashes(self.image_file))

    def test_partial_hashes_not_returned(self):
        """If only md5 is stored but phash is missing, get_hashes() must return None
        to prevent a half-initialized entry from being used."""
        cache = self._make_cache()
        # Manually insert a partial entry
        key = str(self.image_file.resolve())
        s = self.image_file.stat()
        cache.cache[key] = {"mtime": s.st_mtime, "size": s.st_size, "md5": "abc123"}
        self.assertIsNone(cache.get_hashes(self.image_file))

    # -- Dimensions round-trip -----------------------------------------------

    def test_dimensions_set_and_get(self):
        cache = self._make_cache()
        cache.set_dimensions(self.image_file, 4032, 3024)
        cache.save()

        cache2 = self._make_cache()
        result = cache2.get_dimensions(self.image_file)
        self.assertEqual(result, (4032, 3024))

    def test_dimensions_invalidated_on_file_change(self):
        cache = self._make_cache()
        cache.set_dimensions(self.image_file, 4032, 3024)
        cache.save()

        time.sleep(0.01)
        self.image_file.write_bytes(b"replaced content")

        cache2 = self._make_cache()
        self.assertIsNone(cache2.get_dimensions(self.image_file))

    def test_dimensions_none_for_missing_file(self):
        cache = self._make_cache()
        missing = self.tmp / "nonexistent.jpg"
        self.assertIsNone(cache.get_dimensions(missing))

    # -- Cross-field preservation -------------------------------------------

    def test_set_blur_preserves_existing_hashes(self):
        """Writing a blur score must not clobber a previously stored hash."""
        cache = self._make_cache()
        cache.set_hashes(self.image_file, "md5abc", "phashdef")
        cache.set_blur(self.image_file, 77.7)
        cache.save()

        cache2 = self._make_cache()
        hashes = cache2.get_hashes(self.image_file)
        self.assertIsNotNone(hashes, "Hashes should survive a subsequent set_blur call")
        self.assertEqual(hashes["md5"], "md5abc")

    def test_dirty_flag_cleared_after_save(self):
        cache = self._make_cache()
        cache.set_blur(self.image_file, 50.0)
        self.assertTrue(cache.dirty)
        cache.save()
        self.assertFalse(cache.dirty)

    # -- Corrupted cache file ------------------------------------------------

    def test_corrupted_cache_file_loads_empty(self):
        """A corrupted JSON file should not crash the tool — it should start
        with an empty cache, treating all entries as uncached."""
        self.cache_path.write_text("{this is not valid json}")
        cache = self._make_cache()
        self.assertEqual(cache.cache, {})
        self.assertIsNone(cache.get_blur(self.image_file))


# ============================================================================
# SECTION 6: Shell-Export Escaping
# ============================================================================

class TestShellExportEscaping(unittest.TestCase):
    """
    Tests for the JavaScript single-quote shell escaping used in the generated
    removal scripts. The escape pattern is:
        p.replace(/'/g, "'\\''")
    which turns each embedded single quote into: '  (close) \\ (literal) '' (reopen)

    We simulate this in Python to verify the resulting shell command is correct
    for adversarial filenames. The actual test of the JS replace() is indirect —
    we implement the equivalent transformation in Python and verify it would
    produce safe shell commands.

    IMPORTANT: The goal is not to test JS itself, but to verify that the LOGIC
    of the escaping pattern handles all the dangerous cases the OWASP injection
    categories cover:
        - Dollar signs ($var expansion)
        - Backtick command substitution
        - Semicolons (command chaining)
        - Embedded single quotes
        - Spaces
        - Newlines
    """

    def _shell_escape(self, path_str):
        """
        Python equivalent of the JS escaping pattern:
            const safePath = p.replace(/'/g, "'\\''" );
            `rm '${safePath}'`

        Returns the full rm command string.
        """
        safe = path_str.replace("'", "'\\''")
        return f"rm '{safe}'"

    def _assert_no_injection(self, path_str):
        """
        Verify that the resulting command cannot inject additional shell commands.
        After escaping, the entire path argument must be wrapped in single quotes
        (possibly re-opened after embedded quote escapes). The path itself should
        not be interpretable as additional commands.
        """
        cmd = self._shell_escape(path_str)

        # The command must start with rm ' and end with '
        self.assertTrue(cmd.startswith("rm '"),
                        f"Command should start with rm '  —  got: {cmd!r}")
        self.assertTrue(cmd.endswith("'"),
                        f"Command should end with single quote  —  got: {cmd!r}")

    def test_clean_path(self):
        cmd = self._shell_escape("/Organized_Photos/2021/05 May/photo.jpg")
        self.assertEqual(cmd, "rm '/Organized_Photos/2021/05 May/photo.jpg'")

    def test_dollar_sign_neutralized(self):
        """$HOME and similar expansions must not be interpreted."""
        self._assert_no_injection("/Photos/$HOME/../../etc/passwd")

    def test_backtick_neutralized(self):
        """`command` substitution must not execute."""
        self._assert_no_injection("/Photos/`rm -rf /`/photo.jpg")

    def test_semicolon_neutralized(self):
        """Semicolons cannot chain new commands."""
        self._assert_no_injection("/Photos/2021/; echo pwned #.jpg")

    def test_embedded_single_quote(self):
        """A filename like "Nicole's photo.jpg" contains a single quote."""
        cmd = self._shell_escape("/Photos/Nicole's photo.jpg")
        # The escape should turn ' into '\'' so the shell sees a literal single quote
        self.assertEqual(cmd, "rm '/Photos/Nicole'\\''s photo.jpg'")

    def test_multiple_embedded_quotes(self):
        cmd = self._shell_escape("/Photos/it's a 'test'.jpg")
        expected = "rm '/Photos/it'\\''s a '\\''test'\\''.jpg'"
        self.assertEqual(cmd, expected)

    def test_path_with_spaces(self):
        """Spaces in paths must be preserved without word-splitting."""
        cmd = self._shell_escape("/Photos/Summer Vacation/beach day.jpg")
        self.assertEqual(cmd, "rm '/Photos/Summer Vacation/beach day.jpg'")

    def test_newline_in_path(self):
        """Newlines in filenames (unusual but possible) must be contained."""
        self._assert_no_injection("/Photos/weird\nname.jpg")

    def test_backslash_in_path(self):
        """Backslashes are literal inside single quotes — should be preserved."""
        cmd = self._shell_escape("/Photos/back\\slash.jpg")
        self.assertEqual(cmd, "rm '/Photos/back\\slash.jpg'")


# ============================================================================
# SECTION 7: Camera Model Suffix + Destination Filename
# ============================================================================

class TestCameraModelSuffix(unittest.TestCase):
    """
    Tests for reconcile_nikon_archive.extract_camera_model_suffix() and
    compute_destination_filename().

    The model suffix is the mechanism that prevents DSCN filename collisions
    when two different Nikon cameras share overlapping counter ranges.
    DSCN2542.JPG from a S3100 must become DSCN2542_S3100.JPG; the same
    filename from a S3500 must become DSCN2542_S3500.JPG.
    """

    def setUp(self):
        import reconcile_nikon_archive as rna
        self.rna = rna

    def _suffix(self, model_str):
        return self.rna.extract_camera_model_suffix({"Model": model_str})

    def _dest_name(self, filename, suffix):
        return self.rna.compute_destination_filename(Path(filename), suffix)

    # -- extract_camera_model_suffix -----------------------------------------

    def test_coolpix_s3500(self):
        self.assertEqual(self._suffix("COOLPIX S3500"), "_S3500")

    def test_coolpix_s3100(self):
        self.assertEqual(self._suffix("COOLPIX S3100"), "_S3100")

    def test_nikon_d3000(self):
        self.assertEqual(self._suffix("NIKON D3000"), "_D3000")

    def test_plain_model_number(self):
        """Model string with no brand prefix — just the number."""
        self.assertEqual(self._suffix("D3000"), "_D3000")

    def test_empty_model_returns_no_suffix(self):
        self.assertEqual(self._suffix(""), "")

    def test_none_model_returns_no_suffix(self):
        self.assertEqual(self.rna.extract_camera_model_suffix({"Model": None}), "")

    def test_missing_model_key_returns_no_suffix(self):
        self.assertEqual(self.rna.extract_camera_model_suffix({}), "")

    def test_model_with_no_alphanumeric_token(self):
        """Pathological model string — should not crash."""
        self.assertEqual(self._suffix("---"), "")

    # -- compute_destination_filename ----------------------------------------

    def test_suffix_appended_before_extension(self):
        result = self._dest_name("DSCN2542.JPG", "_S3500")
        self.assertEqual(result, "DSCN2542_S3500.JPG")

    def test_empty_suffix_preserves_original_name(self):
        result = self._dest_name("DSCN2542.JPG", "")
        self.assertEqual(result, "DSCN2542.JPG")

    def test_lowercase_extension_preserved(self):
        result = self._dest_name("DSCN2542.jpg", "_S3100")
        self.assertEqual(result, "DSCN2542_S3100.jpg")

    def test_stem_with_underscores(self):
        """Existing underscores in the stem should not be affected."""
        result = self._dest_name("DSC_0001.JPG", "_D3000")
        self.assertEqual(result, "DSC_0001_D3000.JPG")


# ============================================================================
# SECTION 8: Event Cluster Folder Adoption (BUG-5)
# ============================================================================

class TestClusterFolderDayMapping(unittest.TestCase):
    """
    Cover map_days_to_cluster_folders(), which reports which calendar days are
    already owned by an existing "MM-DD Event" folder.

    This is the lookup that stops a re-import from stranding a handful of new
    photos loose in the month folder when the day they belong to already has an
    event folder sitting right next to them.
    """

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.month = self.temp_dir / "07 July"
        self.month.mkdir()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _map(self, year=2024):
        return create_event_folders.map_days_to_cluster_folders(self.month, year)

    def test_single_day_folder_claims_one_day(self):
        folder = self.month / "07-04 Event"
        folder.mkdir()

        result = self._map()

        self.assertEqual(result, {date(2024, 7, 4): folder})

    def test_span_folder_claims_every_day_inclusive(self):
        """A span folder owns both endpoints and everything between them."""
        folder = self.month / "07-18–07-20 Event"
        folder.mkdir()

        result = self._map()

        self.assertEqual(
            sorted(result),
            [date(2024, 7, 18), date(2024, 7, 19), date(2024, 7, 20)]
        )
        self.assertTrue(all(path == folder for path in result.values()))

    def test_span_crossing_month_boundary(self):
        """
        Spans may cross months — a cluster folder created in July can legitimately
        cover early August, since the folder lives in the span's first month.
        """
        folder = self.month / "07-30–08-02 Event"
        folder.mkdir()

        result = self._map()

        self.assertEqual(
            sorted(result),
            [date(2024, 7, 30), date(2024, 7, 31), date(2024, 8, 1), date(2024, 8, 2)]
        )

    def test_named_holiday_folders_ignored(self):
        """Holiday/birthday folders are handled by the earlier pass, not here."""
        (self.month / "2024 Fourth of July").mkdir()
        (self.month / "2024 J Birthday - 14").mkdir()

        self.assertEqual(self._map(), {})

    def test_manually_named_folders_ignored(self):
        """User-created descriptive folders must never be treated as clusters."""
        (self.month / "Escape Room").mkdir()
        (self.month / "The Rush Funplex").mkdir()

        self.assertEqual(self._map(), {})

    def test_files_are_not_mistaken_for_folders(self):
        (self.month / "07-04 Event").write_text("not a directory")

        self.assertEqual(self._map(), {})

    def test_malformed_names_ignored(self):
        """Single-digit, lowercase, and suffix-less variants must not match."""
        for name in ("7-4 Event", "07-04 event", "07-04", "07-04 Events", "Event 07-04"):
            with self.subTest(name=name):
                folder = self.month / name
                folder.mkdir()
                self.assertEqual(self._map(), {}, f"{name!r} should not be a cluster folder")
                folder.rmdir()

    def test_reversed_span_ignored_defensively(self):
        """An end date before the start date is nonsense — ignore, don't crash."""
        (self.month / "07-20–07-18 Event").mkdir()

        self.assertEqual(self._map(), {})

    def test_leap_day_span(self):
        february = self.temp_dir / "02 February"
        february.mkdir()
        folder = february / "02-28–03-01 Event"
        folder.mkdir()

        result = create_event_folders.map_days_to_cluster_folders(february, 2024)

        self.assertIn(date(2024, 2, 29), result, "2024 is a leap year")
        self.assertEqual(len(result), 3)


class TestClusterAdoption(unittest.TestCase):
    """
    Cover the BUG-5 fix in _detect_photo_clusters(): loose photos belonging to a
    day that already owns an event folder are routed into that folder regardless
    of the per-day threshold.

    Filenames carry YYYYMMDD_HHMMSS dates so _get_file_date() resolves them with
    zero I/O — no exiftool, no cache priming, fully hermetic.
    """

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.year_dir = self.temp_dir / "2024"
        self.year_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _month(self, month_name):
        folder = self.year_dir / month_name
        folder.mkdir(exist_ok=True)
        return folder

    def _add_photos(self, month_folder, datestamp, count, start=0):
        """Create `count` dated photo files directly inside month_folder."""
        created = []

        for index in range(start, start + count):
            path = month_folder / f"IMG_{datestamp}_{index:06d}.jpg"
            path.write_bytes(b"\xff\xd8\xff\xe0stub")
            created.append(path)

        return created

    def _clusters(self, threshold=35):
        return create_event_folders._detect_photo_clusters(self.year_dir, threshold)

    def test_sub_threshold_files_adopted_into_existing_folder(self):
        """
        The BUG-5 regression case: 3 new photos on a day that already has an
        event folder must be collected into it, not left stranded.
        """
        july = self._month("07 July")
        existing = july / "07-04 Event"
        existing.mkdir()
        loose = self._add_photos(july, "20240704", 3)

        results = self._clusters()

        self.assertEqual(len(results), 1, "expected exactly one adoption result")
        dest_dir, files = results[0]
        self.assertEqual(dest_dir, existing)
        self.assertEqual(sorted(files), sorted(loose))

    def test_sub_threshold_files_without_existing_folder_are_left_alone(self):
        """Unchanged behavior: a quiet day with no folder stays untouched."""
        july = self._month("07 July")
        self._add_photos(july, "20240704", 3)

        self.assertEqual(self._clusters(), [])

    def test_new_dense_day_still_creates_a_folder(self):
        """Unchanged behavior: a day at the threshold produces a new folder."""
        july = self._month("07 July")
        created = self._add_photos(july, "20240704", 35)

        results = self._clusters()

        self.assertEqual(len(results), 1)
        dest_dir, files = results[0]
        self.assertEqual(dest_dir, july / "07-04 Event")
        self.assertFalse(dest_dir.exists(), "new folder must not be created during detection")
        self.assertEqual(len(files), 35)

    def test_threshold_boundary_is_inclusive(self):
        """Exactly threshold-1 photos on a fresh day must not qualify."""
        july = self._month("07 July")
        self._add_photos(july, "20240704", 34)

        self.assertEqual(self._clusters(), [])

    def test_adopted_day_does_not_join_a_new_span(self):
        """
        A day owned by an existing folder is removed from span formation, so an
        adjacent dense day forms its own folder instead of silently absorbing
        the adopted day's files into a renamed span.
        """
        july = self._month("07 July")
        existing = july / "07-04 Event"
        existing.mkdir()
        adopted = self._add_photos(july, "20240704", 2)
        dense = self._add_photos(july, "20240705", 40)

        results = dict(self._clusters())

        self.assertEqual(sorted(results[existing]), sorted(adopted))
        self.assertEqual(sorted(results[july / "07-05 Event"]), sorted(dense))

    def test_span_folder_adopts_across_its_whole_range(self):
        """A span folder collects loose files from every day it covers."""
        july = self._month("07 July")
        existing = july / "07-18–07-20 Event"
        existing.mkdir()
        day18 = self._add_photos(july, "20240718", 2)
        day20 = self._add_photos(july, "20240720", 2, start=50)

        results = self._clusters()

        self.assertEqual(len(results), 1)
        dest_dir, files = results[0]
        self.assertEqual(dest_dir, existing)
        self.assertEqual(sorted(files), sorted(day18 + day20))

    def test_exclude_paths_still_respected(self):
        """
        Files claimed by the earlier holiday pass must not be adopted, or a
        dry-run would report the same file under two different destinations.
        """
        july = self._month("07 July")
        existing = july / "07-04 Event"
        existing.mkdir()
        loose = self._add_photos(july, "20240704", 3)

        results = create_event_folders._detect_photo_clusters(
            self.year_dir, threshold=35, exclude_paths=set(loose)
        )

        self.assertEqual(results, [])

    def test_destination_is_explicit_not_inferred_from_first_file(self):
        """
        Destination must be derived from the owning month folder rather than the
        first file's parent, so a misfiled photo cannot drag the folder with it.
        """
        july = self._month("07 July")
        august = self._month("08 August")
        existing = july / "07-30–08-02 Event"
        existing.mkdir()
        # A photo dated in the span but misfiled under August
        misfiled = self._add_photos(august, "20240801", 2)

        results = self._clusters()

        self.assertEqual(len(results), 1)
        dest_dir, files = results[0]
        self.assertEqual(dest_dir, existing, "must land in July's span folder, not August")
        self.assertEqual(sorted(files), sorted(misfiled))

    def test_no_photos_returns_empty(self):
        self._month("07 July")

        self.assertEqual(self._clusters(), [])

    def test_threshold_zero_disables_detection_but_not_adoption(self):
        """
        --event-threshold 0 disables *discovery* of new clusters. Adoption into
        folders that already exist is a correctness fix, not discovery, so it
        must still happen — otherwise the flag silently reintroduces BUG-5.
        """
        july = self._month("07 July")
        existing = july / "07-04 Event"
        existing.mkdir()
        loose = self._add_photos(july, "20240704", 3)
        self._add_photos(july, "20240709", 40)

        results = self._clusters(threshold=0)

        self.assertEqual(len(results), 1, "only the adoption should be reported")
        dest_dir, files = results[0]
        self.assertEqual(dest_dir, existing)
        self.assertEqual(sorted(files), sorted(loose))


# ============================================================================
# SECTION 9: EXIF-Only Duplicate Detection (BUG-6)
# ============================================================================

class TestAnalysisCacheMd5(unittest.TestCase):
    """
    Cover get_md5()/set_md5() on ImageAnalysisCache.

    A dedicated pair is needed because get_hashes() only returns when BOTH md5
    and phash are cached, and set_hashes() requires both. Content-hash dedupe
    needs the md5 alone, and must not clobber a phash computed by triage.
    """

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.image = self.temp_dir / "DSCN0001.JPG"
        self.image.write_bytes(b"\xff\xd8\xff\xe0" + b"payload" * 32)
        # ImageAnalysisCache takes the cache FILE path, not its directory —
        # get_analysis_cache() is what appends the filename to a directory.
        self.cache = ImageAnalysisCache(self.temp_dir / '.analysis_cache.json')

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_roundtrip(self):
        self.cache.set_md5(self.image, "deadbeef")

        self.assertEqual(self.cache.get_md5(self.image), "deadbeef")

    def test_missing_entry_returns_none(self):
        self.assertIsNone(self.cache.get_md5(self.image))

    def test_set_md5_preserves_phash_and_blur(self):
        """Must not clobber values written by the triage pipeline."""
        self.cache.set_hashes(self.image, "oldmd5", "phash123")
        self.cache.set_blur(self.image, 512.5)

        self.cache.set_md5(self.image, "newmd5")

        self.assertEqual(self.cache.get_md5(self.image), "newmd5")
        self.assertEqual(self.cache.get_hashes(self.image)["phash"], "phash123")
        self.assertEqual(self.cache.get_blur(self.image), 512.5)

    def test_invalidated_when_file_content_changes(self):
        """A rewritten file must not return its stale hash."""
        self.cache.set_md5(self.image, "deadbeef")
        time.sleep(0.01)
        self.image.write_bytes(b"\xff\xd8\xff\xe0" + b"different payload entirely")

        self.assertIsNone(self.cache.get_md5(self.image))

    def test_save_survives_a_vanished_directory(self):
        """
        A bulk flush at the end of a long run must not abort because one cached
        directory was pruned or its NAS share unmounted meanwhile. Raising here
        would discard every hash the run had computed.
        """
        self.cache.set_md5(self.image, "deadbeef")
        shutil.rmtree(self.temp_dir)

        self.cache.save()  # must not raise

        self.assertTrue(self.cache.dirty, "unsaved cache should stay marked dirty")

    def test_set_md5_on_missing_file_is_noop(self):
        """Storing a hash for a vanished path must not raise."""
        ghost = self.temp_dir / "gone.JPG"

        self.cache.set_md5(ghost, "deadbeef")

        self.assertIsNone(self.cache.get_md5(ghost))


class TestExifOnlyDuplicateDetection(unittest.TestCase):
    """
    Cover the BUG-6 fix: DuplicateDetector.find_duplicate() used to bail out
    immediately when the source filename carried no YYYYMMDD_HHMMSS stamp, never
    consulting the index at all.

    Organized Nikon files are named DSCN3089_S3500.JPG. Re-ingesting the same SD
    card therefore treated every file as new, and move_file() "resolved" the
    collision by appending _1 — silently doubling the archive.

    These tests build a throwaway archive so nothing touches real media.
    """

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.photo_dir = self.temp_dir / "Organized_Photos"
        self.video_dir = self.temp_dir / "Organized_Videos"
        self.month_dir = self.photo_dir / "2013" / "12 December"
        self.month_dir.mkdir(parents=True)
        self.video_dir.mkdir(parents=True)
        self.incoming = self.temp_dir / "TO_PROCESS"
        self.incoming.mkdir()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _archive(self, name, payload):
        path = self.month_dir / name
        path.write_bytes(payload)
        return path

    def _incoming(self, name, payload):
        path = self.incoming / name
        path.write_bytes(payload)
        return path

    def _detector(self):
        """
        Build a detector whose source-hash cache lives in the temp tree.

        Injecting the path keeps tests from writing .source_hash_cache.json into
        the repository working directory.
        """
        return duplicate_detector.DuplicateDetector(
            photo_dir=self.photo_dir,
            video_dir=self.video_dir,
            source_hash_cache=self.temp_dir / 'source_hashes.json'
        )

    def test_exif_only_reingest_is_detected(self):
        """
        The BUG-6 regression case: the exact same bytes, already archived under a
        model-suffixed name, arriving again with the camera's original name.
        """
        payload = b"\xff\xd8\xff\xe0" + b"nikon original" * 64
        archived = self._archive("DSCN3089_S3500.JPG", payload)
        source = self._incoming("DSCN3089.JPG", payload)

        result = self._detector().find_duplicate(source)

        self.assertTrue(result.is_duplicate, "byte-identical re-ingest must be caught")
        self.assertEqual(result.existing_path, archived)
        self.assertTrue(result.prefer_existing)

    def test_genuinely_new_exif_only_file_still_imports(self):
        """
        The failure mode that must never happen: skipping a new photo. A file not
        present in the archive must remain importable.
        """
        self._archive("DSCN3089_S3500.JPG", b"\xff\xd8\xff\xe0" + b"archived" * 64)
        source = self._incoming("DSCN9999.JPG", b"\xff\xd8\xff\xe0" + b"brand new photo" * 64)

        result = self._detector().find_duplicate(source)

        self.assertFalse(result.is_duplicate)

    def test_same_size_different_content_is_not_a_duplicate(self):
        """
        Proves the match is by content hash, not merely by size. Size is only a
        cheap pre-filter; two different photos of equal length must not collide.
        """
        self._archive("DSCN3089_S3500.JPG", b"A" * 4096)
        source = self._incoming("DSCN4444.JPG", b"B" * 4096)

        result = self._detector().find_duplicate(source)

        self.assertFalse(result.is_duplicate)

    def test_renamed_file_with_date_pattern_still_caught_by_content(self):
        """
        The 'renamed over the years' case: a date-stamped source whose pattern
        matches nothing in the archive, but which is byte-identical to a file
        archived under a completely different name.
        """
        payload = b"\xff\xd8\xff\xe0" + b"same bytes different name" * 32
        archived = self._archive("VacationPhoto.jpg", payload)
        source = self._incoming("IMG_20240704_120000.jpg", payload)

        result = self._detector().find_duplicate(source)

        self.assertTrue(result.is_duplicate)
        self.assertEqual(result.existing_path, archived)

    def test_date_pattern_fast_path_unchanged(self):
        """Existing behavior: a date-pattern + size match is still EXACT."""
        payload = b"\xff\xd8\xff\xe0" + b"dated" * 64
        archived = self._archive("P_20241215_165151_Clif.jpg", payload)
        source = self._incoming("P_20241215_165151.jpg", payload)

        result = self._detector().find_duplicate(source)

        self.assertTrue(result.is_duplicate)
        self.assertEqual(result.confidence, duplicate_detector.MatchConfidence.EXACT)
        self.assertEqual(result.existing_path, archived)

    def test_empty_archive_imports_everything(self):
        source = self._incoming("DSCN0001.JPG", b"\xff\xd8\xff\xe0" + b"lonely" * 64)

        result = self._detector().find_duplicate(source)

        self.assertFalse(result.is_duplicate)

    def test_missing_source_reports_cleanly(self):
        result = self._detector().find_duplicate(self.incoming / "nope.JPG")

        self.assertFalse(result.is_duplicate)
        self.assertIn("does not exist", result.reason)

    def test_source_directory_is_never_written_to(self):
        """
        Hashing an incoming file must not create a cache in the source tree.

        The source tree is routinely a mounted NAS share or a memory card. Writing
        there would violate --dry-run, may fail on read-only media, and the entry
        would be useless anyway since the file moves during import.
        """
        payload = b"\xff\xd8\xff\xe0" + b"nikon original" * 64
        self._archive("DSCN3089_S3500.JPG", payload)
        source = self._incoming("DSCN3089.JPG", payload)

        detector = self._detector()
        result = detector.find_duplicate(source)
        # Flushing must not create the file either
        detector.save_caches()

        self.assertTrue(result.is_duplicate, "sanity: the match should still work")
        self.assertFalse(
            (self.incoming / '.analysis_cache.json').exists(),
            "no cache file may be written into the source directory"
        )

    def test_source_hash_is_cached_outside_the_source_tree(self):
        """
        A source hash must be recorded in the project-local cache so that the
        usual dry-run-then-live-run sequence does not read every source byte
        twice — over 100 GB across the pending backlog, much of it over SMB.
        """
        payload = b"\xff\xd8\xff\xe0" + b"nikon original" * 64
        self._archive("DSCN3089_S3500.JPG", payload)
        source = self._incoming("DSCN3089.JPG", payload)

        detector = self._detector()
        detector.find_duplicate(source)
        detector.save_caches()

        cache_path = self.temp_dir / 'source_hashes.json'
        self.assertTrue(cache_path.exists(), "source hash cache should be written")

        stored = json.loads(cache_path.read_text())
        self.assertIn(str(source.resolve()), stored)
        self.assertEqual(
            stored[str(source.resolve())]['md5'],
            hashlib.md5(payload).hexdigest()
        )

    def test_cached_source_hash_is_actually_consulted(self):
        """
        Poison the cache with a wrong hash for an unchanged source file. If the
        cache is genuinely consulted, the match fails — which proves reads are
        being skipped rather than silently repeated.
        """
        payload = b"\xff\xd8\xff\xe0" + b"nikon original" * 64
        self._archive("DSCN3089_S3500.JPG", payload)
        source = self._incoming("DSCN3089.JPG", payload)

        stat_result = source.stat()
        cache_path = self.temp_dir / 'source_hashes.json'
        cache_path.write_text(json.dumps({
            str(source.resolve()): {
                'mtime': stat_result.st_mtime,
                'size': stat_result.st_size,
                'md5': "0" * 32,
            }
        }))

        result = self._detector().find_duplicate(source)

        self.assertFalse(result.is_duplicate, "poisoned cache entry should be trusted")

    def test_modified_source_invalidates_its_cached_hash(self):
        """A source file swapped between runs must be re-read, not trusted."""
        payload = b"\xff\xd8\xff\xe0" + b"nikon original" * 64
        archived = self._archive("DSCN3089_S3500.JPG", payload)
        source = self._incoming("DSCN3089.JPG", b"\xff\xd8\xff\xe0" + b"something else" * 64)

        detector = self._detector()
        detector.find_duplicate(source)
        detector.save_caches()

        # Replace the source with content that DOES match the archive
        time.sleep(0.01)
        source.write_bytes(payload)

        result = self._detector().find_duplicate(source)

        self.assertTrue(result.is_duplicate, "stale entry must not mask the new content")
        self.assertEqual(result.existing_path, archived)

    def test_saving_prunes_entries_for_vanished_sources(self):
        """
        An imported file moves out of the source tree, leaving a dead entry.
        Without pruning the cache would grow without bound across imports.
        """
        payload = b"\xff\xd8\xff\xe0" + b"nikon original" * 64
        self._archive("DSCN3089_S3500.JPG", payload)
        source = self._incoming("DSCN3089.JPG", payload)

        detector = self._detector()
        detector.find_duplicate(source)
        detector.save_caches()

        cache_path = self.temp_dir / 'source_hashes.json'
        self.assertIn(str(source.resolve()), json.loads(cache_path.read_text()))

        # Simulate the file having been imported, then hash something else so the
        # cache is dirty and therefore gets rewritten. The replacement must share
        # a size with an archived file, or the size pre-filter short-circuits
        # before any hashing happens and the cache stays clean.
        source.unlink()
        other = self._incoming("DSCN7777.JPG", b"\xff\xd8\xff\xe0" + b"X" * (len(payload) - 4))
        self.assertEqual(other.stat().st_size, len(payload), "sizes must collide")
        detector.find_duplicate(other)
        detector.save_caches()

        stored = json.loads(cache_path.read_text())
        self.assertNotIn(str(source.resolve()), stored, "dead entry should be pruned")
        self.assertIn(str(other.resolve()), stored)

    def test_corrupt_source_hash_cache_is_ignored(self):
        """A truncated cache must degrade to recomputation, not crash."""
        payload = b"\xff\xd8\xff\xe0" + b"nikon original" * 64
        archived = self._archive("DSCN3089_S3500.JPG", payload)
        source = self._incoming("DSCN3089.JPG", payload)
        (self.temp_dir / 'source_hashes.json').write_text("{ this is not json")

        result = self._detector().find_duplicate(source)

        self.assertTrue(result.is_duplicate)
        self.assertEqual(result.existing_path, archived)

    def test_content_match_survives_a_stale_cached_hash(self):
        """
        A cached md5 from before the file was replaced must not produce a false
        match. Cache validation keys on mtime and size, so a rewrite invalidates.
        """
        archived = self._archive("DSCN3089_S3500.JPG", b"\xff\xd8\xff\xe0" + b"original" * 64)
        cache = get_analysis_cache(archived.parent)
        cache.set_md5(archived, "0" * 32)

        # Replace the archived file's content; the cached hash is now a lie
        time.sleep(0.01)
        new_payload = b"\xff\xd8\xff\xe0" + b"replaced content" * 64
        archived.write_bytes(new_payload)

        source = self._incoming("DSCN3089.JPG", new_payload)
        result = self._detector().find_duplicate(source)

        self.assertTrue(result.is_duplicate, "should match on freshly computed hash")
        self.assertEqual(result.existing_path, archived)


# ============================================================================
# SECTION 10: Frame Discriminators (BUG-8)
# ============================================================================

class TestFrameSignature(unittest.TestCase):
    """
    Cover extract_frame_signature() and frame_signatures_conflict().

    extract_date_pattern() resolves only to the second. Two photographs taken in
    the same second, and burst frames which share the timestamp down to the
    millisecond, both collapse onto one pattern. Without these discriminators the
    importer matched a burst frame against its neighbour and skipped it, silently
    discarding a distinct photograph.

    Note: perceptual hashing was measured as an alternative and REJECTED. Across
    500 real skip decisions, true duplicates scored a pHash distance of 0 in every
    case, while mispaired burst frames scored 0 to 16 — one mispairing at distance
    0 despite an SSIM of 0.7597. Burst frames are the same scene, which is exactly
    what pHash is built to call identical, so it cannot separate them.
    """

    def _signature(self, filename):
        return duplicate_detector.extract_frame_signature(filename)

    def _conflict(self, name_a, name_b):
        return duplicate_detector.frame_signatures_conflict(name_a, name_b)

    # -- Extraction ----------------------------------------------------------

    def test_milliseconds_extracted(self):
        result = self._signature("IMG_20210616_120804026.jpg")
        self.assertEqual(result['milliseconds'], 26)
        self.assertIsNone(result['burst_index'])

    def test_burst_index_extracted(self):
        result = self._signature("IMG_20210908_190213263_BURST001_Nicole.jpg")
        self.assertEqual(result['milliseconds'], 263)
        self.assertEqual(result['burst_index'], 1)

    def test_burst_cover_frame(self):
        """The cover frame carries trailing markers after the index."""
        result = self._signature("IMG_20210908_190213263_BURST000_COVER_TOP.jpg")
        self.assertEqual(result['burst_index'], 0)

    def test_burst_with_trailing_noise(self):
        """Some Takeout names append extra digits after COVER_TOP."""
        result = self._signature("IMG_20200119_135649158_BURST000_COVER_TOP20_56_18.jpg")
        self.assertEqual(result['milliseconds'], 158)
        self.assertEqual(result['burst_index'], 0)

    def test_no_milliseconds_present(self):
        """Camcorder and organized names often stop at seconds."""
        result = self._signature("20210526_162641_Clif.jpg")
        self.assertIsNone(result['milliseconds'])
        self.assertIsNone(result['burst_index'])

    def test_collision_counter_is_not_milliseconds(self):
        """A trailing _1 collision counter must not be read as milliseconds."""
        result = self._signature("P_20241012_162741_1_Nicole.jpg")
        self.assertIsNone(result['milliseconds'])

    def test_video_milliseconds(self):
        result = self._signature("VID_20210526_162641582.mp4")
        self.assertEqual(result['milliseconds'], 582)

    # -- Conflict detection --------------------------------------------------

    def test_differing_burst_index_conflicts(self):
        """The dominant BUG-8 case: neighbouring burst frames."""
        self.assertTrue(self._conflict(
            "IMG_20210908_190213263_BURST000_COVER_TOP.jpg",
            "IMG_20210908_190213263_BURST001_Nicole.jpg"
        ))

    def test_differing_milliseconds_conflict(self):
        """Two photographs in the same second, different milliseconds."""
        self.assertTrue(self._conflict(
            "IMG_20210616_120804026.jpg",
            "IMG_20210616_120804916_Nicole.jpg"
        ))

    def test_identical_names_do_not_conflict(self):
        self.assertFalse(self._conflict(
            "IMG_20210616_120804026.jpg",
            "IMG_20210616_120804026_Nicole.jpg"
        ))

    def test_same_burst_index_does_not_conflict(self):
        """Cover marker aside, the same index is the same frame."""
        self.assertFalse(self._conflict(
            "IMG_20210908_190213263_BURST000_COVER_TOP.jpg",
            "IMG_20210908_190213263_BURST000_Nicole.jpg"
        ))

    def test_absent_field_is_never_a_conflict(self):
        """
        A field missing from either name proves nothing, so it must not block a
        legitimate match. This keeps the check purely additive.
        """
        self.assertFalse(self._conflict(
            "IMG_20210616_120804026.jpg",
            "20210616_120804_Clif.jpg"
        ))
        self.assertFalse(self._conflict(
            "20210616_120804_Clif.jpg",
            "IMG_20210616_120804916_Nicole.jpg"
        ))

    def test_zero_padding_ignored(self):
        """BURST01 and BURST001 are the same index."""
        self.assertFalse(self._conflict(
            "IMG_20210908_190213263_BURST01.jpg",
            "IMG_20210908_190213263_BURST001.jpg"
        ))

    def test_all_seventeen_observed_mispairings_are_caught(self):
        """
        Regression guard using the real filename pairs measured on 2026-07-30.
        Every one must be recognized as a conflict.
        """
        observed = [
            ("IMG_20210908_190213263_BURST000_COVER_TOP.jpg", "IMG_20210908_190213263_BURST001_Nicole.jpg"),
            ("IMG_20210616_120804026.jpg", "IMG_20210616_120804916_Nicole.jpg"),
            ("IMG_20220212_111944449_BURST001.jpg", "IMG_20220212_111944449_BURST000_COVER_TOP_Nicole.jpg"),
            ("IMG_20210810_133435242_BURST001.jpg", "IMG_20210810_133435242_BURST000_COVER_TOP_Nicole.jpg"),
            ("IMG_20210616_193055805_BURST001.jpg", "IMG_20210616_193055805_BURST000_COVER_TOP_Nicole.jpg"),
            ("IMG_20220212_095639412_BURST000_COVER_TOP.jpg", "IMG_20220212_095639412_BURST001_Nicole.jpg"),
            ("IMG_20211014_135402265_BURST000_COVER_TOP.jpg", "IMG_20211014_135402265_BURST001_Nicole.jpg"),
            ("IMG_20210909_153159811_BURST000_COVER_TOP.jpg", "IMG_20210909_153159811_BURST001_Nicole.jpg"),
            ("IMG_20220212_114351329_BURST000_COVER_TOP.jpg", "IMG_20220212_114351329_BURST001_Nicole.jpg"),
            ("IMG_20220116_100658351_BURST000_COVER_TOP.jpg", "IMG_20220116_100658351_BURST001_Nicole.jpg"),
            ("IMG_20210608_131933548_BURST001.jpg", "IMG_20210608_131933548_BURST000_COVER_TOP_Nicole.jpg"),
            ("IMG_20210614_130612098.jpg", "IMG_20210614_130612865_Nicole.jpg"),
            ("IMG_20220212_111945973_BURST001.jpg", "IMG_20220212_111945973_BURST000_COVER_TOP_Nicole.jpg"),
            ("IMG_20210911_153318141_BURST000_COVER_TOP.jpg", "IMG_20210911_153318141_BURST001_Nicole.jpg"),
            ("IMG_20210809_154723251.jpg", "IMG_20210809_154723165_Nicole.jpg"),
            ("IMG_20210803_162105044_BURST001.jpg", "IMG_20210803_162105044_BURST000_COVER_TOP_Nicole.jpg"),
            ("IMG_20211209_151932312_HDR.jpg", "IMG_20211209_151932885_HDR_Nicole.jpg"),
        ]

        self.assertEqual(len(observed), 17, "the measured set was 17 mispairings")

        for source_name, matched_name in observed:
            with self.subTest(source=source_name):
                self.assertTrue(
                    self._conflict(source_name, matched_name),
                    f"{source_name} vs {matched_name} must be a conflict"
                )


class TestBurstFramesNotSkipped(unittest.TestCase):
    """
    End-to-end cover for BUG-8 through find_duplicate().

    Burst frames of one scene compress to nearly identical sizes, so the 20%
    size gate passes and the source was declared a duplicate and skipped.
    """

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.photo_dir = self.temp_dir / "Organized_Photos"
        self.video_dir = self.temp_dir / "Organized_Videos"
        self.month_dir = self.photo_dir / "2021" / "09 September"
        self.month_dir.mkdir(parents=True)
        self.video_dir.mkdir(parents=True)
        self.incoming = self.temp_dir / "TO_PROCESS"
        self.incoming.mkdir()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _detector(self):
        return duplicate_detector.DuplicateDetector(
            photo_dir=self.photo_dir,
            video_dir=self.video_dir,
            source_hash_cache=self.temp_dir / 'source_hashes.json'
        )

    def test_neighbouring_burst_frame_is_not_a_duplicate(self):
        """
        BURST000 already archived; BURST001 arriving is a DIFFERENT photograph of
        near-identical size. It must be imported, not skipped.
        """
        (self.month_dir / "IMG_20210908_190213263_BURST000_COVER_TOP_Nicole.jpg").write_bytes(
            b"\xff\xd8\xff\xe0" + b"frame zero" * 400
        )
        source = self.incoming / "IMG_20210908_190213263_BURST001.jpg"
        source.write_bytes(b"\xff\xd8\xff\xe0" + b"frame one!" * 400)

        result = self._detector().find_duplicate(source)

        self.assertFalse(result.is_duplicate, "a different burst frame must be imported")

    def test_same_second_different_milliseconds_is_not_a_duplicate(self):
        (self.month_dir / "IMG_20210616_120804916_Nicole.jpg").write_bytes(
            b"\xff\xd8\xff\xe0" + b"later shot" * 400
        )
        source = self.incoming / "IMG_20210616_120804026.jpg"
        source.write_bytes(b"\xff\xd8\xff\xe0" + b"first shot" * 400)

        result = self._detector().find_duplicate(source)

        self.assertFalse(result.is_duplicate)

    def test_true_duplicate_of_the_same_frame_is_still_skipped(self):
        """The fix must not break legitimate matching of the same frame."""
        payload = b"\xff\xd8\xff\xe0" + b"one frame" * 400
        archived = self.month_dir / "IMG_20210908_190213263_BURST001_Nicole.jpg"
        archived.write_bytes(payload)
        source = self.incoming / "IMG_20210908_190213263_BURST001.jpg"
        source.write_bytes(payload)

        result = self._detector().find_duplicate(source)

        self.assertTrue(result.is_duplicate)
        self.assertEqual(result.existing_path, archived)

    def test_correct_frame_chosen_when_both_are_archived(self):
        """
        With BURST000 and BURST001 both archived, an incoming BURST001 must match
        BURST001 rather than whichever the index happens to list first.
        """
        payload_one = b"\xff\xd8\xff\xe0" + b"frame one!" * 400
        self.month_dir.joinpath("IMG_20210908_190213263_BURST000_COVER_TOP_Nicole.jpg").write_bytes(
            b"\xff\xd8\xff\xe0" + b"frame zero" * 400
        )
        archived_one = self.month_dir / "IMG_20210908_190213263_BURST001_Nicole.jpg"
        archived_one.write_bytes(payload_one)

        source = self.incoming / "IMG_20210908_190213263_BURST001.jpg"
        source.write_bytes(payload_one)

        result = self._detector().find_duplicate(source)

        self.assertTrue(result.is_duplicate)
        self.assertEqual(result.existing_path, archived_one)

    def test_byte_identical_wins_over_a_name_conflict(self):
        """
        If the bytes are identical the files ARE the same image, whatever the
        burst index claims. Falling through to import would create a duplicate.
        """
        payload = b"\xff\xd8\xff\xe0" + b"identical" * 400
        archived = self.month_dir / "IMG_20210908_190213263_BURST000_COVER_TOP_Nicole.jpg"
        archived.write_bytes(payload)
        source = self.incoming / "IMG_20210908_190213263_BURST001.jpg"
        source.write_bytes(payload)

        result = self._detector().find_duplicate(source)

        self.assertTrue(result.is_duplicate, "byte equality settles it")
        self.assertEqual(result.existing_path, archived)
        self.assertIn("despite name mismatch", result.reason)

    def test_names_without_discriminators_still_match(self):
        """
        Camcorder-style names carry no milliseconds or burst index, so the date
        pattern remains the only signal and behaviour is unchanged.
        """
        payload = b"\xff\xd8\xff\xe0" + b"camcorder" * 400
        archived = self.month_dir / "20210908_190213_Clif.jpg"
        archived.write_bytes(payload)
        source = self.incoming / "20210908_190213.jpg"
        source.write_bytes(payload)

        result = self._detector().find_duplicate(source)

        self.assertTrue(result.is_duplicate)
        self.assertEqual(result.existing_path, archived)


# ============================================================================
# SECTION 11: Recompression Keeper Gate (CONCERN-7 ruling)
# ============================================================================

class TestRecompressionKeeperGate(unittest.TestCase):
    """
    Cover the 0.92 SSIM ruling in the import path.

    Google's storage-saver pass produced copies 1.2x to 8x smaller at identical
    pixel dimensions. Those fall outside the 20% size gate, so before this gate
    existed the importer reported them as new — 3,725 of 4,403 files in the
    PhotoSync dry-run — and importing would have duplicated photographs already
    archived, event-filed and reviewed.

    Real images are generated rather than stubbed, because SSIM needs actual pixel
    data. They are kept small so the suite stays fast.
    """

    def setUp(self):
        if not duplicate_detector.OPENCV_AVAILABLE:
            self.skipTest("OpenCV required for SSIM")

        self.temp_dir = Path(tempfile.mkdtemp())
        self.photo_dir = self.temp_dir / "Organized_Photos"
        self.video_dir = self.temp_dir / "Organized_Videos"
        self.month_dir = self.photo_dir / "2021" / "05 May"
        self.month_dir.mkdir(parents=True)
        self.video_dir.mkdir(parents=True)
        self.incoming = self.temp_dir / "TO_PROCESS"
        self.incoming.mkdir()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _detector(self):
        return duplicate_detector.DuplicateDetector(
            photo_dir=self.photo_dir,
            video_dir=self.video_dir,
            source_hash_cache=self.temp_dir / 'source_hashes.json',
            ssim_cache=self.temp_dir / 'ssim.json'
        )

    # Quality pair chosen by measurement, not guesswork. On the fixture below it
    # yields a 3.1x size ratio (well outside the 20% gate) at SSIM 0.9401 — which
    # sits mid-range among the real pairs measured in the archive (0.9282-0.9942 at
    # ratios of 1.2x-8x). White noise was tried first and rejected: JPEG destroys it
    # outright, giving SSIM 0.77 and making the fixture unrepresentative.
    ARCHIVED_QUALITY = 80
    SOURCE_QUALITY = 95

    def _detailed_image(self, seed=0):
        """
        Build a photograph-like image: smooth gradients, a scattering of shapes, and
        mild grain.

        Detail is needed so that JPEG quality actually moves the file size, but pure
        noise is the wrong fixture — real photographs are largely smooth with
        localized detail, and they survive recompression far better than noise does.
        """
        import cv2
        import numpy as np

        rng = np.random.RandomState(seed)
        height, width = 480, 640
        rows, columns = np.mgrid[0:height, 0:width].astype(np.float32)

        image = np.zeros((height, width, 3), np.float32)
        image[..., 0] = 120 + 80 * np.sin(columns / 60.0) * np.cos(rows / 90.0)
        image[..., 1] = 110 + 70 * np.sin((columns + rows) / 70.0)
        image[..., 2] = 130 + 60 * np.cos(rows / 50.0)

        for _ in range(18):
            centre = (rng.randint(0, width), rng.randint(0, height))
            colour = tuple(int(value) for value in rng.randint(0, 255, 3))
            cv2.circle(image, centre, rng.randint(10, 50), colour, -1)

        image += rng.normal(0, 3, image.shape)

        return np.clip(image, 0, 255).astype(np.uint8)

    def _write_jpeg(self, path, image, quality):
        import cv2

        cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return path

    def test_heavy_recompression_of_same_photo_is_a_duplicate(self):
        """
        Same image at quality 95 and quality 25: dimensions identical, sizes far
        apart. Must be recognized as one photograph, keeping the archived copy.
        """
        image = self._detailed_image(seed=1)
        archived = self._write_jpeg(
            self.month_dir / "IMG_20210510_120254911_Nicole.jpg", image, self.ARCHIVED_QUALITY)
        source = self._write_jpeg(
            self.incoming / "IMG_20210510_120254911.jpg", image, self.SOURCE_QUALITY)

        ratio = source.stat().st_size / archived.stat().st_size
        self.assertGreater(ratio, 1.25, "sizes must fall outside the 20% gate")

        result = self._detector().find_duplicate(source)

        self.assertTrue(result.is_duplicate, "recompression must be caught")
        self.assertEqual(result.existing_path, archived)
        self.assertTrue(result.prefer_existing, "the archived copy is kept")
        self.assertIn("Same photograph", result.reason)

    def test_different_photo_at_same_dimensions_is_not_a_duplicate(self):
        """
        Two unrelated images of identical dimensions and very different sizes must
        still be imported. This is the failure that must never happen.
        """
        archived = self._write_jpeg(
            self.month_dir / "IMG_20210510_120254911_Nicole.jpg",
            self._detailed_image(seed=2), self.ARCHIVED_QUALITY)
        source = self._write_jpeg(
            self.incoming / "IMG_20210510_120254911.jpg",
            self._detailed_image(seed=99), self.SOURCE_QUALITY)

        self.assertNotEqual(archived.stat().st_size, source.stat().st_size)

        result = self._detector().find_duplicate(source)

        self.assertFalse(result.is_duplicate, "a different photograph must import")

    def test_dimension_mismatch_skips_the_ssim_check(self):
        """
        A crop or resize is a separate asset, not a recompression. Differing
        dimensions must short-circuit before any decode is attempted.
        """
        import cv2

        image = self._detailed_image(seed=3)
        archived = self._write_jpeg(
            self.month_dir / "IMG_20210510_120254911_Nicole.jpg", image, 90)
        cropped = image[:240, :320]
        source = self._write_jpeg(
            self.incoming / "IMG_20210510_120254911.jpg", cropped, 95)

        detector = self._detector()

        self.assertFalse(
            detector._is_same_photograph(source, archived),
            "different dimensions can never be the same photograph"
        )

    def test_within_size_tolerance_still_uses_the_fast_path(self):
        """Close sizes must not pay for an SSIM decode."""
        image = self._detailed_image(seed=4)
        archived = self._write_jpeg(
            self.month_dir / "IMG_20210510_120254911_Nicole.jpg", image, 90)
        source = self._write_jpeg(
            self.incoming / "IMG_20210510_120254911.jpg", image, 90)

        detector = self._detector()
        result = detector.find_duplicate(source)

        self.assertTrue(result.is_duplicate)
        self.assertEqual(detector._ssim_cache, {}, "no SSIM should have been computed")

    def test_ssim_verdict_is_cached_and_persisted(self):
        """
        Each verdict costs decoding two images, so it must survive the usual
        dry-run-then-live-run sequence.
        """
        image = self._detailed_image(seed=5)
        self._write_jpeg(self.month_dir / "IMG_20210510_120254911_Nicole.jpg", image, self.ARCHIVED_QUALITY)
        source = self._write_jpeg(self.incoming / "IMG_20210510_120254911.jpg", image, self.SOURCE_QUALITY)

        detector = self._detector()
        detector.find_duplicate(source)
        self.assertEqual(len(detector._ssim_cache), 1)
        detector.save_caches()

        cache_path = self.temp_dir / 'ssim.json'
        self.assertTrue(cache_path.exists())

        # A fresh detector must reuse the stored verdict
        reloaded = self._detector()
        self.assertEqual(len(reloaded._ssim_cache), 1)
        result = reloaded.find_duplicate(source)
        self.assertTrue(result.is_duplicate)

    def test_burst_conflict_still_wins_over_the_ssim_gate(self):
        """
        BUG-8 must not be reopened: a conflicting burst index rejects the candidate
        before the recompression check ever runs, even for the same scene.
        """
        image = self._detailed_image(seed=6)
        self._write_jpeg(
            self.month_dir / "IMG_20210510_120254911_BURST000_COVER_TOP_Nicole.jpg", image, self.ARCHIVED_QUALITY)
        source = self._write_jpeg(
            self.incoming / "IMG_20210510_120254911_BURST001.jpg", image, self.SOURCE_QUALITY)

        result = self._detector().find_duplicate(source)

        self.assertFalse(result.is_duplicate, "a different burst frame must import")

    def test_threshold_boundary_is_respected(self):
        """
        _is_same_photograph must follow SAME_PHOTO_SSIM_THRESHOLD rather than a
        hard-coded value, so the ruling can be retuned in one place.
        """
        image = self._detailed_image(seed=7)
        archived = self._write_jpeg(
            self.month_dir / "IMG_20210510_120254911_Nicole.jpg", image, self.ARCHIVED_QUALITY)
        source = self._write_jpeg(
            self.incoming / "IMG_20210510_120254911.jpg", image, self.SOURCE_QUALITY)

        detector = self._detector()
        score = detector._structural_similarity(source, archived)
        self.assertIsNotNone(score)

        with patch.object(duplicate_detector, 'SAME_PHOTO_SSIM_THRESHOLD', score + 0.01):
            self.assertFalse(detector._is_same_photograph(source, archived))

        with patch.object(duplicate_detector, 'SAME_PHOTO_SSIM_THRESHOLD', score - 0.01):
            self.assertTrue(detector._is_same_photograph(source, archived))


# ============================================================================
# SECTION 12: Removal History (do-not-resurrect guard)
# ============================================================================

class TestNormalizeMediaName(unittest.TestCase):
    """
    Cover normalize_media_name(), which is the risky half of the removal guard.

    Asymmetric stakes: a name reduced TOO far collides with unrelated files and
    blocks legitimate imports, while a name left too long merely fails to match and
    the file is imported for review again. So these tests lean hard on the
    over-stripping direction.

    A first version used `_\\d+$` for the collision counter and reduced
    IMG_20240101_120000_Nicole to "img" — every date-stamped file would have
    collapsed onto one key, blocking the entire import.
    """

    def _normalize(self, filename):
        return removal_history.normalize_media_name(filename)

    def test_timestamp_is_never_stripped(self):
        """The regression that would have blocked everything."""
        self.assertEqual(
            self._normalize("IMG_20240101_120000_Nicole.jpg"),
            "img_20240101_120000"
        )

    def test_time_group_alone_is_not_taken_for_a_counter(self):
        self.assertEqual(self._normalize("VID_20210526_162641.mp4"), "vid_20210526_162641")

    def test_stacked_model_person_and_counter(self):
        """The full suffix stack the pipeline can append."""
        self.assertEqual(self._normalize("DSCN1234_S3500_Clif_2.JPG"), "dscn1234")

    def test_model_and_person_without_counter(self):
        self.assertEqual(self._normalize("DSCN1234_S3500_Clif.JPG"), "dscn1234")

    def test_person_suffix_alone(self):
        self.assertEqual(self._normalize("Opportunities_Clif.jpg"), "opportunities")

    def test_edited_marker_is_preserved(self):
        """An edited variant is a separate asset from its original."""
        self.assertEqual(
            self._normalize("Opportunities-edited_Clif.jpg"),
            "opportunities-edited"
        )
        self.assertNotEqual(
            self._normalize("Opportunities-edited_Clif.jpg"),
            self._normalize("Opportunities_Clif.jpg")
        )

    def test_counter_before_person_suffix(self):
        """Different code paths append these in different orders."""
        self.assertEqual(
            self._normalize("P_20241012_162741_1_Nicole.jpg"),
            "p_20241012_162741"
        )

    def test_plain_name_untouched(self):
        self.assertEqual(self._normalize("geico.jpg"), "geico")

    def test_extension_ignored(self):
        self.assertEqual(self._normalize("photo.jpg"), self._normalize("photo.jpeg"))

    def test_distinct_timestamps_stay_distinct(self):
        """The core anti-collision property."""
        names = {
            self._normalize(f"IMG_2024010{index}_12000{index}_Nicole.jpg")
            for index in range(1, 6)
        }
        self.assertEqual(len(names), 5, "distinct photos must not share a key")

    def test_full_path_accepted(self):
        self.assertEqual(
            self._normalize("/some/where/Organized_Photos/2011/Fence-edited_Clif.jpeg"),
            "fence-edited"
        )


class TestRemovalHistory(unittest.TestCase):
    """Cover script parsing and the was_removed() lookup."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_script(self, name, body):
        path = self.temp_dir / name
        path.write_text(body)
        return path

    def test_parses_double_quoted_paths(self):
        """The style every existing exported script uses."""
        script = self._write_script("2026-02-10 remove_photos.sh", (
            '#!/bin/bash\n'
            '# Photo Triage - Files to Remove\n'
            '\n'
            'rm "/archive/2009/Opportunities-edited_Clif.jpg"\n'
            'rm "/archive/2011/Fence-edited_Clif.jpeg"\n'
        ))

        paths = removal_history.parse_removal_script(script)

        self.assertEqual(paths, [
            "/archive/2009/Opportunities-edited_Clif.jpg",
            "/archive/2011/Fence-edited_Clif.jpeg",
        ])

    def test_parses_single_quoted_paths_with_escapes(self):
        """The style produced after the shell-injection fix."""
        script = self._write_script("remove_photos.sh", (
            "#!/bin/bash\n"
            "rm '/archive/2011/Nicole'\\''s photo.jpg'\n"
            "rm '/archive/2011/plain.jpg'\n"
        ))

        paths = removal_history.parse_removal_script(script)

        self.assertEqual(paths, [
            "/archive/2011/Nicole's photo.jpg",
            "/archive/2011/plain.jpg",
        ])

    def test_non_rm_lines_ignored(self):
        script = self._write_script("remove_photos.sh", (
            '#!/bin/bash\n'
            '# Files: 1\n'
            'echo "starting"\n'
            'rm "/archive/keep.jpg"\n'
        ))

        self.assertEqual(removal_history.parse_removal_script(script), ["/archive/keep.jpg"])

    def test_missing_script_returns_empty(self):
        self.assertEqual(
            removal_history.parse_removal_script(self.temp_dir / "absent.sh"),
            []
        )

    def test_history_matches_across_suffix_differences(self):
        """
        The point of the whole module: a file removed under its archived name must
        be recognized when it arrives again under its source name.
        """
        self._write_script("remove_photos.sh",
                           'rm "/archive/2013/DSCN1234_S3500_Clif.JPG"\n')

        history = removal_history.RemovalHistory.from_directory(self.temp_dir)

        self.assertTrue(history.was_removed("DSCN1234.JPG"))
        self.assertTrue(history.was_removed("DSCN1234_S3500.JPG"))
        self.assertFalse(history.was_removed("DSCN9999.JPG"))

    def test_multiple_scripts_are_merged(self):
        self._write_script("a remove_photos.sh", 'rm "/archive/one_Clif.jpg"\n')
        self._write_script("b remove_photos.sh", 'rm "/archive/two_Nicole.jpg"\n')

        history = removal_history.RemovalHistory.from_directory(self.temp_dir)

        self.assertTrue(history.was_removed("one.jpg"))
        self.assertTrue(history.was_removed("two.jpg"))
        self.assertEqual(len(history.sources), 2)

    def test_absent_directory_yields_empty_history(self):
        """No scripts must mean no blocking, never an error."""
        history = removal_history.RemovalHistory.from_directory(self.temp_dir / "nope")

        self.assertEqual(len(history), 0)
        self.assertFalse(history.was_removed("anything.jpg"))

    def test_empty_history_blocks_nothing(self):
        history = removal_history.RemovalHistory()

        self.assertFalse(history.was_removed("IMG_20240101_120000.jpg"))

    def test_only_matching_glob_is_read(self):
        """Unrelated shell scripts in the directory must be left alone."""
        self._write_script("remove_photos.sh", 'rm "/archive/blocked_Clif.jpg"\n')
        self._write_script("backup.sh", 'rm "/archive/unrelated_Clif.jpg"\n')

        history = removal_history.RemovalHistory.from_directory(self.temp_dir)

        self.assertTrue(history.was_removed("blocked.jpg"))
        self.assertFalse(history.was_removed("unrelated.jpg"))


# ============================================================================
# SECTION 13: Source Liveness Guard
# ============================================================================

class TestSourceLivenessGuard(unittest.TestCase):
    """
    Cover the guard against a source share disappearing mid-run.

    Observed for real: undocking dropped the SMB share partway through a dry-run.
    Every remaining file became unreadable, find_duplicate() reported "source does
    not exist", and each one fell through and was counted as new — 4,114 files
    flipped from skip to import. On a live run that would have imported thousands of
    duplicates while reporting success.

    An unreadable source is an error, never a new file.
    """

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.incoming = self.temp_dir / "TO_PROCESS"
        self.incoming.mkdir()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_vanished_source_is_a_failure_not_an_import(self):
        """The core regression: absent source must never be reported as moved."""
        ghost = self.incoming / "IMG_20240101_120000.jpg"

        result, action = organize_archive.process_file(
            ghost, detector=None, dry_run=True
        )

        self.assertEqual(result, 'failed')
        self.assertEqual(action, 'source unreadable')

    def test_guard_runs_before_the_detector_is_touched(self):
        """
        Passing detector=None proves the check happens before duplicate detection.
        If the guard were later, this would raise AttributeError instead.
        """
        ghost = self.incoming / "DSCN0001.JPG"

        try:
            result, _ = organize_archive.process_file(ghost, detector=None, dry_run=True)
        except AttributeError:
            self.fail("the liveness guard must precede any detector use")

        self.assertEqual(result, 'failed')

    def test_existing_file_still_proceeds_past_the_guard(self):
        """
        The guard must not block a readable file. A stub detector reports no
        duplicate, so a dry run should report the file as moved.
        """
        source = self.incoming / "IMG_20240101_120000.jpg"
        source.write_bytes(b"\xff\xd8\xff\xe0" + b"payload" * 64)

        stub = MagicMock()
        stub.find_duplicate.return_value = duplicate_detector.DuplicateResult(
            is_duplicate=False,
            confidence=duplicate_detector.MatchConfidence.NONE,
            existing_path=None,
            prefer_existing=False,
            reason="no match"
        )

        # skip_damaged is disabled because this test is about the liveness guard,
        # not the integrity gate. The stub payload is not a decodable JPEG, so the
        # integrity gate would (correctly) quarantine it and mask what is under test.
        result, _ = organize_archive.process_file(
            source, detector=stub, dry_run=True, skip_damaged=False
        )

        self.assertEqual(result, 'moved')
        stub.find_duplicate.assert_called_once()


class TestDamagedSourceQuarantine(unittest.TestCase):
    """
    Cover the integrity gate that holds a damaged source out of the archive.

    Motivation: the health scan found 3 truncated JPEGs and a zero-byte file in the
    PhotoSync source tree. Importing one of those would place a damaged copy in the
    archive where a later review could choose it over a healthy one — and the review
    tools rank by blur and resolution, neither of which notices truncation.

    The gate sits immediately before the move, so only files that would actually be
    imported pay for the decode.
    """

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.incoming = self.temp_dir / "TO_PROCESS"
        self.incoming.mkdir()

        self.stub = MagicMock()
        self.stub.find_duplicate.return_value = duplicate_detector.DuplicateResult(
            is_duplicate=False,
            confidence=duplicate_detector.MatchConfidence.NONE,
            existing_path=None,
            prefer_existing=False,
            reason="no match"
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _real_jpeg(self, name):
        import cv2
        import numpy as np

        path = self.incoming / name
        cv2.imwrite(str(path), np.full((64, 64, 3), 96, dtype=np.uint8))
        return path

    def test_intact_file_imports(self):
        source = self._real_jpeg("IMG_20240101_120000.jpg")

        result, _ = organize_archive.process_file(
            source, detector=self.stub, dry_run=True
        )

        self.assertEqual(result, 'moved')

    def test_truncated_file_is_quarantined(self):
        """The exact failure found in the PhotoSync tree."""
        intact = self._real_jpeg("IMG_20240102_120000.jpg")
        payload = intact.read_bytes()
        intact.write_bytes(payload[:-30])

        result, action = organize_archive.process_file(
            intact, detector=self.stub, dry_run=True
        )

        self.assertEqual(result, 'damaged')
        self.assertIn('truncated', action)

    def test_zero_byte_file_is_quarantined(self):
        empty = self.incoming / "IMG_20240103_120000.jpg"
        empty.touch()

        result, action = organize_archive.process_file(
            empty, detector=self.stub, dry_run=True
        )

        self.assertEqual(result, 'damaged')
        self.assertIn('empty', action)

    def test_override_allows_a_damaged_import(self):
        """--import-damaged must still work for a partial file worth keeping."""
        intact = self._real_jpeg("IMG_20240104_120000.jpg")
        intact.write_bytes(intact.read_bytes()[:-30])

        result, _ = organize_archive.process_file(
            intact, detector=self.stub, dry_run=True, skip_damaged=False
        )

        self.assertEqual(result, 'moved')

    def test_gate_runs_only_after_duplicate_detection(self):
        """
        A skipped duplicate must not pay for a decode. If the source is a known
        duplicate the detector short-circuits and the integrity check never runs.
        """
        source = self._real_jpeg("IMG_20240105_120000.jpg")
        source.write_bytes(source.read_bytes()[:-30])   # damaged, but a duplicate

        self.stub.find_duplicate.return_value = duplicate_detector.DuplicateResult(
            is_duplicate=True,
            confidence=duplicate_detector.MatchConfidence.EXACT,
            existing_path=Path("/archive/already_here.jpg"),
            prefer_existing=True,
            reason="Byte-identical"
        )

        result, _ = organize_archive.process_file(
            source, detector=self.stub, dry_run=True
        )

        self.assertEqual(result, 'skipped', "duplicates skip before the integrity gate")


# ============================================================================
# SECTION 14: Media Health Checks
# ============================================================================

class TestMediaHealthChecks(unittest.TestCase):
    """
    Cover check_media_health.py's per-file verdicts.

    Regression context: the first run of this tool reported 103 archived files as
    "unreadable", every one of them a HEIC. They were all perfectly readable — the
    module simply never registered PIL's HEIF opener. A health checker that cries
    wolf on an entire image format is worse than none at all, so the registration is
    now covered by a test.
    """

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _intact_jpeg(self, name="intact.jpg"):
        """Write a small but genuinely valid JPEG."""
        import cv2
        import numpy as np

        path = self.temp_dir / name
        image = np.full((64, 64, 3), 128, dtype=np.uint8)
        cv2.imwrite(str(path), image)
        return path

    def test_heif_opener_is_registered(self):
        """
        The 103-false-positive regression. PIL must recognise HEIC on import of this
        module, otherwise every iPhone photo is reported as damaged.
        """
        if not check_media_health.HEIC_AVAILABLE:
            self.skipTest("pillow-heif not installed")

        from PIL import Image

        self.assertIn(
            'HEIF', Image.registered_extensions().get('.heic', 'HEIF'),
            "PIL must map .heic to the HEIF plugin"
        )

    def test_truncated_file_is_detected(self):
        intact = self._intact_jpeg()
        payload = intact.read_bytes()
        truncated = self.temp_dir / "truncated.jpg"
        truncated.write_bytes(payload[:-40])

        _, status, detail = check_media_health.check_file(truncated)

        self.assertEqual(status, 'truncated')
        self.assertIn('truncated', detail.lower())

    def test_intact_file_passes(self):
        _, status, _ = check_media_health.check_file(self._intact_jpeg())

        self.assertEqual(status, 'ok')

    def test_empty_file_is_flagged_separately(self):
        """Zero bytes is its own category, not lumped in with unreadable."""
        empty = self.temp_dir / "empty.jpg"
        empty.touch()

        _, status, detail = check_media_health.check_file(empty)

        self.assertEqual(status, 'empty')
        self.assertEqual(detail, 'zero bytes')

    def test_non_image_masquerading_as_one(self):
        bogus = self.temp_dir / "bogus.jpg"
        bogus.write_text("this is not an image")

        _, status, _ = check_media_health.check_file(bogus)

        self.assertEqual(status, 'unreadable')

    def test_unvalidatable_format_is_not_called_damaged(self):
        """A format we cannot check must not be reported as broken."""
        document = self.temp_dir / "notes.txt"
        document.write_text("some text")

        _, status, _ = check_media_health.check_file(document)

        self.assertEqual(status, 'not_checked')

    def test_zip_crc_corruption_is_caught(self):
        """
        The strongest check available, and the only one that can see damage inherited
        from a pre-ZFS NAS: ZIP stores a CRC32 per member, so a single flipped byte is
        provable rather than guessed at.
        """
        import zipfile

        path = self.temp_dir / "document.docx"

        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('word/document.xml', '<xml>' + 'content' * 200 + '</xml>')

        payload = bytearray(path.read_bytes())

        # Flip a byte inside the compressed member data, past the local header
        payload[len(payload) // 2] ^= 0xFF
        path.write_bytes(bytes(payload))

        _, status, detail = check_media_health.check_file(path)

        self.assertEqual(status, 'corrupt')
        self.assertIn('CRC mismatch', detail)

    def test_intact_zip_family_file_passes(self):
        import zipfile

        path = self.temp_dir / "sheet.xlsx"

        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('xl/workbook.xml', '<workbook/>')

        _, status, _ = check_media_health.check_file(path)

        self.assertEqual(status, 'ok')

    def test_non_zip_masquerading_as_office_document(self):
        path = self.temp_dir / "fake.docx"
        path.write_text("this is not a zip container")

        _, status, _ = check_media_health.check_file(path)

        self.assertEqual(status, 'unreadable')

    def test_truncated_pdf_is_detected(self):
        """A PDF must end with %%EOF; its absence means the write was cut short."""
        path = self.temp_dir / "truncated.pdf"
        path.write_bytes(b"%PDF-1.4\n" + b"object data " * 100)

        _, status, detail = check_media_health.check_file(path)

        self.assertEqual(status, 'truncated')
        self.assertIn('%%EOF', detail)

    def test_complete_pdf_passes(self):
        path = self.temp_dir / "complete.pdf"
        path.write_bytes(b"%PDF-1.4\n" + b"object data " * 100 + b"\n%%EOF\n")

        _, status, _ = check_media_health.check_file(path)

        self.assertEqual(status, 'ok')

    def test_audio_only_file_with_a_video_extension_is_flagged(self):
        """
        The blind spot that let eight files pass as healthy home movies. 2010/00033.MTS
        holds 94 MB of MP3 audio, and ffprobe calls it a valid 2,959-second mp3 stream
        — so "does this decode" answers yes. The footage is not damaged, it is absent,
        and no transcode recovers it.
        """
        source = self.temp_dir / "audio.mp3"
        target = self.temp_dir / "fake.MTS"

        made = subprocess.run(
            ['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono',
             '-t', '1', '-c:a', 'libmp3lame', '-y', str(source)],
            capture_output=True, check=False
        )

        if made.returncode != 0 or not source.exists():
            self.skipTest("ffmpeg cannot produce an mp3 here")

        shutil.copy(source, target)

        status, detail = check_media_health.check_video(target)

        self.assertEqual(status, 'not a video')
        self.assertIn('no video stream', detail)

    def test_container_disagreeing_with_extension_is_flagged(self):
        """
        2010/00045.MTS is an m4v. The container is intact, so every damage check passes,
        but the file is not the recording its name claims.
        """
        source = self.temp_dir / "clip.mp4"
        target = self.temp_dir / "fake2.MTS"

        made = subprocess.run(
            ['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=32x32:d=1',
             '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-y', str(source)],
            capture_output=True, check=False
        )

        if made.returncode != 0 or not source.exists():
            self.skipTest("ffmpeg cannot produce an mp4 here")

        shutil.copy(source, target)

        status, detail = check_media_health.check_video(target)

        self.assertEqual(status, 'wrong container')
        self.assertIn('expected mpegts', detail)

    def test_matching_container_still_passes(self):
        """Guard against the extension check rejecting healthy files wholesale."""
        source = self.temp_dir / "good.mp4"

        made = subprocess.run(
            ['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=32x32:d=1',
             '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-y', str(source)],
            capture_output=True, check=False
        )

        if made.returncode != 0 or not source.exists():
            self.skipTest("ffmpeg not available")

        status, _ = check_media_health.check_video(source)

        self.assertEqual(status, 'ok')

    def test_deep_video_check_is_opt_in(self):
        """
        The container probe stays the default because a full decode is expensive, but
        it cannot see mid-stream damage. Five AVCHD files passed the fast check with
        clean durations while carrying 46-244 decode errors, then lost footage when
        transcoded — one dropped 72 of its 103 seconds.
        """
        self.assertTrue(hasattr(check_media_health, 'check_video_deep'))

        # check_file must not decode deeply unless asked
        import inspect

        signature = inspect.signature(check_media_health.check_file)
        self.assertIn('deep', signature.parameters)
        self.assertFalse(signature.parameters['deep'].default)

    def test_deep_check_sees_damage_the_fast_check_misses(self):
        """
        The whole point of the deep check, demonstrated on a real corrupted stream.

        A file with mid-stream damage still reports a clean duration, so the container
        probe calls it fine. Only decoding reveals the problem — which matters because
        transcoding such a file loses footage silently.
        """
        import shutil as shutil_module
        import subprocess

        if shutil_module.which('ffmpeg') is None:
            self.skipTest("ffmpeg required")

        clip = self.temp_dir / "clip.mp4"
        subprocess.run(
            ['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=duration=3:size=320x240:rate=30',
             '-c:v', 'libx264', '-y', str(clip)],
            check=True, capture_output=True, timeout=120
        )

        healthy_fast = check_media_health.check_video(clip)
        healthy_deep = check_media_health.check_video_deep(clip)
        self.assertEqual(healthy_fast[0], 'ok')
        self.assertEqual(healthy_deep[0], 'ok', "an intact clip must pass both checks")

        # Corrupt a run of bytes well inside the stream, past the header
        payload = bytearray(clip.read_bytes())
        start = len(payload) // 2
        payload[start:start + 600] = b'\x00' * 600
        damaged = self.temp_dir / "damaged.mp4"
        damaged.write_bytes(bytes(payload))

        fast = check_media_health.check_video(damaged)
        deep = check_media_health.check_video_deep(damaged)

        self.assertNotEqual(
            deep[0], 'ok',
            f"deep check must notice mid-stream damage (got {deep})"
        )
        self.assertEqual(
            fast[0], 'ok',
            "documents the gap: the container probe still calls this file fine"
        )

    def test_muxer_noise_is_not_counted_as_damage(self):
        """
        Decoding to `-f null -` still runs an output muxer, and that muxer complains
        about timestamps it dislikes. Those complaints describe the command, not the
        file.

        This is not hypothetical tuning: a first pass over the archive flagged 325
        files and 323 of them were this single warning. A checker that calls 11.5% of
        a healthy archive damaged only teaches you to ignore it.
        """
        noise = [
            '[null @ 0x98ec1f700] Application provided invalid, non monotonic DTS',
            'Application provided invalid, non monotonic DTS to muxer in stream 0',
        ]
        real = [
            '[h264 @ 0xa46c49c00] error while decoding MB 50 66, bytestream 24721',
            '[mjpeg @ 0xab8c84e00] overread 8',
            '[aac @ 0x982cace00] channel element 0.0 duplicate',
            '[h264 @ 0xc7ac48e00] missing picture in access unit with size 6412',
        ]

        for line in noise:
            with self.subTest(line=line[:40]):
                self.assertTrue(check_media_health._is_muxer_noise(line))

        for line in real:
            with self.subTest(line=line[:40]):
                self.assertFalse(
                    check_media_health._is_muxer_noise(line),
                    "a decoder-reported error must still count"
                )

    def test_truncation_tolerance_stays_disabled(self):
        """
        PIL's LOAD_TRUNCATED_IMAGES must remain off. Turning it on anywhere in the
        process would make every short file decode "successfully" and defeat the
        entire purpose of this module.
        """
        from PIL import ImageFile

        self.assertFalse(ImageFile.LOAD_TRUNCATED_IMAGES)


# ============================================================================
# SECTION 15: Camcorder Source-Deletion Guard and Pre-Screen
# ============================================================================

class TestStagingPathGuard(unittest.TestCase):
    """
    Cover is_staging_path(), which decides whether deleting a source is allowed.

    camcorder_convert deletes each original after a successful conversion, and
    keep_originals defaults to False. That is correct for a TO_PROCESS copy and
    catastrophic for an archive: pointed at the NAS home-movies share it would have
    deleted 675 original MTS files, 94 GB, which are the only copy.
    """

    def _staging(self, path):
        return camcorder_convert.is_staging_path(path)

    def test_staging_directory_permits_deletion(self):
        self.assertTrue(self._staging("/repo/TO_PROCESS/CAMCORDER/00001.MTS"))

    def test_nested_under_staging_still_permits(self):
        self.assertTrue(self._staging("/repo/TO_PROCESS/batch/2013/deep/00001.MTS"))

    def test_nas_share_refuses_deletion(self):
        """The case that motivated the guard."""
        self.assertFalse(self._staging("/Volumes/home-movies/2009/00006.MTS"))

    def test_organized_archive_refuses_deletion(self):
        self.assertFalse(self._staging("/repo/Organized_Videos/2013/09 September/x.mp4"))

    def test_similarly_named_directory_is_not_staging(self):
        """Only an exact path component counts, not a substring of one."""
        self.assertFalse(self._staging("/repo/TO_PROCESS_OLD/00001.MTS"))
        self.assertFalse(self._staging("/repo/MY_TO_PROCESS_BACKUP/00001.MTS"))


class TestDurationPlausibility(unittest.TestCase):
    """
    Cover duration_is_plausible(), which rejects corrupt timing metadata.

    Real case: 2010/00057.MTS reports 66,315 seconds (18.4 hours) for a 142 MB file
    while only 610 frames decode. Handing that duration to the encoder risks a
    run-away job that consumes a night and produces garbage.
    """

    def _check(self, duration, size):
        return camcorder_convert.duration_is_plausible(Path("x.MTS"), duration, size)

    def test_real_corrupt_case_is_rejected(self):
        plausible, why = self._check(66315.725589, 142_600_000)

        self.assertFalse(plausible)
        self.assertIn('corrupt', why)

    def test_normal_avchd_is_accepted(self):
        """225 MB over 100 seconds is about 18 Mbps -- squarely normal AVCHD."""
        plausible, _ = self._check(100.0, 225_000_000)

        self.assertTrue(plausible)

    def test_short_clip_is_accepted(self):
        """A 2 MB two-second clip is still a sane 8 Mbps."""
        plausible, _ = self._check(2.0, 2_000_000)

        self.assertTrue(plausible)

    def test_zero_duration_is_rejected(self):
        plausible, why = self._check(0, 100_000_000)

        self.assertFalse(plausible)
        self.assertIn('zero or missing', why)

    def test_missing_duration_is_rejected(self):
        plausible, _ = self._check(None, 100_000_000)

        self.assertFalse(plausible)

    def test_threshold_is_honoured_not_hardcoded(self):
        """The bound must come from the constant so it can be retuned in one place."""
        threshold = camcorder_convert.MIN_PLAUSIBLE_BITRATE_BPS
        size = 10_000_000

        # Just above the bound
        plausible, _ = self._check(size * 8 / (threshold * 1.1), size)
        self.assertTrue(plausible)

        # Just below it
        plausible, _ = self._check(size * 8 / (threshold * 0.9), size)
        self.assertFalse(plausible)


# ============================================================================
# SECTION 16: Reconciler Video Awareness (BUG-7)
# ============================================================================

class TestReconcilerVideoAwareness(unittest.TestCase):
    """
    Cover the BUG-7 fix in reconcile_nikon_archive.py.

    The reconciler indexed only Organized_Photos, which broke it twice over. Every
    video was reported as NEW_CONTENT — on the Nikon archive that was 11 of 11
    reported-new files, a 100% false-positive rate on the tool's only actionable
    output — and the destination it predicted for a video named the photo root, which
    the importer would never use.

    Both stem from the same cause: a transcode shares no bytes with its source, so
    MD5 cannot see it, while the naming convention preserves the original stem
    (DSCN3019.AVI becomes 20131004_161529_DSCN3019_S3100.h265.mp4).
    """

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.photos = self.temp_dir / "Organized_Photos"
        self.videos = self.temp_dir / "Organized_Videos"
        (self.photos / "2013" / "10 October").mkdir(parents=True)
        (self.videos / "2013" / "10 October").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _stem_index(self):
        return reconcile_nikon_archive.build_archive_stem_index([self.photos, self.videos])

    # -- Video detection -----------------------------------------------------

    def test_avchd_is_a_video(self):
        self.assertTrue(reconcile_nikon_archive.is_video_source(Path("00001.MTS")))
        self.assertTrue(reconcile_nikon_archive.is_video_source(Path("00001.m2ts")))

    def test_standard_video_formats(self):
        for name in ("clip.mp4", "clip.MOV", "clip.avi", "clip.m4v"):
            with self.subTest(name=name):
                self.assertTrue(reconcile_nikon_archive.is_video_source(Path(name)))

    def test_photos_are_not_videos(self):
        for name in ("DSCN0001.JPG", "IMG_1234.heic", "scan.png"):
            with self.subTest(name=name):
                self.assertFalse(reconcile_nikon_archive.is_video_source(Path(name)))

    # -- Transcode detection -------------------------------------------------

    def test_transcode_found_by_embedded_stem(self):
        """The exact real case: DSCN3019.AVI archived as an H.265 transcode."""
        archived = self.videos / "2013" / "10 October" / "20131004_161529_DSCN3019_S3100.h265.mp4"
        archived.write_bytes(b"transcoded content")

        match = reconcile_nikon_archive.find_transcoded_match(
            Path("/nas/2013/DSCN3019.AVI"), self._stem_index()
        )

        self.assertEqual(match, archived)

    def test_unrelated_stem_finds_nothing(self):
        (self.videos / "2013" / "10 October" / "20131004_161529_DSCN3019_S3100.h265.mp4").write_bytes(b"x")

        match = reconcile_nikon_archive.find_transcoded_match(
            Path("/nas/2013/DSCN9999.AVI"), self._stem_index()
        )

        self.assertIsNone(match)

    def test_short_stems_are_refused(self):
        """
        A stem like "001" would match half the archive by coincidence, so anything
        under four characters is rejected outright rather than risking a false skip.
        """
        (self.videos / "2013" / "10 October" / "20131004_161529_001_CAM.h265.mp4").write_bytes(b"x")

        match = reconcile_nikon_archive.find_transcoded_match(
            Path("/nas/001.MTS"), self._stem_index()
        )

        self.assertIsNone(match)

    def test_stem_as_the_last_token_still_matches(self):
        """
        With no model suffix the original stem lands last and carries ".h265" from the
        compound extension. Splitting on dots as well as underscores keeps it findable.
        """
        archived = self.videos / "2013" / "10 October" / "20131004_161529_DSCN3019.h265.mp4"
        archived.write_bytes(b"x")

        match = reconcile_nikon_archive.find_transcoded_match(
            Path("/nas/2013/DSCN3019.AVI"), self._stem_index()
        )

        self.assertEqual(match, archived)

    def test_partial_token_does_not_match(self):
        """
        DSCN301 must not match DSCN3019 — matching is on whole underscore-delimited
        tokens, not substrings, or a shorter stem would swallow a longer one.
        """
        (self.videos / "2013" / "10 October" / "20131004_161529_DSCN3019_S3100.h265.mp4").write_bytes(b"x")

        match = reconcile_nikon_archive.find_transcoded_match(
            Path("/nas/DSCN301.AVI"), self._stem_index()
        )

        self.assertIsNone(match)

    def test_stem_index_spans_both_roots(self):
        """Photos and videos must both be indexed, which is the root of BUG-7."""
        (self.photos / "2013" / "10 October" / "DSCN3089_S3500.JPG").write_bytes(b"p")
        (self.videos / "2013" / "10 October" / "20131004_161529_DSCN3019_S3100.h265.mp4").write_bytes(b"v")

        index = self._stem_index()

        self.assertIn("dscn3089_s3500", index)
        self.assertIn("20131004_161529_dscn3019_s3100.h265", index)
        # Note the trailing ".h265": a compound extension leaves part of itself
        # in the stem, which is why matching tokenizes on dots as well.

    # -- Destination routing -------------------------------------------------

    def test_video_destination_uses_the_video_root(self):
        destination = reconcile_nikon_archive.compute_destination_path(
            Path("/nas/2013/DSCN3019.AVI"),
            datetime(2013, 10, 4, 16, 15, 29),
            "_S3100",
            self.photos,
            video_archive_dir=self.videos,
        )

        self.assertIsNotNone(destination)
        self.assertTrue(
            str(destination).startswith(str(self.videos)),
            f"video must land under Organized_Videos, got {destination}"
        )

    def test_photo_destination_still_uses_the_photo_root(self):
        destination = reconcile_nikon_archive.compute_destination_path(
            Path("/nas/2013/DSCN3089.JPG"),
            datetime(2013, 12, 25, 10, 0, 0),
            "_S3500",
            self.photos,
            video_archive_dir=self.videos,
        )

        self.assertTrue(str(destination).startswith(str(self.photos)))

    def test_video_root_omitted_falls_back_safely(self):
        """Without a video root the old behavior stands rather than crashing."""
        destination = reconcile_nikon_archive.compute_destination_path(
            Path("/nas/2013/DSCN3019.AVI"),
            datetime(2013, 10, 4, 16, 15, 29),
            "",
            self.photos,
        )

        self.assertTrue(str(destination).startswith(str(self.photos)))


# ============================================================================
# SECTION 17: Foreign Content Splice Detection
# ============================================================================

class TestTransportStreamSplices(unittest.TestCase):
    """
    Synthetic transport streams, because the real damaged files are on a share that
    may not be mounted and are far too large to commit.

    A valid AVCHD packet here is a 4-byte TP_extra_header followed by 0x47 and 187
    payload bytes, which is all the structure the detector actually relies on.
    """

    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.root = Path(self.temp)

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def make_ts(self, packets, phase_shift=0):
        """Build `packets` worth of valid BDAV transport stream bytes."""
        data = bytearray(b'\x00' * phase_shift)

        for index in range(packets):
            data += b'\x00\x00\x00\x00'
            data += bytes([detect_splices.SYNC_BYTE])
            # Payload deliberately avoids 0x47 so phase detection is unambiguous
            data += bytes([(index * 7 + offset) % 0x46 for offset in range(187)])

        return bytes(data)

    def make_mp3_like(self, length):
        """Bytes carrying MP3 framing and a LAME tag, as a donor file's blocks would."""
        block = bytearray()

        while len(block) < length:
            block += b'\xff\xfb\x90\x64'
            block += bytes([(len(block) + step) % 251 for step in range(413)])

        data = bytearray(block[:length])
        data[5000:5008] = b'LAME3.99'
        return bytes(data)

    def write(self, name, payload):
        """Write a file and return its path."""
        path = self.root / name
        path.write_bytes(payload)
        return path

    def test_clean_transport_stream_produces_no_finding(self):
        """A continuous stream must not be flagged, or the tool is useless at scale."""
        path = self.write('clean.MTS', self.make_ts(9000))

        self.assertIsNone(detect_splices.analyze_file(path))

    def test_foreign_tail_is_detected_and_located(self):
        """Video followed by foreign data is the core case."""
        video = self.make_ts(9000)
        path = self.write('spliced.MTS', video + self.make_mp3_like(6 << 20))

        finding = detect_splices.analyze_file(path)

        self.assertIsNotNone(finding)
        self.assertEqual(finding['status'], 'spliced')
        # The splice is located within one window of the true boundary
        self.assertLess(abs(finding['splice_offset'] - len(video)),
                        detect_splices.WINDOW_BYTES)

    def test_entirely_foreign_file_reports_total_loss(self):
        """
        An .MTS holding only MP3 data is the finding ffprobe cannot give us: it reports
        such a file as a healthy audio stream, which is why the health check passed it.
        """
        path = self.write('allmp3.MTS', self.make_mp3_like(8 << 20))

        finding = detect_splices.analyze_file(path)

        self.assertIsNotNone(finding)
        self.assertEqual(finding['status'], 'entirely foreign')
        self.assertEqual(finding['fraction_foreign'], 1.0)

    def test_foreign_transport_stream_identified_by_phase(self):
        """
        Blocks from another .MTS still hold sync, just at a different phase. Detecting
        that is what distinguishes a donor video from unstructured corruption.
        """
        host = self.make_ts(9000)
        donor = self.make_ts(40000, phase_shift=60)
        path = self.write('donor.MTS', host + donor)

        finding = detect_splices.analyze_file(path)

        self.assertIsNotNone(finding)
        self.assertEqual(finding['foreign_verdict'], 'another transport stream')

    def test_resumed_video_is_not_counted_as_definitely_lost(self):
        """
        Video resuming after a foreign region lands on a different packet grid, because
        the resumed data has no reason to fall back onto the original phase. Counting
        that as destroyed reported a 35%-recoverable file as 99.5% lost.

        So `bytes_foreign` must cover only data with no transport-stream structure at
        any phase, leaving phase-shifted video in its own ambiguous bucket.
        """
        good = self.make_ts(9000)
        path = self.write(
            'multi.MTS',
            good + self.make_mp3_like(4 << 20) + good + self.make_mp3_like(4 << 20)
        )

        finding = detect_splices.analyze_file(path)
        size = path.stat().st_size

        self.assertIsNotNone(finding)
        self.assertEqual(finding['status'], 'spliced')
        # The two MP3 blocks are 8 MB of an ~11.8 MB file; the confident number must
        # stay close to that rather than swallowing the whole remainder.
        self.assertLess(finding['bytes_foreign'], 0.80 * size)
        self.assertGreater(finding['bytes_foreign'], 0.50 * size)

    def test_phase_shifted_video_is_reported_separately(self):
        """
        Donor transport-stream blocks and a resumed recording are indistinguishable by
        phase, so they share a bucket that is deliberately kept out of the loss figure.
        """
        host = self.make_ts(9000)
        donor = self.make_ts(40000, phase_shift=60)
        path = self.write('donor.MTS', host + donor)

        finding = detect_splices.analyze_file(path)

        self.assertIsNotNone(finding)
        self.assertGreater(finding['bytes_phase_shifted'], 0)
        self.assertEqual(finding['bytes_foreign'], 0)

    def test_single_corrupt_packet_is_not_called_a_splice(self):
        """
        Ordinary damage must not masquerade as foreign content, because the two lead to
        opposite decisions: transcode-and-salvage versus the footage is gone.
        """
        data = bytearray(self.make_ts(9000))
        # Break a handful of scattered sync bytes
        for packet in (100, 400, 900, 1500):
            data[packet * 192 + 4] = 0x00

        path = self.write('glitch.MTS', bytes(data))

        self.assertIsNone(detect_splices.analyze_file(path))


class TestJpegLogicalEnd(unittest.TestCase):
    """
    Trailing-data detection for photos, where the false-positive risk is highest: motion
    photos and MPO pairs append a legitimate second payload by design.
    """

    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.root = Path(self.temp)

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def make_jpeg(self):
        """A minimal but structurally valid JPEG with a real scan segment."""
        parts = [
            b'\xff\xd8',                                  # SOI
            b'\xff\xe0' + (16).to_bytes(2, 'big') + b'JFIF\x00' + b'\x00' * 9,
            b'\xff\xdb' + (67).to_bytes(2, 'big') + b'\x00' + bytes(range(64)),
            b'\xff\xda' + (8).to_bytes(2, 'big') + b'\x01\x01\x00\x00\x00\x00',
            # Entropy-coded data including a stuffed 0xFF00 and a restart marker
            b'\x12\x34\xff\x00\x56\xff\xd0\x78\x9a',
            b'\xff\xd9',                                  # EOI
        ]
        return b''.join(parts)

    def write(self, name, payload):
        path = self.root / name
        path.write_bytes(payload)
        return path

    def test_logical_end_walks_past_stuffed_bytes(self):
        """A naive search for 0xFFD9 finds compressed data by chance; the walk must not."""
        image = self.make_jpeg()

        self.assertEqual(detect_splices.jpeg_logical_end(image), len(image))

    def test_fill_bytes_before_a_restart_marker_do_not_derail_the_walk(self):
        """
        A run of 0xFF is legal padding before a marker, not a marker itself. Treating it
        as one derailed the walk on every JPEG using restart intervals: four archived
        scans reported "no end marker" despite decoding perfectly and ending in 0xFFD9,
        and one file invented 307 KB of "trailing data" from its own image data.
        """
        parts = [
            b'\xff\xd8',
            b'\xff\xdd' + (4).to_bytes(2, 'big') + b'\x00\x10',   # DRI
            b'\xff\xda' + (8).to_bytes(2, 'big') + b'\x01\x01\x00\x00\x00\x00',
            b'\x12\x34',
            b'\xff\xff\xff\xd0',                                  # fill bytes, then RST0
            b'\x56\x78',
            b'\xff\x00\x9a',                                      # stuffed literal
            b'\xff\xd9',
        ]
        image = b''.join(parts)

        self.assertEqual(detect_splices.jpeg_logical_end(image), len(image))

    def test_samsung_trailer_is_not_flagged(self):
        """
        Samsung Extended Format appears on 2,036 archived photos. Flagging it made the
        report 2,040 findings long with nothing real in it.
        """
        trailer = (b'\x00\x00\x01\x0a\x0e\x00\x00\x00Image_UTC_Data1658328390848'
                   b'SEFH' + b'\x00' * 200)
        path = self.write('galaxy.jpg', self.make_jpeg() + trailer)

        self.assertIsNone(detect_splices.analyze_file(path))

    def test_motorola_camera_trailer_is_not_flagged(self):
        """
        The single largest false-positive source: 1,914 archived photos carry a
        Motorola camera-settings block after End-of-Image. Together with the Samsung
        trailer this covered 3,950 of the 3,959 original findings.
        """
        trailer = (b'<camera>appversion=8.18.8.0_230518,cameraid=3,'
                   b'modeid=AUTO_CAPTURE_MODE,flashoption=FLASH_OFF</camera>')
        path = self.write('moto.jpg', self.make_jpeg() + trailer + b'\x00' * 100)

        self.assertIsNone(detect_splices.analyze_file(path))

    def test_tiny_foreign_buffer_is_not_called_a_transport_stream(self):
        """
        Over a buffer shorter than a few dozen packets, one chance 0x47 scores a perfect
        sync ratio. That produced 20 confident donor-video verdicts on metadata scraps.
        """
        verdict, _ = detect_splices.classify_foreign(b'\x47' + b'\x00' * 97)

        self.assertNotEqual(verdict, 'another transport stream')

    def test_clean_jpeg_has_no_finding(self):
        """Baseline, so trailing-data findings mean something."""
        path = self.write('clean.jpg', self.make_jpeg())

        self.assertIsNone(detect_splices.analyze_file(path))

    def test_unexplained_trailing_data_is_flagged(self):
        """Foreign bytes appended past End-of-Image are the photo-side symptom."""
        path = self.write('tail.jpg', self.make_jpeg() + b'\xab\xcd' * 40000)

        finding = detect_splices.analyze_file(path)

        self.assertIsNotNone(finding)
        self.assertEqual(finding['status'], 'trailing data')

    def test_motion_photo_trailer_is_not_flagged(self):
        """
        Google and Samsung phones append an MP4 after the JPEG on purpose. Flagging
        these would bury real findings under thousands of healthy files.
        """
        trailer = b'\x00\x00\x00\x18ftypmp42' + b'\x00' * 60000
        path = self.write('motion.jpg', self.make_jpeg() + trailer)

        self.assertIsNone(detect_splices.analyze_file(path))

    def test_mpo_second_image_is_not_flagged(self):
        """An appended second JPEG is a stereo pair, not corruption."""
        path = self.write('pair.jpg', self.make_jpeg() + self.make_jpeg() + b'\x00' * 40000)

        self.assertIsNone(detect_splices.analyze_file(path))


class TestIsobmffBoxWalk(unittest.TestCase):
    """
    Box-chain verification for the archive's own MP4 outputs, which is how a splice
    would show up in a file this pipeline produced.
    """

    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.root = Path(self.temp)

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def box(self, kind, payload):
        """Assemble one ISOBMFF box."""
        return (len(payload) + 8).to_bytes(4, 'big') + kind + payload

    def write(self, name, payload):
        path = self.root / name
        path.write_bytes(payload)
        return path

    def test_valid_box_chain_passes(self):
        """A well-formed chain must produce no finding."""
        data = self.box(b'ftyp', b'mp42' + b'\x00' * 8) + self.box(b'moov', b'\x00' * 512)
        path = self.write('good.mp4', data + self.box(b'mdat', b'\x00' * 4096))

        self.assertIsNone(detect_splices.analyze_file(path))

    def test_broken_chain_is_flagged(self):
        """Foreign bytes where a box header belongs break the chain unambiguously."""
        data = self.box(b'ftyp', b'mp42' + b'\x00' * 8)
        path = self.write('bad.mp4', data + b'\xff\xfe\xfd\xfc' * 20000)

        finding = detect_splices.analyze_file(path)

        self.assertIsNotNone(finding)
        self.assertEqual(finding['status'], 'spliced')

    def test_box_running_past_end_of_file_reports_truncation(self):
        """
        Truncation is a different verdict from splicing, and conflating them would send
        a recoverable file to the wrong pile.
        """
        header = (1 << 20).to_bytes(4, 'big') + b'mdat'
        path = self.write('short.mp4', self.box(b'ftyp', b'mp42\x00\x00\x00\x00')
                          + header + b'\x00' * 256)

        finding = detect_splices.analyze_file(path)

        self.assertIsNotNone(finding)
        self.assertEqual(finding['status'], 'truncated')

    def test_zero_size_terminator_box_is_accepted(self):
        """Size 0 legitimately means 'extends to end of file'."""
        trailing = (0).to_bytes(4, 'big') + b'mdat' + b'\x00' * 8192
        path = self.write('term.mp4', self.box(b'ftyp', b'mp42\x00\x00\x00\x00') + trailing)

        self.assertIsNone(detect_splices.analyze_file(path))


# ============================================================================
# SECTION 18: Damaged-Media Rescue
# ============================================================================

class TestRescueClassification(unittest.TestCase):
    """
    The mapping step that decides what a damaged file actually holds.

    Context: the originating SD cards are gone, so these sources are the only surviving
    copy and a wrong classification silently discards the last version of something.
    Two files ffprobe called completely unreadable turned out to hold transport-stream
    video and carveable JPEGs respectively.
    """

    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.root = Path(self.temp)

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def make_ts(self, packets, phase_shift=0):
        """Valid BDAV transport-stream bytes."""
        data = bytearray(b'\x00' * phase_shift)

        for index in range(packets):
            data += b'\x00\x00\x00\x00'
            data += bytes([rescue_damaged_media.SYNC_BYTE])
            data += bytes([(index * 7 + offset) % 0x46 for offset in range(187)])

        return bytes(data)

    def test_transport_stream_is_recognised(self):
        chunk = self.make_ts(600)

        self.assertEqual(rescue_damaged_media.classify_window(chunk), 'ts')

    def test_transport_stream_recognised_at_any_phase(self):
        """
        Carved regions never begin on the donor's packet boundary, so a phase-locked
        check would classify real recoverable video as unknown and throw it away.
        """
        chunk = self.make_ts(600, phase_shift=77)

        self.assertEqual(rescue_damaged_media.classify_window(chunk), 'ts')

    def test_mp3_region_is_recognised(self):
        block = bytearray()

        while len(block) < (1 << 18):
            block += b'\xff\xfb\x90\x64'
            block += bytes([(len(block) + step) % 251 for step in range(413)])

        block[5000:5004] = b'LAME'

        self.assertEqual(rescue_damaged_media.classify_window(bytes(block)), 'mp3')

    def test_random_data_is_not_claimed(self):
        """
        Over-claiming is the expensive error: it sends unusable regions to a slow
        transcode and fills the rescue folder with files that must be reviewed.
        """
        import hashlib

        noise = bytearray()
        seed = b'seed'

        while len(noise) < (1 << 18):
            seed = hashlib.sha256(seed).digest()
            noise += seed

        self.assertEqual(rescue_damaged_media.classify_window(bytes(noise)), 'unknown')

    def test_short_buffer_is_not_classified(self):
        """A buffer too small to hold a packet grid cannot support any verdict."""
        self.assertEqual(rescue_damaged_media.classify_window(b'\x47' * 64), 'unknown')

    def test_sync_alignment_trims_to_a_packet_boundary(self):
        """
        ffmpeg often refuses a transport stream that does not start on a packet
        boundary, so a carved fragment has to be trimmed before it is handed over.
        """
        stream = self.make_ts(200)
        offset = rescue_damaged_media.align_to_sync(b'\x11\x22\x33\x44' + stream)

        self.assertEqual(offset, 8)

    def test_region_profile_finds_a_buried_stream(self):
        """
        The 2009/00006.MTS case: unreadable at the start, with transport-stream video
        three quarters of the way in. ffprobe only inspects the beginning, so anything
        relying on it alone reports the file as empty.
        """
        import hashlib

        noise = bytearray()
        seed = b'x'

        while len(noise) < (6 << 20):
            seed = hashlib.sha256(seed).digest()
            noise += seed

        path = self.root / 'buried.MTS'
        path.write_bytes(bytes(noise) + self.make_ts(40000))

        regions = rescue_damaged_media.profile_carve_regions(path)
        kinds = [kind for kind, _, _ in regions]

        self.assertIn('ts', kinds)
        # And the stream must be found past the noise, not at offset 0
        first_ts = next(start for kind, start, _ in regions if kind == 'ts')
        self.assertGreater(first_ts, 4 << 20)


class TestRescueOutputNaming(unittest.TestCase):
    """
    Naming and byte-exactness. A partial recovery sitting beside real footage must be
    impossible to mistake for a clean original.
    """

    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.root = Path(self.temp)

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_damaged_marker_is_present(self):
        self.assertEqual(rescue_damaged_media.DAMAGED_MARKER, '_DAMAGED')

    def test_year_is_taken_from_the_source_path(self):
        year = rescue_damaged_media.year_for(Path('/Volumes/home-movies/2009/00030.MTS'))

        self.assertEqual(year, '2009')

    def test_unfoldered_source_still_gets_a_destination(self):
        """The 'New-after reset' files sit outside any year folder and must not vanish."""
        year = rescue_damaged_media.year_for(
            Path('/Volumes/home-movies/2011 Summer Vacation/New-after reset/00024.MTS'))

        self.assertEqual(year, 'undated')

    def test_prefix_cut_is_byte_exact(self):
        """
        The valid prefix is intact AVCHD and must stay that way -- the cut is a byte
        copy, never a re-encode, so nothing is lost before ffmpeg ever sees it.
        """
        payload = bytes(range(256)) * 400
        source = self.root / 'source.MTS'
        source.write_bytes(payload)
        destination = self.root / 'prefix.mts'

        written = rescue_damaged_media.cut_valid_prefix(source, 12345, destination)

        self.assertEqual(written, 12345)
        self.assertEqual(destination.read_bytes(), payload[:12345])

    def test_carved_jpegs_must_decode(self):
        """
        A naive SOI-to-EOI carve yields mostly garbage. Garbage in a rescue folder is
        worse than nothing, because every file there has to be reviewed by hand.
        """
        import cv2
        import numpy as np

        # Noise, not a flat fill: a solid-colour JPEG compresses to a couple of KB and
        # falls under the size floor, which would test the floor rather than the carve.
        real = self.root / 'real.jpg'
        generator = np.random.default_rng(1234)
        cv2.imwrite(str(real),
                    generator.integers(0, 256, (600, 600, 3), dtype=np.uint8))
        valid = real.read_bytes()
        self.assertGreater(len(valid), rescue_damaged_media.MIN_CARVED_JPEG)

        # A decoy that has the markers but no decodable image between them
        decoy = b'\xff\xd8\xff\xe0' + b'\x41' * 40000 + b'\xff\xd9'
        blob = decoy + b'\x00' * 500 + valid

        source = Path('/nas/2009/00026.MTS')
        captured = datetime(2009, 12, 25, 19, 41, 2)
        saved = rescue_damaged_media.carve_jpegs(blob, self.root, source, captured, 1)

        self.assertEqual(len(saved), 1)
        self.assertIn('_DAMAGED', saved[0][0].name)
        # Date first, so the file sorts chronologically beside the rest of the archive
        self.assertTrue(saved[0][0].name.startswith('20091225_194102_00026'))


class TestRescueNaming(unittest.TestCase):
    """
    Output naming. Both rules here came from reviewing the first imported batch.
    """

    def test_capture_date_leads_the_filename(self):
        """
        The archive is ordered by date -- neighbouring files are named
        `20091225_202803_CAM.h265.mp4` -- so a name starting with the source's reel
        number sorts to the top of the folder and breaks the chronology.
        """
        name = rescue_damaged_media.output_name(
            Path('/nas/2009/00006.MTS'), datetime(2009, 12, 25, 19, 12, 20), '.mp4')

        self.assertEqual(name, '20091225_191220_00006_DAMAGED.mp4')

    def test_provenance_and_damage_marker_survive(self):
        """The source reel and the partial-recovery warning both have to remain."""
        name = rescue_damaged_media.output_name(
            Path('/nas/2010/00057.MTS'), datetime(2010, 3, 16, 20, 29, 2), '.mp4', 2)

        self.assertIn('00057', name)
        self.assertIn('_DAMAGED', name)
        self.assertTrue(name.endswith('_extracted2.mp4'))

    def test_missing_date_still_produces_a_usable_name(self):
        """A source with no recoverable date must not crash the rescue."""
        name = rescue_damaged_media.output_name(Path('/nas/x/00099.MTS'), None, '.mp4')

        self.assertEqual(name, '00099_DAMAGED.mp4')

    def test_numbering_is_sequential_over_surviving_outputs(self):
        """
        The bug this replaces: numbering ran over regions *found*, so a region that
        failed validation burned its number. 00057 shipped as extracted 2, 3 and 4 with
        no 1, because its first region did not decode. Numbering now follows the files
        that actually exist.
        """
        source = Path('/nas/2010/00057.MTS')
        captured = datetime(2010, 3, 16, 20, 29, 2)
        produced = []

        for region_succeeded in (False, True, True):
            name = rescue_damaged_media.output_name(
                source, captured, '.mp4', len(produced) + 1)

            if region_succeeded:
                produced.append(name)

        self.assertTrue(produced[0].endswith('_extracted1.mp4'))
        self.assertTrue(produced[1].endswith('_extracted2.mp4'))


# ============================================================================
# SECTION 19: Import Preflight
# ============================================================================

class StubDuplicateResult:
    """Minimal stand-in so preflight tests do not need the real 38k-file archive index."""

    def __init__(self, is_duplicate=False, existing_path=None):
        self.is_duplicate = is_duplicate
        self.existing_path = existing_path


class StubDetector:
    """Returns a fixed verdict, isolating preflight logic from duplicate detection."""

    def __init__(self, result=None):
        self.result = result or StubDuplicateResult()

    def find_duplicate(self, path):
        return self.result


class TestImportPreflight(unittest.TestCase):
    """
    Predicting an import before running it.

    Every one of these cases is a real defect the rescued files would have caused: 29
    files dated to the day they were rescued, audio routed into the photo archive, and
    five re-encodes of footage already archived that the duplicate detector cleared
    because a re-encode shares no bytes with its archived counterpart.
    """

    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.root = Path(self.temp)

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def make_file(self, name, when=None):
        """Create a file, optionally back-dating its mtime."""
        path = self.root / name
        path.write_bytes(b'\x00' * 2048)

        if when is not None:
            stamp = when.timestamp()
            os.utime(path, (stamp, stamp))

        return path

    def test_recent_mtime_is_a_blocker(self):
        """
        An mtime of today is the processing date, not a capture date. This is what sent
        all 29 rescued files into a single 2026 folder.
        """
        path = self.make_file('rescued.mp4', datetime.now())

        prediction = preflight_import.predict(path, StubDetector(), {})
        severities = [severity for severity, _ in prediction['issues']]

        self.assertIn('BLOCKER', severities)

    def test_old_mtime_is_only_a_warning(self):
        """
        A years-old mtime is weak evidence but usually roughly right. Calling it a
        blocker would bury the blockers that matter.
        """
        path = self.make_file('old.mp4', datetime(2010, 4, 14, 8, 13, 30))

        prediction = preflight_import.predict(path, StubDetector(), {})
        severities = [severity for severity, _ in prediction['issues']]

        self.assertNotIn('BLOCKER', severities)
        self.assertIn('WARNING', severities)

    def test_audio_has_no_archive_destination(self):
        """
        is_video_file() says an mp3 is not a video, so the organizer sends it to
        Organized_Photos. Nearly six hours of recovered audio would have gone there.
        """
        path = self.make_file('recovered.mp3', datetime(2010, 1, 24))

        prediction = preflight_import.predict(path, StubDetector(), {})
        messages = ' '.join(message for _, message in prediction['issues'])

        self.assertIn('audio', messages.lower())
        self.assertIn('BLOCKER', [severity for severity, _ in prediction['issues']])

    def test_already_archived_content_is_blocked_by_provenance(self):
        """
        The case no heuristic catches. 00017_DAMAGED.mp4 is a re-encode of footage
        already archived from the same source, sharing no bytes with it, so the
        duplicate detector clears it. Only the source mapping proves the redundancy.
        """
        path = self.make_file('00017_DAMAGED.mp4', datetime(2009, 12, 25, 20, 28))
        provenance = {
            '00017_DAMAGED.mp4': ('/Volumes/home-movies/2009/00017.MTS',
                                  '2009/12 December/20091225_202803_CAM.h265.mp4'),
        }

        prediction = preflight_import.predict(path, StubDetector(), provenance)
        blockers = [message for severity, message in prediction['issues']
                    if severity == 'BLOCKER']

        self.assertTrue(any('already archived' in message for message in blockers))

    def test_redundancy_notes_that_the_duplicate_detector_misses_it(self):
        """
        The warning matters as much as the blocker: it explains why the existing safety
        net does not catch this, so the check is not later assumed redundant.
        """
        path = self.make_file('00065_DAMAGED.mp4', datetime(2010, 4, 7))
        provenance = {'00065_DAMAGED.mp4': ('/nas/00065.MTS', '2010/04 April/x.mp4')}

        prediction = preflight_import.predict(path, StubDetector(), provenance)
        warnings = [message for severity, message in prediction['issues']
                    if severity == 'WARNING']

        self.assertTrue(any('does NOT catch' in message for message in warnings))

    def test_new_content_with_a_real_date_is_clean(self):
        """A file with nothing wrong must produce no issues, or the tool is noise."""
        path = self.make_file('IMG_20240101_120000.mp4')

        prediction = preflight_import.predict(path, StubDetector(), {})

        self.assertEqual(prediction['issues'], [])
        self.assertEqual(prediction['date'].year, 2024)

    def test_destination_uses_the_organizers_own_logic(self):
        """
        Predictions must call the real functions. Reimplementing them would let the
        prediction drift from behaviour, which is the one thing this tool cannot do.
        """
        path = self.make_file('IMG_20091225_202803.mp4')

        prediction = preflight_import.predict(path, StubDetector(), {})
        expected = organize_archive.get_destination_folder(
            organize_archive.get_creation_date(path)[0], True)

        self.assertEqual(prediction['destination'], expected)

    def test_multiple_outputs_from_one_source_are_flagged(self):
        """
        A rescue can extract the same footage two ways -- a whole-file decode and a carve
        of the same bytes -- producing outputs that look independent. 00050 gave a direct
        extraction of 2,065 frames beside two carved files holding 2,007 between them,
        and importing all three would have filed one clip as three.
        """
        first = self.make_file('00050_DAMAGED.mp4', datetime(2010, 2, 14))
        second = self.make_file('00050_DAMAGED_carved1.mp4', datetime(2010, 2, 14))
        provenance = {
            '00050_DAMAGED.mp4': ('/nas/2010/00050.MTS', None),
            '00050_DAMAGED_carved1.mp4': ('/nas/2010/00050.MTS', None),
        }

        predictions = [preflight_import.predict(p, StubDetector(), provenance)
                       for p in (first, second)]
        preflight_import.find_sibling_redundancy(predictions)

        for prediction in predictions:
            messages = [m for severity, m in prediction['issues'] if severity == 'WARNING']
            self.assertTrue(any('2 outputs rescued from' in m for m in messages))

    def test_single_output_source_is_not_flagged(self):
        """
        Siblings are sometimes genuinely the only option: 00006's carve is its sole
        output because direct extraction produced nothing. One output is never redundant.
        """
        path = self.make_file('00006_DAMAGED_carved1.mp4', datetime(2009, 12, 25))
        provenance = {'00006_DAMAGED_carved1.mp4': ('/nas/2009/00006.MTS', None)}

        predictions = [preflight_import.predict(path, StubDetector(), provenance)]
        preflight_import.find_sibling_redundancy(predictions)

        messages = [m for _, m in predictions[0]['issues']]
        self.assertFalse(any('outputs rescued from' in m for m in messages))

    def test_two_inputs_claiming_one_destination_are_flagged(self):
        """
        The organizer resolves collisions by appending _1, silently, so two versions of
        one recording end up side by side looking like two takes.
        """
        first = self.make_file('IMG_20091225_202803.mp4')
        second = self.root / 'sub'
        second.mkdir()
        duplicate = second / 'IMG_20091225_202803.mp4'
        duplicate.write_bytes(b'\x00' * 2048)

        predictions = [preflight_import.predict(p, StubDetector(), {})
                       for p in (first, duplicate)]
        internal, _ = preflight_import.find_collisions(predictions)

        self.assertEqual(len(internal), 1)
        self.assertEqual(len(next(iter(internal.values()))), 2)


# ============================================================================
# SECTION 20: Conversion Verification and Splice Attribution
# ============================================================================

class TestConversionVerification(unittest.TestCase):
    """
    The two traps in verify_conversions.py, both of which produced wrong reports before
    being fixed and are invisible without a test.
    """

    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.root = Path(self.temp)

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_ssim_and_psnr_keys_both_resolve(self):
        """
        analyze_video_quality disagrees with itself: calculate_ssim returns {'all': ...}
        and calculate_psnr returns {'average': ...}. Reading 'all' for both looks like it
        works, because SSIM answers and PSNR silently returns None — which is exactly how
        an earlier verification reported PSNR unavailable against a perfectly good tool.
        """
        self.assertAlmostEqual(verify_conversions.metric_value({'all': 0.9277}), 0.9277)
        self.assertAlmostEqual(verify_conversions.metric_value({'average': 36.07}), 36.07)

    def test_plain_number_and_junk_are_handled(self):
        """A bare float must pass through; anything unrecognized must not crash."""
        self.assertEqual(verify_conversions.metric_value(41.5), 41.5)
        self.assertIsNone(verify_conversions.metric_value(None))
        self.assertIsNone(verify_conversions.metric_value({'unexpected': 1.0}))

    def test_output_moved_into_an_event_folder_is_still_found(self):
        """
        create_event_folders.py relocates archived files after import, leaving the
        conversion index pointing somewhere that no longer exists. Twelve of 646
        home-movies outputs had moved, and calling them missing every run would make the
        report ignorable.
        """
        moved = self.root / '2013' / '05 May' / 'Home Walkthroughs'
        moved.mkdir(parents=True)
        target = moved / '20130510_104649_CAM.h265.mp4'
        target.write_bytes(b'\x00')

        index = {target.name: [target]}
        resolved, was_moved = verify_conversions.resolve_output(
            '2013/05 May/20130510_104649_CAM.h265.mp4', index)

        self.assertEqual(resolved, target)
        self.assertTrue(was_moved)

    def test_ambiguous_filename_is_not_guessed(self):
        """
        Two files sharing a name means the fallback cannot know which is meant, so it
        must report the indexed location and let the failure be honest rather than
        silently verify the wrong file.
        """
        first = self.root / 'a' / 'clip.mp4'
        second = self.root / 'b' / 'clip.mp4'

        for path in (first, second):
            path.parent.mkdir(parents=True)
            path.write_bytes(b'\x00')

        _, was_moved = verify_conversions.resolve_output(
            '2013/05 May/clip.mp4', {'clip.mp4': [first, second]})

        self.assertFalse(was_moved)


class TestSpliceAttribution(unittest.TestCase):
    """
    Turning findings into decisions: which era, and what reached the archive.
    """

    def test_year_is_taken_from_a_path_component(self):
        self.assertEqual(
            attribute_splices.year_of('/Volumes/home-movies/2009/00017.MTS'), '2009')

    def test_pathological_years_are_not_matched(self):
        """
        A four-digit run is not a year. Matching one would scatter the clustering that
        the whole report depends on.
        """
        self.assertEqual(
            attribute_splices.year_of('/Volumes/share/1234/clip.MTS'), 'unfoldered')
        self.assertEqual(
            attribute_splices.year_of('/Volumes/share/00042/clip.MTS'), 'unfoldered')

    def test_unfoldered_sources_are_still_counted(self):
        """
        The two files outside any year folder sat in 'New-after reset' and were the only
        affected files outside 2009 and 2010, so dropping them would have hidden the one
        exception to the clustering.
        """
        year = attribute_splices.year_of(
            '/Volumes/home-movies/2011 Summer Vacation/New-after reset/00024.MTS')

        self.assertEqual(year, 'unfoldered')

    def test_only_foreign_statuses_count_as_affected(self):
        """
        Empty files are a separate pre-existing problem. Counting them as foreign content
        would inflate the 2014 rate and invent a third cluster.
        """
        self.assertIn('spliced', attribute_splices.FOREIGN_STATUSES)
        self.assertIn('entirely foreign', attribute_splices.FOREIGN_STATUSES)
        self.assertNotIn('empty', attribute_splices.FOREIGN_STATUSES)
        self.assertNotIn('ok', attribute_splices.FOREIGN_STATUSES)


# ============================================================================
# 10. MOVE_FILE_SAFELY WITHOUT PERSON TAGGING (organize_media.py)
# ============================================================================

class TestMoveFileSafelyWithoutPerson(unittest.TestCase):
    """
    Regression: with no --person, line 557's eager ['_' + PERSON_NAME] raised
    TypeError before the comprehension's guard could apply — organize_media
    crashed on the first file of any personless run (found 2026-10-22 during
    the family-history import, the first import run without a person name).
    """

    def test_move_succeeds_when_person_name_is_none(self):
        from PIL import Image

        import organize_media

        original_person = organize_media.PERSON_NAME
        organize_media.PERSON_NAME = None
        try:
            with tempfile.TemporaryDirectory() as root:
                src = Path(root) / "scan-001.jpg"
                Image.new("RGB", (4, 4)).save(src)
                dst_dir = Path(root) / "dest"
                dst_dir.mkdir()

                success, moved = organize_media.move_file_safely(src, dst_dir)

                self.assertTrue(success)
                self.assertEqual(moved, dst_dir / "scan-001.jpg")
                self.assertFalse(src.exists())
        finally:
            organize_media.PERSON_NAME = original_person


# ============================================================================
# RUNNER
# ============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
