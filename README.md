# process-media

Currently contains logic for parsing of Google Takeout photo exports, which I need to consolidate from multiple family members into one location for use (Shutterfly, digital photo frames, deduplication, first year videos, etc.). But will need to handle processing videos from our camcorder with stupid names, as well.

## Google Takeout Sorter Script

<!--

The code in organize_media.py was entirely written by Claude Sonnet 4.5, and took a few combined prompts to accomplish:

i have run a google takeout task which has exported my family's personal photos for local storage. however, the files are split across five archive folders which organize photos only by year, and include supplemental-metadata files containing the very important creationTime, photoTakenTime, and geoData objects.

i would ike to combine all of the separate repeated directories into one, with directories for each full four-digit year, and subdirectories for each month in each year, in the format "01 January", "02 February", etc, and move the photo, video, and metadata files into their appropriate destination. delete the trash directories, as well as empty event folders (ones that may contain a metadata file, but no media). there are also a few folders that may or may not have specific names, may or may not be split across multiple takeout directories, and should be placed in their appropriate year directory and prefixed with the two-digit month code.

also, there are some photos that were created by myself manually and added that should have probably used the creationTime object, instead of the photoTakenTime object, as in the current first ride file. incorporate a comparison between these two dates, and if they would assign media to different locations, move the file and its corresponding metadata into a _TO_REVIEW_ directory.

(and then about 80 follow-on prompts and fixes, because I was not clear enough, as well as the AI making some odd assumptions at times)

-->

### Quick Start (Recommended):

1. Extract your Google Takeout archive(s) into the `TAKEOUT_DATA/` directory
   - Each Takeout archive should be extracted as separate folders (e.g., `Takeout`, `Takeout 2`, etc.)
   - Can process 50+ Takeout directories in one run

2. Run the master processing script:
   ```bash
   python3 workflow.py
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
   python3 fix_truncated_extensions.py TAKEOUT_DATA/
   ```
2. **Merge metadata into EXIF:**
   ```bash
   python3 merge_metadata.py TAKEOUT_DATA/ --recursive --remove-json
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
# First person - extract their Takeout to /TAKEOUT_DATA/, then:
python3 workflow.py
# (Enter "Clif" when prompted)

# Second person - replace the /TAKEOUT_DATA/ content with their export, then:
python3 workflow.py
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
python3 merge_metadata.py TAKEOUT_DATA/ --recursive

# Preserve existing EXIF data (only fill if missing)
python3 merge_metadata.py TAKEOUT_DATA/ --recursive --preserve-existing

# Remove JSON files after successful merge
python3 merge_metadata.py TAKEOUT_DATA/ --recursive --remove-json
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
- Files with no parseable date are moved to `_TO_REVIEW_/` with year-based organization:
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
- **Final metadata merge**: workflow.py runs merge_metadata.py on `_TO_REVIEW_/` to update any files that were skipped during organization

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

**Directory Structure:**
```
Google Takeout Photo Exports/
├── organize_media.py               (Main organization script)
├── merge_metadata.py               (EXIF metadata writer)
├── workflow.py                     (Master orchestrator)
├── fix_fragmented_metadata.py      (Post-processing: reunite fractured projects)
├── cleanup_orphaned_json.py        (Post-processing: remove orphaned JSON)
├── check_leftover_files.py         (Verify remaining files are duplicates)
├── media_utils.py                  (Shared: constants and utility functions)
├── build_file_index.py             (Shared: O(1) file indexing for duplicate detection)
├── README.md
├── TAKEOUT_DATA/                   (Extract your Takeout archives here)
│   ├── Takeout/
│   ├── Takeout 2/
│   └── ... (supports 50+ directories, provided you have three hours for processing)
└── Organized_Photos/               (Output directory)
    ├── 2025/
    │   ├── 01 January/
    │   ├── 07 July/
    │   └── 12 Dad's Projects/     (Project folder)
    └── _TO_REVIEW_/
        ├── 2018/                   (Year-organized review)
        ├── Wallpapers/             (Auto-detected wallpaper files)
        └── Trash_Archives/
```

**Processing Workflow:**

1. **Main Processing** (workflow.py):
   - Fixes truncated extensions
   - Merges metadata for project folders
   - Organizes all files with EXIF updates and JSON cleanup
   - Rebuilds index after each Takeout directory

2. **Post-Processing** (optional, for Google Takeout fragmentation issues):
   - Run `fix_fragmented_metadata.py` to move media from dated folders to projects
   - Run `cleanup_orphaned_json.py` to remove any remaining orphaned JSON files

**Results:**

- Output: `Organized_Photos/` with year/month hierarchy, files containing their needed metadata, and extra directories containing any files needing review
