# process-media

Currently contains logic for parsing of Google Takeout photo exports, which I need to consolidate from multiple family members into one location for use (Shutterfly, digital photo frames, deduplication, first year videos, etc.). But will need to handle processing videos from our camcorder with stupid names, as well.

## Google Takeout Sorter Script

<!--

The code in organize_photos.py was entirely written by Claude Sonnet 4.5, and took a few combined prompts to accomplish:

i have run a google takeout task which has exported my family's personal photos for local storage. however, the files are split across five archive folders which organize photos only by year, and include supplemental-metadata files containing the very important creationTime, photoTakenTime, and geoData objects.

i would ike to combine all of the separate repeated directories into one, with directories for each full four-digit year, and subdirectories for each month in each year, in the format "01 January", "02 February", etc, and move the photo, video, and metadata files into their appropriate destination. delete the trash directories, as well as empty event folders (ones that may contain a metadata file, but no media). there are also a few folders that may or may not have specific names, may or may not be split across multiple takeout directories, and should be placed in their appropriate year directory and prefixed with the two-digit month code.

also, there are some photos that were created by myself manually and added that should have probably used the creationTime object, instead of the photoTakenTime object, as in the current first ride file. incorporate a comparison between these two dates, and if they would assign media to different locations, move the file and its corresponding metadata into a _TO_REVIEW_ directory.

(and then about 80 follow-on prompts and fixes, because I was not clear enough, as well as the AI making some odd assumptions at times)

-->

### Quick Start (Recommended):

1. Extract your Google Takeout archive(s) into the `TAKEOUT_DATA/` directory
   - Each Takeout archive should be extracted as separate folders (e.g., `Takeout`, `Takeout 2`, etc.)

2. Run the master processing script:
   ```bash
   python3 workflow.py
   ```
   This will prompt for the person's name and automatically:
   - Fix truncated file extensions (`.MP` → `.mp4`)
   - Merge JSON metadata into EXIF data (removes JSON files after)
   - Organize photos/videos by date with person tagging

3. Review results:
   - Photos: `Organized_Photos/YYYY/MM MonthName/`
   - Videos: `Organized_Videos/YYYY/MM MonthName/`
   - Conflicts: `Organized_Photos/_TO_REVIEW_/`

### Manual Step-by-Step (Advanced):

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
   python3 organize_photos.py

   # With person tagging
   python3 organize_photos.py --person "Clif"
   ```

### Processing Multiple Family Members:

For multiple household members, run the master script separately for each person's export:

```bash
# First person - extract their Takeout to TAKEOUT_DATA/, then:
python3 workflow.py
# (Enter "Clif" when prompted)

# Second person - replace TAKEOUT_DATA/ with their export, then:
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

**Usage:**
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

**What it does:**
- Handles truncated JSON filenames (`.supplemental-metada.json`, `.supplemental-me.json`, etc.)
- Uses **earliest date** between `photoTakenTime` and `creationTime`
- When dates differ by 3+ months, uses earlier as creation date and later as modification date
- Writes date/time to EXIF DateTimeOriginal
- Adds GPS coordinates from `geoData` (when non-zero)
- Works with photos (JPEG, PNG, HEIC) and videos (MP4, MOV, etc.)
- **Default behavior: overwrites existing EXIF** (use `--preserve-existing` to keep original dates)

### File Organization:

The `organize_photos.py` script consolidates photos from up to 5 Google Takeout archives into a structured organization system using a two-phase approach:

**Phase 1: Project Folder Processing**
- Identifies special project folders (e.g., "Dad's 2006 F-150 XLT", "Family History") that should remain intact as collections
- Extracts year from folder name or folder contents
- Determines the most common month from photos within the folder for prefix assignment
- Merges duplicate project folders found across multiple Takeout archives instead of creating separate copies
- Moves complete folders to year directories with format: `YYYY/MM FolderName/`

**Phase 2: Regular File Processing**
- Processes individual media files not in project folders
- **Date priority**: Filename patterns (YYYYMMDD) are checked first for speed; JSON metadata is only parsed if filename has no date
- When JSON metadata is needed, compares photoTakenTime vs creationTime - uses earlier date (later becomes modification date) when they differ by 3+ months
- Organizes files into: `YYYY/MM MonthName/` (e.g., `2025/12 December/`)
- Files with no parseable date in filename or metadata are moved to `_TO_REVIEW_/` directory

**Cleanup Phase**
- Removes empty directories and folders containing only metadata files
- Moves Trash directories to `_TO_REVIEW_/Trash_Archives/` for final review

**Key Features:**

- Date conflict detection: files where photoTakenTime and creationTime differ by 3+ months
- Project folder merging: Prevents duplicate folders from multiple Takeout archives
- Metadata preservation: Moves .json metadata files alongside their corresponding media files
- Fallback dating: Uses multiple strategies to determine file dates when metadata is missing
- Photo/Video separation: Photos go to Organized_Photos/, videos to Organized_Videos/

**Directory Structure:**
```
Google Takeout Photo Exports/
├── organize_photos.py
├── README.md
├── TAKEOUT_DATA/          (Extract your Takeout archives here)
│   ├── Takeout/
│   ├── Takeout 2/
│   └── ...
└── Organized_Photos/       (Output directory)
    ├── 2025/
    │   ├── 01 January/
    │   └── 07 July/
    └── _TO_REVIEW_/
        └── Trash_Archives/
```

**Results:**

- Output: `Organized_Photos/` with year/month hierarchy, files containing their needed metadata, and extra directories containing any files needing review
