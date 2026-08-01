# SCRIPTS.md — every script in the repo

Reference companion to [README.md](README.md), which covers the five workflows that are the intended entry points. This file itemizes everything, including the engines the workflows drive and the tools you reach for when something has gone wrong.

**Run everything as `.venv/bin/python`**, never bare `python3` — see README "Setup".

---

## Contents

- [Workflow orchestrators](#workflow-orchestrators) — the front doors
- [Processing engines](#processing-engines) — what the workflows drive
- [Analysis](#analysis)
- [Verification and diagnostics](#verification-and-diagnostics)
- [Repair and cleanup](#repair-and-cleanup)
- [Shared libraries](#shared-libraries)
- [Tests](#tests)

---

## Workflow orchestrators

Prefer these. Each chains the right engines in the right order and is the documented path.

### `workflow_takeout.py`

Google Takeout import. Prompts for a person's name, then fixes truncated extensions, merges JSON metadata into EXIF, organizes by date with person tagging, and rebuilds the file index between Takeout directories so duplicate detection stays accurate. Handles 50+ Takeout folders in one run.

No flags — it is interactive by design, since the person name has to be supplied per export.

### `workflow_archive.py`

Import from a NAS folder, phone dump, or memory card — anything without JSON sidecars. Uses date, size, duration, and content hashing to decide what is already present.

| Flag | Effect |
|---|---|
| `--dry-run` | Report without moving anything |
| `--person-suffix NAME` | Append an owner suffix to every filename |
| `--model-suffix SUFFIX` | Override the EXIF-derived camera model suffix for the batch |

Drives `organize_archive.py`, which additionally accepts `--ignore-removal-history` and `--import-damaged`. Both defaults are the safe ones; see README for why.

### `workflow_camcorder.py`

Convert AVCHD and other legacy video to H.265.

| Flag | Effect |
|---|---|
| `--dry-run` | Analyze and estimate without encoding |
| `--avchd-only` | **Restrict to `.MTS`/`.M2TS`. Required when pointing at an archive** — otherwise it picks up MP4s that `organize_archive.py` already imported, which it cannot recognize because that path does not write to the conversion index |
| `--keep-originals` | Do not delete sources after converting |
| `--crf N` | Quality factor; default 26 |
| `--preset NAME` | x265 preset; default `slow` |
| `--force-software` | Force `libx265` instead of letting VideoToolbox handle clean footage |

### `workflow_reprocess.py`

Menu-driven maintenance for media that is already organized. Interactive, no flags. Actions: convert legacy formats in place, duplicate check, deep codec scan, fix motion photos, and create event folders.

### `workflow_review.py`

Generate the two HTML review reports. Warms the blur and hash caches, then builds the review-issues and browse-all reports.

| Flag | Effect |
|---|---|
| `--open` | Open the reports in a browser when done |
| `--no-duplicates` | Skip duplicate scanning (faster) |
| `--skip-cache` | Skip the cache warm-up when it is already populated |

Reports land at `Organized_Photos/_review_issues.html` and `_browse_all.html`.

---

## Processing engines

Driven by the workflows above. Run directly only when you need a step in isolation.

### `organize_media.py`

The Google Takeout organizer. Two-phase: project folders first, then individual files. Merges JSON metadata, resolves duplicates against an in-memory index, routes conflicts to `_TO_REVIEW_/`. Compares `photoTakenTime` against `creationTime` and sets aside anything where the two disagree by three months or more.

### `organize_archive.py`

The archive organizer. Detects DCIM buckets so a card dump is scattered by EXIF date rather than moved as one lump, batches EXIF extraction, derives camera model suffixes per file, and consults both the removal history and an integrity check before importing anything.

**Moves** files. Stage a copy before pointing it at an archive.

#### Performance

- **Duration caching**: Video durations are cached to `.duration_cache.json`
  - First run: ~50 seconds (ffprobe analyzes each video)
  - Subsequent runs: ~5 seconds (uses cached durations)
  - Cache invalidates when file mtime or size changes

### `camcorder_convert.py`

AVCHD to H.265, with the per-file decisions: encoder selection (VideoToolbox for clean footage, `libx265` for noisy), date derivation from exiftool then ffprobe then mtime, and output naming as `YYYYMMDD_HHMMSS_CAM.h265.mp4`.

**Deletes sources** after a successful conversion unless `--keep-originals` is passed, and refuses to do so outside a `TO_PROCESS` directory regardless.

### `convert_legacy.py`

Converts legacy formats already sitting in `Organized_Videos/` in place — AVI, MTS, M2TS, MPEG-2. Nikon AVI files gain a datetime prefix to match the camcorder naming convention. Uses CRF 20, which deliberately differs from `camcorder_convert.py`'s 26; see the README note.

#### Codecs converted vs skipped

| Converted (older/larger) | Skipped (already efficient) |
|--------------------------|----------------------------|
| H.264/AVC | H.265/HEVC |
| MPEG-2 | AV1 |
| MPEG-4 Part 2 | VP9 |
| Motion JPEG | |
| VC-1, WMV | |

### `create_event_folders.py`

Groups photos from month folders into named event subfolders. Two passes: named holidays and birthdays first (configured birth dates, Fourth of July, Halloween, Thanksgiving, Christmas), then dense-day cluster detection for untagged events.

Adopts loose photos into an event folder that already owns their day, regardless of the cluster threshold, so a later import cannot strand a handful of photos beside the folder they belong in.

Dry-run by default; `--execute` to move, `--year YYYY` to scope, `--event-threshold N` to tune cluster detection (0 disables discovery but not adoption).

### `merge_metadata.py`

Writes Google Takeout JSON metadata into photo and video EXIF. `--recursive`, `--remove-json`, `--preserve-existing`. Requires exiftool.

### `motion_photo_extract.py`

Handles Pixel Motion Photos — dual-stream files that macOS QuickLook cannot play. Can extract the still, delete the video, or strip the embedded still so the video plays. `--scan` to survey first.

### `photo_triage.py`

The largest module in the repo at ~4,700 lines. Blur detection, duplicate scanning by MD5 and perceptual hash, keeper selection, auto-triage file moves, and two complete HTML applications with inline CSS and JavaScript.

Subcommands: `summary`, `blurry`, `review-issues`, `browse`, `auto-triage`, `undo`.

Exits immediately if OpenCV is unavailable, which is why the venv interpreter matters. Prefer `workflow_review.py` over calling this directly.

---

## Analysis

### `analyze_photo_quality.py`

Blur scoring by Laplacian variance, perceptual hashing, SSIM comparison, HEIC support, and the `ImageAnalysisCache` that every other tool reads from. Cache entries hold blur score, MD5, perceptual hash, EXIF date and dimensions, invalidated by mtime and size.

Blur thresholds: 150+ sharp, 80–150 decent, 40–80 soft, 20–40 blurry, under 20 very blurry. Low-texture images are exempt, since a photo of a wall legitimately scores low.

Subcommands: `blur`, `compare`, `pairs`, `analyze`.

#### Edited pair detection

Automatically finds files with `-edited`, `_edited`, ` edited`, or ` (edited)` suffixes and compares them to their originals:

- **SSIM comparison**: How similar are the images?
- **Blur comparison**: Which version is sharper?
- **Size comparison**: File size differences

### `analyze_video_quality.py`

Compares an original against a re-encode: SSIM, PSNR, bitrate, compression ratio. Can sweep a range of CRF values and extract frames for visual comparison, which is the tool for finding the right CRF before a large DVD rip.

#### Understanding the metrics

**SSIM (Structural Similarity Index):**

| Value | Interpretation |
|-------|---------------|
| 1.0 | Identical (lossless) |
| > 0.98 | Imperceptible difference |
| 0.95 - 0.98 | Nearly indistinguishable (target for archival) |
| 0.90 - 0.95 | Minor visible differences |
| < 0.90 | Noticeable quality loss |

**PSNR (Peak Signal-to-Noise Ratio):**

| Value | Interpretation |
|-------|---------------|
| > 45 dB | Excellent (mathematically near-lossless) |
| 40 - 45 dB | Very good (broadcast quality) |
| 35 - 40 dB | Good (acceptable for most content) |
| 30 - 35 dB | Fair (visible artifacts likely) |
| < 30 dB | Poor (significant quality loss) |

**Rule of Thumb:** A video with **SSIM ≥ 0.95** and **PSNR ≥ 38 dB** is typically "visually lossless" for normal viewing conditions. SSIM is generally more perceptually accurate than PSNR.

#### CRF comparison mode

When testing multiple CRF values, the script:
1. Extracts a sample clip from the original (default 60 seconds)
2. Encodes the sample at each specified CRF value
3. Runs SSIM and PSNR comparisons for each
4. Outputs a comparison table with recommendations

Example output:
```
  CRF |     Size |    Bitrate | Compress |     SSIM |     PSNR | Quality
------+----------+------------+----------+----------+----------+--------
   18 |   42.3MB |     5780kb |    45.2% |   0.9812 |   42.3 dB | Imperceptible
   20 |   27.1MB |     3680kb |    65.1% |   0.9695 |   40.8 dB | Nearly indist...
   22 |   18.4MB |     2510kb |    76.3% |   0.9521 |   38.2 dB | Nearly indist...
   24 |   12.7MB |     1730kb |    83.6% |   0.9234 |   35.6 dB | Minor visible...
```

#### Frame extraction

The tool automatically extracts comparison frames at 10%, 30%, 50%, 70%, and 90% through the video for visual spot-checking. These are saved as PNG files in the output directory.

#### Worked example: choosing a CRF for a DVD rip

```bash
# 1. Rip a short sample (or full episode) at maximum quality
HandBrakeCLI -i /dev/dvd -o sample_lossless.mkv --encoder x265 --quality 0

# 2. Test various CRF values to find the sweet spot
.venv/bin/python analyze_video_quality.py sample_lossless.mkv --test-crf 18 20 22 24 26

# 3. Review the comparison table and extracted frames
open /var/folders/.../quality_analysis_.../frames/

# 4. Once you've found your ideal CRF, use it for the full rip
```

---

### `duplicate_detector.py`

Import-time duplicate detection, driven by `organize_archive.py`. Signals in order: filename date pattern, sub-second frame discriminators, video duration, file size, content hash, and structural similarity for same-dimension recompressions.

Also has a CLI for checking a single file against the archive.

---

## Verification and diagnostics

### `check_media_health.py`

Is this file actually intact? Full image decode rather than a header read, ffprobe for video including AVCHD, CRC32 per member for ZIP-family documents, `%%EOF` for PDF. `--output PATH` to save the damaged list, `--workers N` to tune for a network share.

The only check here that can see corruption inherited from a pre-ZFS NAS generation.

### `check_nas_archive.py`

Compares a NAS directory against the organized archive by filename date pattern and reports what is missing. Skips `.MTS`/`.M2TS`, which belong to the camcorder workflow. `--verbose`, `--output missing.txt`.

### `check_leftover_files.py`

Verifies that whatever remains in `TO_PROCESS/` after a run is genuinely a duplicate of something organized, rather than a file that failed to import quietly.

### `reconcile_nikon_archive.py`

Read-only pre-ingestion survey. Classifies every file in a source directory against the archive: `EXACT_MATCH`, `TRANSCODED_MATCH`, `DATE_SIZE_MATCH`, `DEST_COLLISION`, `NO_EXIF`, `NEW_CONTENT`, `ERROR`. Answers "how much of this do I already have" before committing to a transfer.

Indexes both `Organized_Photos/` and `Organized_Videos/`, and recognizes a video already present as a transcode by finding the original stem inside the archived filename — a converted file shares no bytes with its source, so hashing cannot see it.

`--no-md5` for a fast first pass, `--cache-only` to re-display a previous run, `--output PATH` for the results cache, `--archive-dir` to compare against something else.

Named for Nikon but works on any source directory.

---

## Repair and cleanup

### `cleanup_orphaned_json.py`

Removes Takeout JSON sidecars whose media file is gone. `--yes` for non-interactive batches.

### `fix_fragmented_metadata.py`

Reunites project folders that Google split across dated directories — JSON in one place, media in another. `--dry-run` first.

### `fix_truncated_extensions.py`

Repairs extensions truncated by filesystem limits, `.MP` to `.mp4` and similar.

### `apply_date_from_neighbor.py`

For files with no usable EXIF date. Sets the **filesystem mtime** via `touch -t` — it deliberately does not write EXIF tags, which is fortunate because exiftool cannot write to MTS at all. Downstream tools fall back to mtime, so that is enough.

Borrows the date from the nearest preceding file with valid EXIF; `--date YYYYMMDD` to override when the neighbour is known wrong. `--dry-run` first.

---

## Shared libraries

Imported, not run.

### `media_utils.py`

Shared constants and helpers: photo, video and AVCHD extension sets, month folder names, sidecar path resolution, Takeout JSON suffix handling.

### `build_file_index.py`

Builds an in-memory index keyed by base name, extension and edited-status for O(1) duplicate lookups. Strips person suffixes so a source file matches its archived counterpart. Walks recursively, so files inside event folders stay visible.

### `conversion_index.py`

Persistent record of which videos have been converted, keyed by `(creation_date, file_size)` of the original — not filename, because camcorder filenames restart at `00000.MTS` on every card and mean nothing across them. Stored at `Organized_Videos/.conversion_index.json`, written per conversion so an interrupted batch loses one file rather than the run.

### `removal_history.py`

Remembers what was deliberately deleted so it cannot come back. Parses every `*remove*.sh` exported from a review session and matches by normalized name rather than path, because the organizing scripts move files freely.

Also runnable for inspection: `--check FILENAME`, `--list N`.

---

## Tests

### `test_core.py`

196 tests covering the logic whose silent failure is expensive: date extraction, project folder classification, keeper priority, the analysis cache, shell export escaping, camera model suffixes, event folder adoption, EXIF-only duplicate detection, frame discriminators, the recompression keeper gate, removal history normalization, source liveness, damaged-source quarantine, media health checks, staging-path and duration plausibility, and reconciler video awareness.

Hermetic and fast — under two seconds, no live files, no NAS mount, no network. Fixtures are generated rather than curated, which is a deliberate trade; see NEXT.md for the integration corpus that is still missing.

```bash
.venv/bin/python test_core.py           # all
.venv/bin/python test_core.py -v        # verbose
.venv/bin/python test_core.py TestDateExtraction   # one class
```

---

## Naming and placement rules

How files are named and where they land, shared by every import path.

The `organize_media.py` script consolidates photos from multiple Google Takeout archives into a structured organization system using a two-phase approach with performance optimizations:

**Performance Optimizations:**
- **In-memory file index**: Builds a fast lookup index of all organized files at startup (~1 second for thousands of files)
- **Index rebuilding**: Automatically rebuilds the index after processing each Takeout directory to ensure accurate duplicate detection across all 50+ Takeout directories
- **Filename-first date extraction**: Checks filename patterns (YYYYMMDD) before parsing JSON for speed
- **O(1) duplicate detection**: Dictionary lookups instead of filesystem glob operations

**Phase 1: Project Folder Processing**
- Identifies special project folders (e.g., "Dad's 2006 F-150 XLT", "Family History") that should remain intact as collections
- **Project folder detection rule**: any named folder that is not a standard `Photos from YYYY` or `Untitled…` folder — *except* folders whose name contains a comma. Google Takeout creates per-share directories named after the people a photo was shared with (e.g., "Nicole, Shannon, Simon", "Clif, jacen.the.first@gmail.com"). These are not curated collections; their contents are per-person copies of shared photos and are sorted normally as individual files.
- **Merges JSON metadata into EXIF for all files within the project folder** (using merge_metadata.py --recursive --remove-json)
- Extracts year from folder name or folder contents
- Determines the most common month from photos within the folder for prefix assignment
- Merges duplicate project folders found across multiple Takeout archives instead of creating separate copies
- Moves complete folders (with EXIF-updated files) to year directories with format: `YYYY/MM FolderName/`

**Phase 2: Regular File Processing**
- Processes individual media files not in project folders
- **Date priority**: Filename patterns are checked first for speed; JSON metadata is only parsed if filename has no date
  - Supported patterns: `YYYYMMDD_HHMMSS`, `YYYY-MM-DD-HH-MM-SS`, `YYYYMMDD`, `YYYY-MM-DD`, `YYYY-MM_`
- When JSON metadata exists, compares photoTakenTime vs creationTime - uses earlier date (later becomes modification date) when they differ by 3+ months
- **Wallpaper detection**: Files with resolution prefixes (e.g., `1920x1080`, `4k`, `Ultrawide`) are automatically routed to `_TO_REVIEW_/Wallpapers/`
- **File extension auto-fix**: Detects mismatched extensions via magic bytes (e.g., WebP saved as .jpg) and automatically renames files to correct extension
- **EXIF updates**: Date and GPS metadata from ALL sources (filename, JSON, or existing EXIF) are written to files during organization
  - Files with filename dates: EXIF written from parsed filename date
  - Files with JSON metadata: EXIF written from JSON dates and GPS coordinates
  - Files with existing EXIF: EXIF preserved (no JSON to process)
  - If EXIF write fails due to format mismatch, extension is auto-corrected and write is retried
- **JSON cleanup**: Metadata JSON files are deleted after successful EXIF write and file move
- Organizes files into: `YYYY/MM MonthName/` (e.g., `2025/12 December/`)
- Files with no parsable date are moved to `_TO_REVIEW_/` with year-based organization:
  - Extracts year from path (prioritizing "Photos from YYYY" folders)
  - Creates subdirectories like `_TO_REVIEW_/2018/`, `_TO_REVIEW_/2019/`
  - Writes EXIF date as January 1 of inferred year (e.g., 2018-01-01 00:00:00) - easily identifiable as inferred
  - Files with no year in path remain in flat `_TO_REVIEW_/` directory

**Duplicate Detection:**
- Distinguishes between originals and -edited variants (both can coexist)
- Uses file index for O(1) lookup speed instead of slow filesystem operations
- Detects duplicates across all processed Takeout directories (index rebuilt after each one)

**Cleanup Phase**
- Removes empty directories and folders containing only metadata files
- Moves Trash directories to `_TO_REVIEW_/Trash_Archives/` for final review
- **Final metadata merge**: workflow_takeout.py runs merge_metadata.py on `_TO_REVIEW_/` to update any files that were skipped during organization

**Post-Processing Tools:**

**fix_fragmented_metadata.py** - Handles Google Takeout fragmentation
- Google Takeout sometimes splits projects: JSON metadata in project folders, media files in dated folders
- Scans organized project directories for orphaned JSON files (JSON without media)
- Searches organized dated folders for corresponding media files
- Moves media files from dated folders into their proper project folders
- Deletes JSON after successful reunification
- Supports `--dry-run` mode to preview changes

**cleanup_orphaned_json.py** - Removes orphaned metadata
- Finds JSON files that don't have corresponding media files (deleted, moved elsewhere, etc.)
- Identifies various truncated JSON patterns (`.supplemental-.json`, `.supplemental-metad.json`, etc.)
- Skips folder `metadata.json` files
- Interactive deletion with confirmation (or use `--yes` / `-y` for batch processing)

**Key Features:**

- Date conflict detection: files where photoTakenTime and creationTime differ by 3+ months
- Project folder merging: Prevents duplicate folders from multiple Takeout archives
- Performance: In-memory indexing for fast duplicate detection across 50+ Takeout directories
- Smart EXIF writing: Applies metadata from any source (filename, JSON, existing EXIF) during organization
- Fallback dating: Uses multiple strategies to determine file dates when metadata is missing
- Photo/Video separation: Photos go to Organized_Photos/, videos to Organized_Videos/
- Takeout fragmentation handling: Reunites projects split across dated folders
- Wallpaper separation: Auto-detects and routes resolution-prefixed wallpapers to `_TO_REVIEW_/Wallpapers/`
- Extension mismatch auto-fix: Detects and corrects wrong file extensions via magic byte analysis (JPEG, PNG, GIF, WebP, HEIC, MP4)

**Known Issues:**

- **Pixel Motion Photos**: Google Pixel phones create "Motion Photos" – short video clips captured alongside photos. These export as `.mp4` files with **two video streams**: the main video clip plus an embedded still image. macOS QuickLook/Preview cannot play these dual-stream files (the video opens in dedicated players like VLC just fine). Most of these clips are accidental 2-3 second snippets with no value. It is also very likely that a high-resolution version of the same still already exists (or existed).
  - **To disable on Pixel**: Camera Settings → More settings → Motion → Off
  - **To fix existing files**: Use `motion_photo_extract.py` (see Reprocessing Workflow) to extract the still and delete the video, or strip the embedded still to make QuickLook-compatible

**Directory Structure:**
```
process-media/
├── analyze_photo_quality.py        (Utility: photo blur detection + SSIM comparison)
├── analyze_video_quality.py        (Utility: video SSIM/PSNR quality comparison)
├── build_file_index.py             (Shared: O(1) file indexing)
├── camcorder_convert.py            (Video: codec conversion logic)
├── check_leftover_files.py         (Takeout: verify duplicates)
├── check_nas_archive.py            (Archive: verify NAS files exist in organized)
├── cleanup_orphaned_json.py        (Takeout: remove orphaned JSON)
├── conversion_index.py             (Video: persistent deduplication)
├── create_event_folders.py         (Reprocess: sort holiday/birthday photos into event folders)
├── photo_triage.py                 (Triage: batch blurry/duplicate management)
├── workflow_review.py              (Triage: orchestrates blur + dupes + HTML reports)
├── convert_legacy.py               (Reprocess: legacy format conversion logic)
├── duplicate_detector.py           (Archive: smart duplicate detection with caching)
├── fix_fragmented_metadata.py      (Takeout: reunite fractured projects)
├── media_utils.py                  (Shared: constants and utility functions)
├── merge_metadata.py               (Takeout: EXIF metadata writer)
├── motion_photo_extract.py         (Reprocess: handle Pixel Motion Photos)
├── organize_archive.py             (Archive: main organization script)
├── organize_media.py               (Takeout: main organization script)
├── workflow_archive.py             (Archive: master orchestrator)
├── workflow_camcorder.py           (Video: master orchestrator)
├── workflow_reprocess.py           (Reprocess: menu-driven maintenance)
├── workflow_takeout.py             (Takeout: master orchestrator)
├── README.md
├── .duration_cache.json            (Cache: video durations for fast duplicate detection)
├── TO_PROCESS/                     (Unified input: all media to process)
│   ├── Takeout/                    (Google Takeout exports)
│   ├── Takeout 2/
│   ├── Camcorder/                  (AVCHD files from camcorder)
│   ├── NAS_Archive/                (Raw media from NAS backup)
│   └── ...
├── Organized_Photos/               (Output: photos by year/month)
│   ├── 2025/
│   │   ├── 01 January/
│   │   │   ├── 2025 J Birthday - 15/   (named event sub-folder)
│   │   │   └── 01-18 Event/            (dense-day auto-detected event)
│   │   └── 12 Dad's Projects/
│   └── _TO_REVIEW_/
└── Organized_Videos/               (Output: videos by year/month)
    ├── .conversion_index.json       (Tracks all conversions for dedup)
    └── 2024/
        └── 05 May/
            └── 20240504_113916_CAM.h265.mp4
```

**Processing Workflow:**

1. **Main Processing** (workflow_takeout.py):
   - Fixes truncated extensions
   - Merges metadata for project folders
   - Organizes all files with EXIF updates and JSON cleanup
   - Rebuilds index after each Takeout directory

2. **Post-Processing** (optional, for Google Takeout fragmentation issues):
   - Run `fix_fragmented_metadata.py` to move media from dated folders to projects
   - Run `cleanup_orphaned_json.py` to remove any remaining orphaned JSON files

**Results:**

- Output: `Organized_Photos/` with year/month hierarchy, files containing their needed metadata, and extra directories containing any files needing review

---
