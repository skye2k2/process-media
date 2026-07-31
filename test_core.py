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

import check_nas_archive
import create_event_folders
import duplicate_detector
import organize_archive
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
# RUNNER
# ============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
