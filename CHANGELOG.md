# process-media CHANGELOG

---

## v13 — 2026-07-30 — "Source hash cache + dry-run purity"

Follow-ups found while validating v12 against the real Nikon NAS archive. Three
fixes, all concerning where and when caches get written.

<details>

### Dry-run no longer writes into the source tree

v12's `_get_cached_md5()` stored the hash of an *incoming* file in an
`.analysis_cache.json` inside that file's own directory. For a NAS-hosted or
memory-card source that meant writing to the source tree — during `--dry-run`,
which must modify nothing, onto media that may be read-only, and in the NAS case
putting avoidable wear on the drives.

Source hashing now goes through a separate `_hash_source()`, and
`_get_cached_md5()` is documented as archive-only. A test asserts that no cache
file appears in the source directory even after an explicit flush.

### Source hashes cached outside the source tree

Rather than discard those hashes, they are recorded in
`.source_hash_cache.json` beside the module, alongside the existing
`.duration_cache.json`. Validated by mtime and size like every other cache here.

This matters because the normal workflow is dry-run, inspect, then live run — and
without a cache each pass re-reads every source byte. The pending import backlog
is over 100 GB, much of it across an SMB share.

`save_source_hashes()` prunes entries whose file no longer exists before writing.
The expected outcome of an import is that the source file *moves* into the
archive, so without pruning the cache would grow without bound.

Measured against `/Volumes/photosync/NIKON` (4,502 files, 12 GB): a repeat
`--dry-run` reached identical verdicts in 99.8 s wall / 23.4 s CPU. For scale, the
reconciliation run measured **190.9 s to MD5 that same file set** from cold.

`DuplicateDetector` accepts a `source_hash_cache` override so tests never write
into the working directory.

### ImageAnalysisCache.save() tolerates an unwritable destination

`save_all_caches()` iterates every registered cache and previously let
`FileNotFoundError` escape. Caches are flushed in bulk at the very *end* of a long
run, and by then a directory may legitimately be gone — pruned during the run, or
on a share that has since unmounted. The exception aborted the flush partway
through and discarded every hash the run had just computed.

It now warns and moves on, leaving the cache marked dirty. Surfaced by a test that
was itself wrong in an instructive way: it passed a *directory* to
`ImageAnalysisCache`, which takes a cache *file* path, so `open()` created a plain
file and the save appeared to succeed.

### Housekeeping

- `.gitignore`: added `.analysis_cache.json`, `.duration_cache.json`, and
  `.source_hash_cache.json`. None were ignored, so the first real run would have
  left them as untracked noise.
- Cleared a `SyntaxWarning` from an unescaped `\d` in a test docstring.

### Tests — 99 → 106

`test_source_directory_is_never_written_to`, `test_source_hash_is_cached_outside_the_source_tree`,
`test_cached_source_hash_is_actually_consulted` (poisons the cache with a wrong
hash to prove it is genuinely read rather than silently recomputed),
`test_modified_source_invalidates_its_cached_hash`,
`test_saving_prunes_entries_for_vanished_sources`,
`test_corrupt_source_hash_cache_is_ignored`, and
`test_save_survives_a_vanished_directory`.

</details>

---

## v12 — 2026-07-30 — "BUG-6: EXIF-only files were invisible to dedupe"

Import-time duplicate detection ignored 26.1% of the archive. Any file without a
`YYYYMMDD_HHMMSS` stamp in its filename — every Nikon `DSCN*`, DSLR `DSC_*`, old
`IMG_####`, and scanned image — was treated as new on every ingest. Fixed with a
size-narrowed content-hash fallback. Also deletes a dead function whose tests
were the reason this went unnoticed.

<details>

### BUG-6: find_duplicate() bailed out before consulting the index

`DuplicateDetector.find_duplicate()` extracted a date pattern from the source
filename and, finding none, returned `is_duplicate=False` immediately — without
ever looking at the archive. Organized Nikon files are named
`DSCN3089_S3500.JPG`. So re-ingesting the same SD card classified every photo as
new, and `move_file()` then "resolved the collision" by appending `_1`, emitting
a log line that reads like success.

Measured on the live archive before the fix:

```
Archive files reachable by date-pattern dedupe: 27,547 / 37,300
Invisible to it: 9,753 (26.1%)

EXIF-ONLY FILE (already in archive, re-ingest simulation)
  is_duplicate : False
  reason       : No date pattern in filename
CONTROL: DATE-STAMPED FILE
  is_duplicate : True     <- name-based path worked fine
```

This was armed directly in front of the Phase C backlog: ~5,000 Nikon `DSCN`
files, plus DSLR and old-camera files, against the stated goal of not "doubling
the file count of our new photo/video archive with duplicates everywhere."

### Fix: size-narrowed content hashing

`find_duplicate()` now falls back to content comparison at **both** points where
name-based matching gives up:

1. No date pattern in the filename at all.
2. A date pattern that matches nothing in the index — which also catches a photo
   that was renamed at some point since it was first imported.

Content hashing was chosen over an EXIF-date-plus-size heuristic deliberately. A
false positive means **silently discarding a genuinely new photo**, which is far
worse than importing a duplicate. Byte equality carries no such risk. Re-encoded
and resized near-duplicates remain out of scope — the perceptual-hash pass in
`photo_triage.py` handles those during review.

Hashing 158 GB to answer one question is avoided by narrowing on size first:
byte-identical files necessarily have identical length, so only archived files
sharing the source's exact size are ever hashed.

New members:

- `DuplicateDetector._get_size_index()` — lazily built `{size: [paths]}`. Deferred
  because a batch whose filenames all carry date stamps never needs it.
- `DuplicateDetector._get_cached_md5()` — reads MD5 from the per-directory
  `.analysis_cache.json`, computing and storing it only on a miss. 46,475 MD5s
  were already cached by previous triage runs.
- `DuplicateDetector._find_identical_by_content()` — size narrowing, then hash
  comparison over the survivors, sorted for deterministic results so a dry-run
  matches the live run that follows.
- `ImageAnalysisCache.get_md5()` / `set_md5()` — `get_hashes()` only returns when
  *both* md5 and phash are cached, and `set_hashes()` demands both. The new pair
  reads and writes the md5 alone without clobbering a phash or blur score.
- `DuplicateDetector.save_caches()` — flushes the duration cache *and* the
  analysis caches. Nothing previously persisted the latter, so newly computed
  MD5s were discarded, forcing a re-hash on every run (twice for the usual
  dry-run-then-live sequence). `organize_archive.py` and `workflow_reprocess.py`
  now call this instead of `save_duration_cache()`.

### Also removed: dead code that was actively misleading

`organize_archive.find_existing_by_date()` had **no call sites** — the live
archive import path is `DuplicateDetector.find_duplicate()`. It carried its own
`paths[0]`-only bug and an O(index) scan per file, and 8 tests asserted its
behavior under a docstring claiming it was "the primary deduplication mechanism
for DSCN and other EXIF-only files."

That false confidence is precisely why BUG-6 survived this long: the suite looked
like it covered EXIF-only dedupe. The function and its tests are deleted, and
Section 9 now covers the path that actually runs.

### Verified after the fix

```
EXIF-ONLY FILE (already in archive, re-ingest simulation)
  is_duplicate : True
  confidence   : EXACT
  reason       : Byte-identical to DSCN9371.JPG (no date in filename)
```

Batch scale check — 250 already-archived EXIF-only photos copied out and
re-offered to the importer:

| Measure | Result |
|---|---|
| Detected as duplicate | 250 / 250, no misses |
| Per-file lookup | 5.8 ms |
| Detector init (37,300-file index) | 2.46 s |
| Projected, 5,000 Nikon files | ~29 s |
| Projected, full 28,800 backlog | ~167 s (upper bound; first run warms the cache) |

### Tests — 94 → 99 (8 removed, 13 added)

- `TestAnalysisCacheMd5` (5): roundtrip, missing entry, cross-field preservation
  against phash and blur, invalidation after content change, and no-raise on a
  vanished path.
- `TestExifOnlyDuplicateDetection` (8): the re-ingest regression case; a genuinely
  new file still importing (the failure mode that must never occur); same size but
  different content rejected, proving the match is by hash and not by size; a
  renamed-but-identical file caught; the date-pattern fast path unchanged; empty
  archive; missing source; and a stale cached hash not producing a false match.

### Note on mtime

An `mtime`-based date index was evaluated and rejected. `process_file()` calls
`stamp_filesystem_dates()` after every move, so mtime *should* equal capture
date, but sampling 400 EXIF-only archived photos found only 88.0% agreement:
11.2% disagreed, some by years, clustered around a bulk-copy date of 2023-08-19
and around scanned images whose EXIF records the scan rather than the scene.

</details>

---

## v11 — 2026-07-30 — "BUG-5: event folder re-run safety"

Fixed cluster detection so that re-running after an import collects new photos
into the event folders that already own their day, instead of stranding them or
creating a competing sibling folder. Tests written before the fix; suite grew
from 75 to 94.

<details>

### BUG-5: cluster detection ignored existing event folders

`_detect_photo_clusters()` evaluated the ≥35-photos-per-day threshold against
*loose direct-child files only*. It never considered that a day might already
own an `MM-DD Event` folder from a previous run. Two distinct failure modes:

1. **Stranding.** A batch adding fewer than `threshold` photos to an
   already-filed day left them loose in the month folder, beside the folder
   they belonged in.
2. **Competing folders** (the worse case, and the one a naive "count the loose
   files" audit misses entirely). A batch adding *more* than `threshold` photos
   to a day covered by a span folder created a brand-new folder for that day.
   On the live archive this would have created `2016/07 July/07-19 Event`
   holding 102 photos directly beside the existing
   `2016/07 July/07-18–07-19 Event` — splitting one event across two siblings.

**Fix:** `_detect_photo_clusters()` now runs two passes.

- **Pass 1 (adoption)** routes any loose photo whose day is already claimed into
  that existing folder, regardless of threshold. Adoption is a correctness
  repair rather than discovery, so it runs even when `--event-threshold 0` is
  passed — otherwise that flag would silently reintroduce the bug.
- **Pass 2 (discovery)** applies the original threshold logic to unclaimed days
  only. Adopted days are removed from the pool first, so a dense day adjacent to
  an existing folder forms its own folder rather than being absorbed into a
  renamed span. Renaming an existing folder would invalidate outside references
  to it, so that is deliberate.

**New:** `map_days_to_cluster_folders(month_folder, year)` reports which calendar
days already own a cluster folder. It recognizes only the `MM-DD Event` and
`MM-DD–MM-DD Event` names this script generates — named holiday folders
(`2024 Christmas`) and hand-named folders (`Escape Room`) are deliberately
excluded. Impossible dates (`02-30 Event`) and reversed spans are skipped rather
than raising.

**Contract change:** `_detect_photo_clusters()` now returns
`(destination_dir, files)` tuples instead of `(folder_label, files)`. The
destination is fully resolved by the detector, so `process_year()` no longer
infers it from `cluster_files[0].parent`. Dry-run output marks adoptions with
`[into existing]`.

### Measured effect on the live archive

Re-running the dry-run against `Organized_Photos/` moved the total from 1,998 to
2,034 candidate photos:

| Year | Folder | Photos | Was |
|---|---|---|---|
| 2016 | `07-18–07-19 Event` | 102 | would have created a competing `07-19 Event` |
| 2016 | `10-29 Event` | 1 | stranded |
| 2018 | `06-14 Event` | 8 | stranded |
| 2022 | `04-16 Event` | 27 | stranded |

All other years' output is byte-identical to the pre-fix run.

### Tests — Section 8, 19 new cases (75 → 94)

Written before the implementation and confirmed failing first. Fully hermetic:
filenames carry `YYYYMMDD_HHMMSS` stamps so `_get_file_date()` resolves them
with zero I/O — no exiftool, no cache priming, no network.

- `TestClusterFolderDayMapping` (10): single-day and span claims, month-boundary
  and leap-day spans, rejection of holiday folders, hand-named folders, files
  masquerading as folders, malformed names, and reversed ranges.
- `TestClusterAdoption` (9): the sub-threshold regression case, unchanged
  behavior for unclaimed quiet days and fresh dense days, inclusive threshold
  boundary, adopted days excluded from new span formation, span-wide adoption,
  `exclude_paths` still honored, explicit destination resolution, and
  `--event-threshold 0` still adopting.

</details>

---

## v10 — 2026-07-30 — "Reproducible environment"

Restored the photo review workflow, which had been silently non-functional
since a Homebrew Python upgrade, and pinned the toolchain so it cannot break
that way again. No changes to media-processing logic.

<details>

### Environment regression diagnosed and fixed

A Homebrew bump to Python 3.14.6 orphaned the previously-installed
`site-packages`, removing `numpy` and `cv2`. Because `photo_triage.py:4324`
calls `sys.exit(1)` when `OPENCV_AVAILABLE` is false, **every** photo review
entry point (`workflow_review.py`, `review-issues`, `browse`, `auto-triage`)
failed immediately. Blur scoring, perceptual-hash duplicate detection, and SSIM
comparison were all unavailable.

- **`requirements.txt`** — new, with pinned versions and an explanation of why
  they are pinned: `opencv-python==5.0.0.93`, `numpy==2.5.1`, `pillow==12.3.0`,
  `pillow_heif==1.5.0`. External tools (`exiftool`, `ffmpeg`) remain outside pip.
- **README "Setup" section** — new top-level section documenting the
  `.venv` workflow and the `WARNING: OpenCV not installed` symptom.
- **AGENTS.md** — instructs assistants to invoke `.venv/bin/python`, never bare
  `python3`, and explains the failure mode so the next session doesn't misread
  an environment problem as a code problem.
- **`.gitignore`** — added `.TMP_*` so ad-hoc analysis scripts stop showing as
  untracked, per the project's temp-script convention.

### OpenCV 4.x → 5.0 verified, no code changes required

The available wheel line has moved to OpenCV 5.0 while this code was written
against 4.x. Every `cv2` symbol referenced anywhere in the project
(`GaussianBlur`, `cvtColor`, `resize`, `Laplacian`, `imread`, `dct`, `Canny`,
`COLOR_BGR2GRAY`, `COLOR_RGB2BGR`, `CV_64F`, `INTER_AREA`, `IMREAD_GRAYSCALE`)
was confirmed present in 5.0.

Verified against live archive files rather than only unit tests, since the unit
tests patch OpenCV out:

- `test_core.py`: 75/75 pass, no OpenCV warning
- `calculate_blur_score` and `compute_phash`: 9/9 real files across JPG, PNG,
  and HEIC returned non-null values
- `calculate_image_ssim`: returns exactly `1.0` for a file against itself
- `photo_triage.py review-issues` on a 63-photo subset: exit 0, HTML generated,
  4 duplicate groups found

### Previously-uncommitted work committed

`test_core.py` (75 tests, documented in v6) and `workflow_review.py`
(documented in v9) existed on disk but had never been committed.

</details>

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
