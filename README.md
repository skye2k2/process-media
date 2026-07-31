# process-media

Media organization and conversion tools for consolidating family photos and videos from multiple sources:

1. **Google Takeout Processing** - Organize exported photos/videos from multiple family members, extract metadata from JSON, write to EXIF, deduplicate, and sort into year/month folders
2. **Archive Processing** - Organize raw media files from NAS archives, phone backups, or other sources without JSON metadata, using smart duplicate detection
3. **Video Conversion** - Convert older video codecs (H.264, MPEG-2, AVCHD) to H.265 for archival, automatically skipping files already in modern formats
4. **Reprocessing** - Maintain already-organized media: convert legacy formats in-place, detect duplicates, and future tools

All workflows use a unified `TO_PROCESS/` input directory and shared `Organized_Photos/` and `Organized_Videos/` output directories.

---

## Setup

Python dependencies live in a **project-local virtual environment**. This is not optional convenience: a Homebrew upgrade to Python 3.14 previously orphaned the globally-installed packages, and because `photo_triage.py` exits immediately when OpenCV is unavailable, the entire photo review workflow was silently disabled for months. Pinning inside `.venv/` makes the toolchain immune to system Python churn.

```bash
# One-time setup
brew install exiftool ffmpeg          # external tools, not pip-managed
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# Verify the install (should report "Ran 75 tests ... OK" with no OpenCV warning)
.venv/bin/python test_core.py
```

Run **every** script through the venv interpreter, not bare `python3`:

```bash
.venv/bin/python workflow_review.py --open
.venv/bin/python workflow_archive.py TO_PROCESS/NIKON --dry-run
```

If you see `WARNING: OpenCV not installed`, you are running the system Python instead of `.venv/bin/python`. Blur scoring, perceptual-hash duplicate detection, and SSIM comparison all depend on OpenCV, so that warning means quality analysis is silently unavailable.

<!--

The code in organize_media.py was initially written by Claude Sonnet 4.5, and took a few combined prompts to get started:

i have run a google takeout task which has exported my family's personal photos for local storage. however, the files are split across five archive folders which organize photos only by year, and include supplemental-metadata files containing the very important creationTime, photoTakenTime, and geoData objects.

i would ike to combine all of the separate repeated directories into one, with directories for each full four-digit year, and subdirectories for each month in each year, in the format "01 January", "02 February", etc, and move the photo, video, and metadata files into their appropriate destination. delete the trash directories, as well as empty event folders (ones that may contain a metadata file, but no media). there are also a few folders that may or may not have specific names, may or may not be split across multiple takeout directories, and should be placed in their appropriate year directory and prefixed with the two-digit month code.

also, there are some photos that were created by myself manually and added that should have probably used the creationTime object, instead of the photoTakenTime object, as in the current first ride file. incorporate a comparison between these two dates, and if they would assign media to different locations, move the file and its corresponding metadata into a _TO_REVIEW_ directory.

(and then about 80 follow-on prompts and fixes for this initial processing, because I was not clear enough, as well as the AI being forgetful or making some odd assumptions at times)

Additional key features were added incrementally to provide:

- multithreaded processing, and both regular and helpful logging of progress and results
- naming, metadata management, deduplication, re-encoding, and sorting of camcorder video files
- metadata management, deduplication, and sorting of DSLR photos
- automatic event subfolder categorization (birthdays, holidays, highly-photographed days)
- photo analysis tools for identifying blur, duplication, and over-captured events, via an HTML review page, which generate scripts for deletion
- specialization of scripts for better adherence to engineering principles, better separation of concerns, and reusability

-->

---

## Google Takeout Sorter Script

### Quick Start (Recommended):

1. Extract your Google Takeout archive(s) into the `TO_PROCESS/` directory
   - Each Takeout archive should be extracted as separate folders (e.g., `Takeout`, `Takeout 2`, etc.)
   - Can process 50+ Takeout directories in one run

2. Run the master processing script:
   ```bash
   python3 workflow_takeout.py
   ```
   This will prompt for the person's name and automatically:
   - Fix truncated file extensions (`.MP` → `.mp4`)
   - Merge JSON metadata into EXIF data for project folders
   - Organize photos/videos by date with person tagging
   - Write EXIF metadata from JSON during organization (removes JSON files after)
   - Rebuild file index after each Takeout for accurate duplicate detection

3. Post-processing cleanup (if needed):
   ```bash
   # Reunite fractured project directories (files split across dated folders)
   python3 fix_fragmented_metadata.py --dry-run  # Preview first
   python3 fix_fragmented_metadata.py            # Actually move files

   # Clean up orphaned JSON files
   python3 cleanup_orphaned_json.py        # Interactive mode
   python3 cleanup_orphaned_json.py --yes  # Non-interactive (batch processing)
   ```

4. Review results:
   - Photos: `Organized_Photos/YYYY/MM MonthName/`
   - Videos: `Organized_Videos/YYYY/MM MonthName/`
   - Conflicts: `Organized_Photos/_TO_REVIEW_/`

<details>

<summary>**Advanced Metadata Management:**</summary>

If you prefer to run each step individually:

1. **Fix truncated extensions:**
   ```bash
   python3 fix_truncated_extensions.py TO_PROCESS/
   ```
2. **Merge metadata into EXIF:**
   ```bash
   python3 merge_metadata.py TO_PROCESS/ --recursive --remove-json
   ```
3. **Organize photos:**
   ```bash
   # Basic usage
   python3 organize_media.py

   # With person tagging
   python3 organize_media.py --person "Clif"
   ```

</details>

### Processing Multiple Family Members:

For multiple household members, run the master script separately for each person's export:

```bash
# First person - extract their Takeout to TO_PROCESS/, then:
python3 workflow_takeout.py
# (Enter "Clif" when prompted)

# Second person - replace the TO_PROCESS/ content with their export, then:
python3 workflow_takeout.py
# (Enter "Nicole" when prompted)
```

Each person's files will be tagged and organized. Filename conflicts are automatically resolved by appending the person's name.

### Merging Metadata into EXIF

The JSON metadata part of Google Takeout exports is directly into your photo/video files using [merge_metadata.py](merge_metadata.py). This eliminates the need for separate .json files cluttering your directories.

**Why merge metadata?**
- Browse photos without separate JSON files
- EXIF data travels with the file
- Works with standard photo viewers and editors
- Includes date/time and GPS coordinates (when available)

<details>

<summary>**Advanced Metadata Management:**</summary>

```bash
# Install exiftool (required)
brew install exiftool  # macOS
# or: apt-get install libimage-exiftool-perl  # Linux

# Merge metadata (overwrites EXIF with Google's earliest date)
python3 merge_metadata.py TO_PROCESS/ --recursive

# Preserve existing EXIF data (only fill if missing)
python3 merge_metadata.py TO_PROCESS/ --recursive --preserve-existing

# Remove JSON files after successful merge
python3 merge_metadata.py TO_PROCESS/ --recursive --remove-json
```

</details>

**What it does:**
- Handles truncated JSON filenames (`.supplemental-metada.json`, `.supplemental-me.json`, etc.)
- Uses **earliest date** between `photoTakenTime` and `creationTime`
- When dates differ by 3+ months, uses earlier as creation date and later as modification date
- Writes date/time to EXIF DateTimeOriginal
- Adds GPS coordinates from `geoData` (when non-zero)
- Works with photos (JPEG, PNG, HEIC) and videos (MP4, MOV, etc.)
- **Default behavior: overwrites existing EXIF data** (use `--preserve-existing` to keep original dates)

### File Organization:

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

## Archive Media Processing (NAS Backups, Phone Exports)

For raw media files that don't have JSON metadata—NAS archives, phone backups, camera SD cards, etc. Unlike Google Takeout, these files rely on filename patterns and EXIF data for dating.

### Quick Start:

1. Place archive files in the `TO_PROCESS/` directory:
   ```bash
   cp -r /Volumes/NAS/Photos/Archive/* TO_PROCESS/
   ```

2. Run the archive processing workflow:
   ```bash
   python3 workflow_archive.py
   ```

3. Review results in `Organized_Photos/` and `Organized_Videos/`

### What It Does:

1. **Date extraction priority:**
   - Filename patterns: `VID_20210526_162641.mp4`, `IMG_20210526_162641.jpg`, `PXL_20210526_162641.mp4`
   - EXIF metadata (DateTimeOriginal)
   - File modification time (fallback)

2. **Smart duplicate detection** (using `duplicate_detector.py`):
   - Matches files by date pattern + video duration + file size
   - Distinguishes "exact duplicates" (≤1% size difference) from "similar" (1-20%)
   - Detects "significant difference" (20-100% size difference) and prefers smaller file
   - Detects "bloated" re-encoded files (same resolution but 2x+ larger)
   - Recommends which version to keep based on quality analysis

3. **Bloated file replacement:**
   - Google Takeout sometimes re-encodes videos at higher bitrates (4x larger!)
   - Archive workflow detects when source file is smaller with same quality
   - Replaces bloated organized file with smaller original
   - Preserves the organized file's person-name suffix (e.g., `_Clif`, `_Nicole`)

4. **Project folder handling:**
   - Identifies project folders (contain media files, not just nested directories)
   - Moves entire folder as a unit to year/month structure
   - Format: `YYYY/MM FolderName/`

### Performance Optimizations:

- **Duration caching**: Video durations are cached to `.duration_cache.json`
  - First run: ~50 seconds (ffprobe analyzes each video)
  - Subsequent runs: ~5 seconds (uses cached durations)
  - Cache invalidates when file mtime or size changes

### Options:

```bash
# Preview without making changes
python3 workflow_archive.py --dry-run

# Process from custom directory
python3 workflow_archive.py /path/to/archive

# Append owner name to every filename (model suffix added automatically)
python3 workflow_archive.py --person-suffix _Clif

# Override camera model suffix for entire batch (use only if EXIF Model is broken)
python3 workflow_archive.py --model-suffix _S3500

# Run the organizer directly (without workflow wrapper)
python3 organize_archive.py --dry-run
python3 organize_archive.py TO_PROCESS/NIKON --person-suffix _Clif
```

### Camera Model Suffix Auto-Detection:

When ingesting from a camera that uses `DSCN_XXXX.JPG` naming (Nikon CoolPix, etc.),
`organize_archive.py` reads the EXIF `Model` field for each file and appends a short
model token to the filename stem before moving it:

```
DSCN2542.JPG  (COOLPIX S3500)  →  DSCN2542_S3500.JPG
DSCN2542.JPG  (COOLPIX S3100)  →  DSCN2542_S3100.JPG
```

This prevents filename collisions when two cameras share an overlapping counter range.
Suffix order when both model and person are present: `DSCN2542_S3500_Clif.JPG`.

Auto-detection only applies to `DSCN`/`DSC`-prefixed files. `IMG_`, `VID_`, and `PXL_`
files already embed a timestamp and are unambiguous.

### Pre-Ingestion Reconciliation Tool:

Before importing a large NAS archive, use `reconcile_nikon_archive.py` to get a
read-only preview of what would happen — no files are touched:

```bash
# Fast first pass (skips byte-level MD5 comparison)
python3 reconcile_nikon_archive.py /Volumes/photosync/NIKON --no-md5

# Full pass with MD5 (slower but catches exact duplicates)
python3 reconcile_nikon_archive.py /Volumes/photosync/NIKON

# Re-display previous run without re-scanning
python3 reconcile_nikon_archive.py /Volumes/photosync/NIKON --cache-only
```

Output categories:
- `EXACT_MATCH` — byte-identical copy already in archive; safe to skip
- `DATE_SIZE_MATCH` — high-confidence duplicate by EXIF date + file size
- `DEST_COLLISION` — would land in the same folder/filename as an existing file
  with different content (requires manual review before ingesting)
- `NEW_CONTENT` — not yet in archive; ready to ingest
- `NO_EXIF` — no date available; use `apply_date_from_neighbor.py` to fix

### Fixing NO_EXIF Files:

Files in a cluster with no EXIF date (typically edited copies of deleted originals)
can be stamped with the date of their nearest DSCN-numbered predecessor:

```bash
# Dry run to verify what dates will be applied
python3 apply_date_from_neighbor.py \
    --reconcile-cache .reconcile_cache.json \
    --dry-run --verbose

# Apply (borrows date from nearest preceding file with valid EXIF)
python3 apply_date_from_neighbor.py \
    --reconcile-cache .reconcile_cache.json

# Override with a specific date when the neighbor date is known-wrong
python3 apply_date_from_neighbor.py \
    --reconcile-cache .reconcile_cache.json \
    --date 20190601
```

---

## Video Codec Conversion Script

Converts older video codecs (H.264, MPEG-2, AVCHD) to H.265/HEVC for archival storage. Particularly useful for camcorders with unhelpful sequential naming (`00000.MTS`, `00001.MTS`, etc.) that resets when memory cards are initialized.

**Smart codec detection**: Files already encoded in modern formats (H.265, AV1, VP9) are automatically skipped.

### Quick Start:

1. Place video files in the `TO_PROCESS/` directory (same as Takeout):
   ```bash
   # Copy camcorder files, old phone videos, etc.
   cp /path/to/camcorder/*.MTS TO_PROCESS/Camcorder/
   ```

2. Run the conversion workflow:
   ```bash
   python3 workflow_camcorder.py
   ```

3. Review results in `Organized_Videos/YYYY/MM MonthName/`

### What It Does:

1. **Scans for video files** in `TO_PROCESS/` (recursively, all subdirectories)
2. **Detects codec** via ffprobe—skips files already in H.265/AV1/VP9
3. **Checks persistent index** for content already processed in prior runs
4. **Extracts creation date** from metadata (exiftool → ffprobe → file mtime fallback)
5. **Converts to H.265/HEVC** using libx265 software encoding for archival quality
6. **Renames files** to `YYYYMMDD_HHMMSS_CAM.h265.mp4` format (the `_CAM` suffix distinguishes camcorder-sourced videos from phone/Takeout videos)
7. **Writes EXIF metadata** with the original creation date
8. **Organizes** into `Organized_Videos/YYYY/MM MonthName/` structure
9. **Updates index** with conversion details for future deduplication
10. **Deletes originals** after successful conversion (with confirmation prompt)

### Persistent Deduplication:

The script maintains a `.conversion_index.json` file in `Organized_Videos/` to track all converted content across multiple runs. This is particularly useful when:

- **Same camcorder files exist on multiple backup drives** (duplicates with identical content but from different sources)
- **Processing is interrupted** and resumed later
- **New backup drives are discovered** containing already-processed content

The index key is based on `creation_date + file_size`, which uniquely identifies content regardless of the useless sequential filenames (00000.MTS, 00001.MTS) that camcorders use. When a file matches an existing index entry, it's skipped with a "already in index" message showing the existing output path.

### Codecs Converted vs Skipped:

| Converted (older/larger) | Skipped (already efficient) |
|--------------------------|----------------------------|
| H.264/AVC | H.265/HEVC |
| MPEG-2 | AV1 |
| MPEG-4 Part 2 | VP9 |
| Motion JPEG | |
| VC-1, WMV | |

### Options:

```bash
# Preview what would happen without making changes
python3 workflow_camcorder.py --dry-run

# Keep original files after conversion
python3 workflow_camcorder.py --keep-originals

# Process files from a custom directory
python3 workflow_camcorder.py /path/to/videos

# Adjust encoding quality (lower CRF = better quality, larger file, don't go below 18)
python3 workflow_camcorder.py --crf 18 --preset slower
```

### Encoding Settings:

Default settings optimize for archival quality with reasonable file sizes:

| Setting | Default | Description |
|---------|---------|-------------|
| CRF | 20 | Quality factor (18-23 is visually lossless to excellent) |
| Preset | slow | Encoding speed/compression tradeoff |
| Audio | AAC 192k | Standard quality audio |

Lower CRF values produce better quality but larger files. The `slow` preset provides better compression than `medium` at the cost of longer encoding time—worthwhile for archival purposes.

### Requirements:

- **ffmpeg** with libx265: `brew install ffmpeg`
- **exiftool**: `brew install exiftool`

The output directory is shared with the Google Takeout workflow, so all videos end up in the same organized structure.

---

## Reprocessing Workflow

Menu-driven workflow for maintaining already-organized media files. Unlike the import workflows, this operates on files that are already in `Organized_Photos/` and `Organized_Videos/`.

### Quick Start:

```bash
python3 workflow_reprocess.py
```

This presents an interactive menu with available actions:

### Available Actions:

1. **Convert Legacy Formats**
   - Scans `Organized_Videos/` for AVI, MTS, WMV, and other legacy formats
   - Converts to H.265/HEVC using the same quality settings as camcorder conversion
   - Replaces original files after verifying conversion is valid
   - Dry-run by default, then prompts before actual conversion

2. **Duplicate Check**
   - Scans organized directories for potential duplicate files
   - Uses duration + size matching to identify duplicates
   - Reports files with same base name in multiple locations
   - Informational only—manual review recommended before removal

3. **Deep Codec Scan**
   - Like Convert Legacy Formats, but also checks MP4/MOV/MKV files
   - Identifies H.264 videos that could benefit from H.265 conversion
   - Slower scan but catches more conversion candidates

4. **Fix Motion Photos**
   - Finds Google Pixel "Motion Photos" (videos with embedded still images)
   - These dual-stream files don't play in macOS QuickLook/Preview
   - Options: extract stills, delete videos, or strip embedded still to fix QuickLook
   - Can also be run directly: `python3 motion_photo_extract.py --scan`

5. **Create Event Folders**
   - Groups holiday and birthday photos from month folders into named event sub-folders, created *inside* the month folder (e.g., `02 February/2024 J Birthday - 14/`)
   - Named holiday/birthday events (run first):
     - **Births**: birth year only, ±1 day window — folder: `{YEAR} {INITIAL} Birth` (e.g., `2010 J Birth`)
     - **Birthdays**: all years after birth year, ±5 day window — folder: `{YEAR} {INITIAL} Birthday - {AGE}` (e.g., `2024 J Birthday - 14`)
     - **Fourth of July**: July 4 only
     - **Halloween**: October 31 only
     - **Thanksgiving**: Tuesday–Friday of the week containing the 4th Thursday of November
     - **Christmas**: December 24–25
   - Automatic dense-day event detection (run after holidays, so no overlap):
     - Any day with ≥35 photos qualifies; consecutive qualifying days merge into one span
     - Folder name: `MM-DD Event` or `MM-DD–MM-DD Event` (no year prefix — already implicit in the containing year directory)
     - Threshold is tunable: `--event-threshold N` (0 disables *discovery* of new clusters; adoption still runs, see below)
   - **Re-run safety (adoption):** loose photos whose day already has an event folder are moved into that existing folder regardless of the threshold, shown as `[into existing]` in the output. This matters when re-running after a new import: without it, a batch that adds only a handful of photos to an already-filed day would leave them stranded loose in the month folder, and a batch that adds *many* photos to a day covered by a span folder would create a competing sibling folder splitting one event in two. Named holiday/birthday folders already merged by name, so this only affected `MM-DD Event` folders.
   - Only considers direct children of `MM MonthName` folders — photos already in any sub-folder are never touched
   - Any `.supplemental-metadata[...].json` sidecar files are co-moved with their photo
   - Analysis cache entries (blur, hashes, EXIF date) travel with moved files — no re-analysis needed afterward
   - Dry-run by default; use `--execute` to move files
   - Can also be run directly: `python3 create_event_folders.py [--year YYYY] [--execute] [--verbose] [--event-threshold N]`

### Why Reprocessing?

When files are imported via Archive Processing, they may include:
- AVI files from old camcorders that were copied without conversion
- MTS files that bypassed the camcorder conversion workflow
- Legacy formats from external sources (phone backups, DVDs, etc.)

The reprocessing workflow handles these after-the-fact, converting them in-place without disrupting your organized folder structure.

---

## Quality Analysis Tool

Objective video quality comparison using SSIM and PSNR metrics. Useful for:
- Determining if a re-encoding results in visible quality loss
- Comparing different CRF values to find the optimal balance of quality and size
- Validating DVD/Blu-ray rip quality before committing to a setting
- A/B testing encoding presets

### Quick Start:

```bash
# Compare two existing files
python3 analyze_video_quality.py original.mov converted.mp4

# Test specific CRF values (creates test encodes)
python3 analyze_video_quality.py original.mkv --test-crf 18 20 22 24

# Limit analysis to first 60 seconds (faster for long videos)
python3 analyze_video_quality.py original.mov converted.mp4 --duration 60

# Save output to specific directory
python3 analyze_video_quality.py original.mov --test-crf 20 --output-dir ./quality_tests/
```

### Understanding Quality Metrics:

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

### CRF Comparison Mode:

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

### Frame Extraction:

The tool automatically extracts comparison frames at 10%, 30%, 50%, 70%, and 90% through the video for visual spot-checking. These are saved as PNG files in the output directory.

### Example Workflow for DVD Ripping:

```bash
# 1. Rip a short sample (or full episode) at maximum quality
HandBrakeCLI -i /dev/dvd -o sample_lossless.mkv --encoder x265 --quality 0

# 2. Test various CRF values to find the sweet spot
python3 analyze_video_quality.py sample_lossless.mkv --test-crf 18 20 22 24 26

# 3. Review the comparison table and extracted frames
open /var/folders/.../quality_analysis_.../frames/

# 4. Once you've found your ideal CRF, use it for the full rip
```

---

## Photo Quality Analysis Tool

Batch photo analysis for blur detection and version comparison. Optimized for processing thousands of images quickly using OpenCV.

### Requirements:

(note: this takes a significant amount of time to download and install, and it is possible that sub-dependencies do not make themselves known on the path)

```bash
brew install opencv
```

### Quick Start:

```bash
# Detect blurry photos in a directory
python3 analyze_photo_quality.py blur Organized_Photos/2024/

# Compare two specific images
python3 analyze_photo_quality.py compare original.jpg edited.jpg

# Find and compare all -edited pairs
python3 analyze_photo_quality.py pairs Organized_Photos/2024/

# Full analysis (blur + pairs) with CSV output
python3 analyze_photo_quality.py analyze Organized_Photos/ --output results.csv
```

### Blur Detection:

Uses Laplacian variance to measure edge sharpness. Higher score = sharper image.

| Score | Interpretation |
|-------|---------------|
| 150+ | Sharp (good quality) |
| 80 - 150 | Decent (acceptable quality) |
| 40 - 80 | Soft (may be intentional or minor focus issues) |
| 20 - 40 | Blurry (likely focus issues, needs review) |
| < 20 | Very Blurry (high-confidence auto-triage candidates) |

**Note:** Portraits with intentional bokeh will score lower in blurred background regions. Low-texture images (walls, carpet, sky) are exempt from blur classification since Laplacian variance is naturally low for uniform subjects. The tool reports scores for you to interpret based on content context.

### Edited Pair Detection:

Automatically finds files with `-edited`, `_edited`, ` edited`, or ` (edited)` suffixes and compares them to their originals:

- **SSIM comparison**: How similar are the images?
- **Blur comparison**: Which version is sharper?
- **Size comparison**: File size differences

### Example Workflow:

```bash
# 1. Find all blurry photos for review
python3 analyze_photo_quality.py blur Organized_Photos/ --output blurry.csv

# 2. Review the CSV in your spreadsheet app, decide which to delete

# 3. Find edited pairs to decide which versions to keep
python3 analyze_photo_quality.py pairs Organized_Photos/
```

---

## Photo Triage Tool

Batch photo organization tool for identifying and managing blurry photos and duplicates. Built on top of `analyze_photo_quality.py` with smart caching, context-aware review, and safe deletion workflows.

### Requirements:

```bash
brew install opencv
pip install pillow-heif  # For HEIC/HEIF support (Apple photos)
```

### Quick Start:

```bash
# Run the full review pipeline (blur cache + review report + browse report)
python3 workflow_review.py Organized_Photos/ --open

# Or run individual steps manually:
python3 photo_triage.py auto-triage --dry-run        # Populate blur cache + detect dupes
python3 photo_triage.py review-issues --open          # Blurry/duplicate HTML report
python3 photo_triage.py browse --open                 # All-photos browsable HTML
```

### Commands:

| Command | Description |
|---------|-------------|
| `summary` | Summarize issues by folder (blurry counts, duplicates) |
| `blurry` | Find blurry photos with surrounding context |
| `bursts` | Detect photo bursts (rapid sequences) |
| `auto-triage` | Move high-confidence issues to review folders |
| `review-issues` | Generate HTML report for blurry/duplicate review |
| `browse` | Generate HTML report browsing ALL photos by directory |
| `undo` | Restore files moved by auto-triage |

### HTML Reports:

Two HTML reports are available:

**`review-issues`** — Interactive report for blurry and duplicate photos:
- Safe-to-delete blurry photos (with sharp alternatives nearby)
- Photos needing manual review (blurry, no clear alternative)
- Duplicate groups (exact and perceptual) with recommended keeper
- Each card shows the photo alongside context neighbors, blur scores, and dates
- Click any image to view full-size (Escape to close)

**`browse`** — All photos organized by directory with time grouping:
- Every photo in every folder, for visual scanning
- Collapsible directory sections

```bash
# Generate both reports at once (recommended)
python3 workflow_review.py Organized_Photos/ --open

# Or individually:
python3 photo_triage.py review-issues Organized_Photos/2020 --open
python3 photo_triage.py browse Organized_Photos/ --open

# Skip duplicate scanning (faster)
python3 photo_triage.py review-issues Organized_Photos/ --no-duplicates
```

### Auto-Triage Workflow:

Auto-triage identifies high-confidence candidates and moves them to review folders:

```bash
# Preview what would be moved (also pre-populates cache)
python3 photo_triage.py auto-triage --dry-run

# Move files to _TO_REVIEW_/Blurry/ and _TO_REVIEW_/Duplicates/
python3 photo_triage.py auto-triage

# Use symlinks instead (keeps originals in place for context)
python3 photo_triage.py auto-triage --symlink
```

**Symlink mode** (recommended): Creates symlinks in the review folders pointing to the originals. This preserves the original files in their context, making it easier to review "Show Original" in Finder. After reviewing, delete the originals directly.

**Move mode**: Physically moves files to review folders. Use `undo` to restore if needed.

### Caching:

Blur analysis results are cached per-folder in `.analysis_cache.json` files. The first full scan takes 15-20 minutes for 30k photos, but subsequent runs use cached values and complete in seconds.

```bash
# Check cache hit rate during scan
python3 photo_triage.py auto-triage --dry-run
# Output: "Progress: 5000/30000 (98% cached)"
```

### Undo:

All moves are recorded in `_TO_REVIEW_/triage_manifest.json`. To restore:

```bash
# Preview what would be restored
python3 photo_triage.py undo Organized_Photos/ --dry-run

# Actually restore files
python3 photo_triage.py undo Organized_Photos/
```

### Blur Thresholds:

| Score | Classification | Auto-triage action |
|-------|---------------|-------------------|
| < 30 | Very blurry | Move if sharp neighbor exists |
| 30-100 | Blurry | Flag for manual review |
| > 100 | Acceptable | Keep |

### Example Workflow:

```bash
# 1. Generate review and browse reports (also warms blur cache)
python3 workflow_review.py Organized_Photos/ --open

# 2. Review in browser, note which photos to delete

# 3. Run triage with symlinks to stage removals
python3 photo_triage.py auto-triage --symlinks

# 4. Delete confirmed bad photos from their original locations

# 5. Clean up empty symlinks in _TO_REVIEW_/
find Organized_Photos/_TO_REVIEW_ -type l ! -exec test -e {} \; -delete
```

<!--

## NEXT:

### NEXT THOUGHTS, IDEAS, CONSIDERATIONS, AND PROMPTS:


TODO:

- BUG: identical duplicates are still not being called out as such. it would be good to figure out why
- BUG: the duplicate resolver prioritizes "newer" copies or edits. many times, this appears be a rounding difference, as the timestamps differ by a single microsecond. and, when shared with someone, that folder sharing date is always *after* the photo time, so the shared photo in an odd folder is what it preselected for keeping, which is less than ideal.

- it might be better to just run a check across all takeout shared directories when detected to see if all photos exist in their proper places, and then just remove those directories, because this has caused a bunch of cleanup drama
- we might need to add the ability to handle the NIKON DSCN-prefixed photos, some of which we have subsequently renamed and moved into various project folders, or ended up in TO_REVIEW, and then copy over and process the NIKON SD card (and determine if any of those are missing, as well)
- the duplicate resolver should also take resolution into account, because often nicole gets photos thrown at her through text, and then gets the originals, and the smaller photos consistently calculate out to a higher blur score. we want to keep the one with the higher resolution for perceptually similar photos. commonly it is a larger filesize, but if two photos have a very high ssim, the same resolution, and different filesizes, the smaller should probably win
- find our missing home movies are (2013-2016, 2017-2019). check archives BEFORE re-syncing with our newest data
- find our old dvd we made of our first year of marriage and college together, which should have our photos, as well, especially the ones from our first and second little nikon pocket cameras, to be able to add, in addition to our wedding photo dvd in its entirety as an event
- i think i would like to add a test directory to this project containing each typical and problem file we are handling, to be able to exercise the code fully in a closed system of tests that cover each base and edge case rather than spend half an hour re-running each time just to see if the new reprocessing worked.

- DON'T FORGET TO FIGURE OUT HOW TO SYNC OUR OLD THEORETICALLY HIGH-QUALITY GOOGLE PHOTO EXPORT WITH THIS STUFF AND SEE IF THERE'S A DIFFERENCE.
   - POTENTIAL FOR QUALITY CONFLICTS: oh, and there is also the possibility of duplicate photos that may or may not have the same name, but have the same data, just at a smaller resolution (history: previous google takeout export at full-resolution, filesize reduction for cloud-based files, then a subsequent google takeout which includes the reduced-size copies of originals)
- THEN DO THE SAME KIND OF PROCESSING ACROSS OUR OLD PHOTOSYNCED DATA (HAD AN APP AT ONE POINT THAT COPIED ORIGINAL PHOTOS TO THE NAS FOR REDUNDANCY), AND SEE IF WE HAVE EVERYTHING.
   - ^^^ SEE THE ORIGINAL PHOTOSYNC FILES FROM THE PREVIOUS ARCHIVE, AND IF THEY REALLY ARE HIGHER-RESOLUTION, OR IF ANY FROM ANYWHEN ACTUALLY MATCH THAT, BEFORE BUILDING IN MORE COMPLEXITY
- FIGURE OUT HOW BEST TO ADD TAGS FOR BEST OF'S, PEOPLE AND EVENTS?
- WE ALSO NEED TO FIGURE OUT HOW BEST TO RESOLVE THE HUNDREDS OF -EDITED FILES, MANY OF WHICH DON'T ACTUALLY MAKE A DRAMATIC ENOUGH IMPROVEMENT TO MERIT THE SPACE, INSTEAD OF KEEPING THE ORIGINAL, AND IF WE WANT TO DO SOMETHING WITH IT, EDITING WITH MODERN PHOTO PROCESSING FOR BETTER RESULTS.
- POTENTIAL ISSUE: how do we handle reprocessing? if we went through and allowed most of the high-confidence and duplicate deletions, and only made it partway through the one left over for painstaking manual review, how do we avoid dealing with ones we explicitly marked as keep all over again the next runthrough? are we adding the KEEP designation to the cache? are there other potential issues?
- what is the best way to potentially re-sync with google photos, so that we can _actually_ save space? or do we just delete everything nonessential, and call it good? or can we keep track of the removed files and build a tool to interact with google photos to remove them in the cloud, as well? i have kept each of the removal scripts, so far, which has output that could potentially be used toward this end.
- and then we need all of this to work with pre-existing data on our nas, so that we don't have to transfer hundreds of gigabytes of nas data to a local directory to be able to sort, deduplicate, compare, and the like, going forward. for the future, we want a very smooth process of 1) add the files to the processing folder, and 2) run the import (and analyze) script. i never want to do a full takeout, again (because we have gone through and removed thousands of blurry, unnecessary, or duplicate photos), just grab the last couple of months, and boom. ensure that the removal scripts will work correctly with nas-based links. smash together the cache removal, recache, and re-browse functionality.

-->
