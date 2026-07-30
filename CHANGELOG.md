# process-media CHANGELOG

---

## v9 — 2026-05-23 — "Review workflow + doc cleanup"

**workflow_review.py** — New orchestrator that chains the three steps needed
to review organized photos: blur cache warm-up (`auto-triage --dry-run`),
`review-issues` HTML report, and `browse` HTML report. Supports `--open`,
`--no-duplicates`, and `--skip-cache` flags.

**README.md** — Fixed stale `review` subcommand references to match actual CLI
(`review-issues` and `browse`). Trimmed the Photo Triage section to focus on
the new `workflow_review.py` entry point instead of requiring users to remember
three separate incantations.

**photo_triage.py** — Updated epilog/help text to reflect actual subcommand
names and reference the new workflow script.

---

## v8 — 2026-05-22 — "Nikon AVI datetime-prefix rename on transcoding"

**convert_legacy.py** — Nikon AVI files (stems matching `DSC[N_]*`) now receive
a `YYYYMMDD_HHMMSS_` datetime prefix when converted to H.265, mirroring the
naming convention used for camcorder files (`YYYYMMDD_HHMMSS_CAM.h265.mp4`).
The existing model-suffixed stem (`DSCN5075_S3500`) is preserved after the prefix,
so the result is `20140916_143022_DSCN5075_S3500.h265.mp4`. Non-DSCN legacy files
are unaffected and keep their original stem with `.h265.mp4` appended.

New helpers:
- `get_video_creation_date(file_path)` — exiftool → mtime fallback, returns `datetime`
- `DSCN_STEM_PATTERN` — constant matching `^DSC[N_]` (mirrors organize_archive.py)

---

## v6 — 2026-05-18 — "Tests + Nikon Reconcile"

Added the first test suite and a dedicated reconciliation tool for the
Nikon NAS archive before any ingestion begins.

<details>

### test_core.py — 63 unit tests covering critical business logic

New test suite targeting the functions whose silent failures have caused
the most historical data-quality bugs. Does NOT require any live files,
NAS mounts, or exiftool calls for the pure-logic tests. Keeper-priority
tests use real tempfiles so `Path.stat()` returns realistic data; EXIF
and dimension lookups are patched.

Sections:
- **Date extraction** (both `organize_archive` and `check_nas_archive` variants):
  14 tests covering known-good formats, DSCN/DSC no-date cases, invalid dates,
  and edge boundaries. Confirms the two modules agree on extractable substrings.
- **Duplicate detection** (`find_existing_by_date`): 8 tests including the
  ±5% size-tolerance gate, edited-variant exclusion, and empty-index behavior.
- **Project-folder classification** (`is_project_folder`): 9 tests including the
  DCIM-bucket guard regex (`^\d{3}[A-Z0-9]+$`) that was added in v4.
- **Keeper-priority sorting** (`_sort_paths_by_keeper_priority`): 7 tests
  covering review-area penalty, EXIF date wins, size fallback, filename-length
  tiebreaker, resolution for perceptual-similar groups, and the assertion that
  resolution is NOT used for exact duplicates.
- **AnalysisCache** get/set/invalidation: 9 tests including cross-field
  preservation (set_blur must not clobber existing hashes), dirty-flag lifecycle,
  and corrupted-file graceful degradation.
- **Shell-export escaping**: 8 tests verifying the `'\''` idiom correctly
  neutralizes `$`, backticks, semicolons, embedded single quotes, spaces,
  newlines, and backslashes.

### reconcile_nikon_archive.py — read-only NAS comparison tool

New tool for the Nikon NAS archive reconciliation problem: 13GB / ~5000 files
whose date history is uncertain due to years of manual renaming and cross-camera
use of the same DSCN sequence counters.

Classification categories (in priority order):
1. `EXACT_MATCH` — byte-identical MD5 match; safe to skip
2. `DATE_SIZE_MATCH` — EXIF date + file size within ±5%; high-confidence duplicate
3. `POSSIBLE_COLLISION` — same DSCN sequence number in archive but differing EXIF
   date or size; needs human review before skipping
4. `NEW_CONTENT` — no match by any strategy; candidate for ingestion
5. `NO_EXIF` — EXIF extraction failed; cannot classify reliably
6. `ERROR` — file could not be read

Features:
- EXIF extraction batched (500 files/call) for performance
- MD5 index built once over Organized_Photos/ and reused for all comparisons
- Per-file DSCN sequence number index detects numbering collisions
- Results cached to `.TMP_reconcile_cache.json` beside the NAS directory for
  fast re-runs without re-doing the full MD5+EXIF extraction
- `--cache-only` flag re-displays the summary from a previous run
- `--no-md5` flag for a quick first-pass (date+size only)
- `--verbose` prints each file's classification in real time
- Never touches Organized_Photos/, TO_PROCESS/, or the NAS files themselves

Rejected alternative: Running `workflow_archive.py --dry-run` against the NAS
directly. That approach would produce a "what would be moved" list but gives
no signal about files that are ALREADY present in the archive — which is exactly
the information needed before deciding whether to ingest 13GB. The reconcile
tool answers that question first.

### reconcile_nikon_archive.py — collision model corrected

Replaced DSCN-sequence-number collision detection (which flagged thousands
of false positives from two cameras sharing the same counter range) with
destination-path collision detection:

- **Old approach:** flagged any two files with the same `DSCN_XXXX` sequence
  number regardless of whether they would actually occupy the same folder.
  Result: ~thousands of `POSSIBLE_COLLISION` hits that weren't real problems.
- **New approach:** computes the exact `YYYY/MM MonthName/filename` destination
  path (mirroring `organize_archive.py` logic) and checks whether that specific
  path already exists in the archive. Only files that would cause a true
  filename+directory collision are flagged as `DEST_COLLISION`.
- **Model suffix** (`_S3100`, `_S3500`, `_D3000`, etc.): derived from the EXIF
  `Model` field and appended to the filename stem before the extension. This is
  the same pattern as person suffixes (`_Clif`, `_Nicole`). With the suffix
  applied, most sequence-counter overlaps between two cameras become non-colliding
  (`DSCN2542_S3100.JPG` vs `DSCN2542_S3500.JPG`), so fewer files land in
  `DEST_COLLISION`. `extract_camera_model_suffix()` and
  `compute_destination_filename()` are the new helpers.
- Added `build_archive_dest_index()` (replaces `build_archive_dscn_index()`).
- Cache forward-compatibility: `--cache-only` migrates old `POSSIBLE_COLLISION`
  entries to `DEST_COLLISION` automatically.
- 12 new tests in `test_core.py` (Section 7) cover model suffix extraction and
  destination filename assembly, bringing the total to 75.

NAS discovery: archive contains two cameras — CoolPix **S3100** (8MP, older
folders) and CoolPix **S3500** (10MP, later folders). Both have full EXIF
metadata comparable to the D3000 except `LensModel` (fixed-lens compacts
write no lens model). macOS Finder Quick Info surfaces all other fields
identically.

</details>

---

## v5 — 2026-05-17 — "Correctness Pass"

Bugfixes from analysis session: shell script injection, keeper
selection reliability, and resolution-aware duplicate comparison. No
regressions introduced; both modified modules import cleanly.

<details>

### BUG-1: Keeper selection replaced — mtime → EXIF date + tiebreakers

- **Root cause:** Both `auto_triage()` and `_render_duplicate_group()` sorted duplicate
  groups by `st_mtime` descending and treated index 0 as the keeper. Filesystem
  modification times are corrupted by card readers, file copies, and Takeout export
  dates — making them an unreliable proxy for "which copy is the original."
- **Fix:** New `_sort_paths_by_keeper_priority(paths, dup_type)` function in
  `photo_triage.py` applies a stable priority chain:
  1. Non-review-area paths preferred (`_TO_REVIEW_`, `Duplicates`, `Blurry` penalized)
  2. For perceptual-similar groups: higher pixel count (original > compressed copy)
  3. Earliest EXIF DateTimeOriginal (true capture date)
  4. Larger file size (less re-encoding history)
  5. Shorter filename (sequential camera names are shorter than collision copies)
  6. mtime descending (last resort only)
- Both `auto_triage()` and `_render_duplicate_group()` now delegate to this function.
- **Affected files:** `photo_triage.py`

### BUG-2: Resolution comparison for perceptual duplicates

- **Root cause:** pHash-similar groups had no mechanism to prefer the higher-resolution
  original over a texted/compressed thumbnail — both just sorted by mtime.
- **Fix (three-part):**
  1. `AnalysisCache` in `analyze_photo_quality.py` gains `get_dimensions()` /
     `set_dimensions()` methods, storing `image_width` and `image_height` per file.
  2. `batch_extract_exif_dates()` in `photo_triage.py` now fetches `-ImageWidth
     -ImageHeight` alongside date fields in the same exiftool call — zero extra
     subprocess cost.
  3. New `get_image_dimensions(file_path)` function in `photo_triage.py` (mirrors
     `get_exif_date()`) checks the cache first, falls back to a single exiftool call.
  4. Resolution is shown in the HTML duplicate card for transparency.
  5. `_sort_paths_by_keeper_priority` uses pixel count as criterion 2 for `similar`
     (pHash) groups; exact-duplicate groups skip it (all copies are the same image).
- **Affected files:** `analyze_photo_quality.py`, `photo_triage.py`

### BUG-3: Identical duplicate detection — root cause identified, no code change

- Diagnostic: `scan_for_duplicates(directory, recursive=True)` is correct. Cross-
  year duplicates are missed only when `directory` is scoped to a single year/month
  subfolder rather than the root `Organized_Photos/`. README note added to run
  auto-triage against the full root to catch cross-year identical pairs.

### BUG-4: Shell script injection fixed (both export functions)

- **Browse export** (`exportRemovals()`) and **review export** (`exportDecisions()`) both
  generated `rm "path"` shell lines. The browse export escaped `"` but not `$` or
  backticks; the review export did no escaping at all.
- **Fix:** Both functions now emit `rm 'path'` with embedded single quotes escaped via
  the `'\''` shell idiom. Single-quoting is the only portable, unconditionally safe
  approach for arbitrary POSIX paths.
- **Affected file:** `photo_triage.py`

### DSCN (Nikon compact) support — confirmed no code change needed

- Nikon compact cameras use `DSCNXXXX.JPG` filenames with no embedded date. These
  fall through `extract_date_from_filename()` (no match) to the EXIF path — same
  behavior as the DSLR `DSC_XXXX.JPG` files handled in v4. No new pattern needed.
- Nikon DCIM subdirectory names (`100NIKON`, `101NIKON`, etc.) match the
  `^\d{3}[A-Z0-9]+$` guard added in v4, so they are correctly treated as loose-file
  containers rather than project folders.

</details>

---

## v4 — 2026-02-23 — "DSLR Ingestion + Archive Performance"

Support for DSLR memory card contents (DSC_-prefixed files), archive workflow
output improvements, and a significant performance improvement via batch EXIF
extraction.

<details>

### DSLR memory card support

- `is_project_folder()` in `organize_archive.py` now excludes standard DCIM
  subdirectory names (e.g., `100D3000`, `101CANON`) via `^\d{3}[A-Z0-9]+$` regex.
  Previously these were misclassified as project folders and moved as a unit into a
  single month bucket; now their contents are scattered individually by EXIF date.
- Confirmed: DSLR EXIF (`DateTimeOriginal`) is solid and always present; the
  single-file fallback in `get_date_from_exif()` handles these correctly.

### Batch EXIF extraction for archive workflow

- New `batch_extract_dates(file_paths, chunk_size=1000)` in `organize_archive.py`
  collapses N per-file exiftool subprocess spawns into one (or a small number of
  chunked) invocations. For a typical DSLR card of ~500 files, this is ~500× faster
  than the old per-file path.
- `get_creation_date()` gains an `exif_cache` parameter; cache hits short-circuit
  before the single-file fallback is reached.
- `process_file()` accepts and passes through `exif_cache`.
- `main()` in `organize_archive.py` pre-fetches dates for all files lacking a
  filename date, then reports hit/miss count before processing begins.

### Archive workflow dry-run output improvements

- `move_file()` dry-run now shows `YYYY/MM MonthName/filename` instead of the full
  absolute path, reducing noise.
- Live run "Moved to:" line now includes year: `YYYY/MM MonthName/`.
- Summary block in dry-run mode appends the full output root paths for both photos
  and videos.

</details>

---

## v3 — 2026-01 — "Stabilization and Triage Tooling"

(Reconstructed from `_CONVERSATION.md` messages 83–147 and commit `f0bd5cd`)

Major stabilization pass after the initial processing run. Introduced photo triage
and review tools, extensive refactoring to eliminate SRP violations, and a second
processing run on 31,733 files.

<details>

### Script renaming for clarity

- `organize_photos.py` → `organize_media.py`
- `verify_remaining_files.py` → `check_leftover_files.py`
- `reunite_project_files.py` → `fix_fragmented_metadata.py`

### Shared code extraction

- `build_file_index.py` extracted from duplicated index-building logic across
  multiple scripts.
- `media_utils.py` introduced as shared constants and utility functions.

### New triage tooling

- `photo_triage.py` introduced: blur detection, duplicate scanning (MD5 + pHash),
  auto-triage file moves, HTML browse report, HTML review report.
- `analyze_photo_quality.py` introduced: `ImageAnalysisCache`, blur scoring,
  perceptual hashing, `scan_for_duplicates`.

### Metadata handling improvements

- `cleanup_orphaned_json.py` `--yes` / `-y` flag added for non-interactive batch
  processing.
- Enhanced date patterns: added `YYYY-MM-DD-HH-MM-SS`, `YYYY-MM-DD`, `YYYY-MM_`
  support.
- Wallpaper detection: files with resolution prefixes (`1920x1080`, `4k`, etc.)
  routed to `_TO_REVIEW_/Wallpapers/`.
- File extension auto-fix via magic byte detection (JPEG, PNG, GIF, WebP, HEIC,
  MP4); 127 mismatched extensions corrected across the 31,733-file run.
- EXIF write now retried after extension correction if the initial write failed
  due to format mismatch.

### HTML review enhancements (lightbox)

- Keep/Remove outline highlighting in lightbox.
- Spacebar toggles keep/remove.
- Up/Down arrow navigation between photos.
- Warning footer for edge cases.
- Blur score badges.

### Archive and camcorder workflows

- `organize_archive.py` introduced for NAS/phone exports without JSON metadata.
- `workflow_archive.py` orchestrator added.
- `workflow_camcorder.py` orchestrator added for AVCHD conversion.
- `duplicate_detector.py` introduced: date-pattern + duration + size multi-signal
  matching for import deduplication.

</details>

---

## v2 — 2025-12 to 2026-01 — "Google Takeout Processing"

(Reconstructed from `_CONVERSATION.md` messages 1–82 and commit `daa99f0`)

Initial implementation of the Google Takeout pipeline. Approximately 80 messages
across two Sonnet sessions — 25.6% regression debugging, 17.1% new requirements.

<details>

### Core Takeout pipeline

- `organize_media.py` (initially `organize_photos.py`): two-phase organization
  (project folders, then individual files) with JSON metadata merging.
- `merge_metadata.py`: batch EXIF writer from Google Takeout JSON.
- `fix_truncated_extensions.py`: `.MP` → `.mp4` and similar truncation fixes.
- `workflow_takeout.py`: master orchestrator.

### Date handling

- `photoTakenTime` vs `creationTime` comparison; files where they differ by 3+
  months routed to `_TO_REVIEW_/` for manual inspection.
- Filename-first date extraction (YYYYMMDD patterns checked before parsing JSON).
- In-memory file index for O(1) duplicate detection.

### Duplicate and project handling

- Project folder detection and merging across multiple Takeout archives.
- Trash directory routing to `_TO_REVIEW_/Trash_Archives/`.
- `cleanup_orphaned_json.py` for leftover metadata files.
- `fix_fragmented_metadata.py` for projects split across dated folders.

### Known regressions introduced and fixed within this period

- Multiple undefined-function errors from premature code submission (Sonnet pattern).
- Function signature mismatches during refactoring.
- `EOFError` in `cleanup_orphaned_json.py` stdin handling (fixed with `--yes` flag).

</details>

---

## v1 — 2025-12 — "Initial Vision"

(Commit `9da7a30`)

Project scaffolded. `organize_media.py`, README, basic directory structure
(`TO_PROCESS/`, `Organized_Photos/`, `Organized_Videos/`).
