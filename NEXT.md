# NEXT.md — Analysis, Priorities, and Planned Work

> Generated on 2026-04-30 from analysis of the full codebase, `_CONVERSATION.md` session history, and README TODO list.
> This file is the "trail of breadcrumbs" for the next session after this conversation compacts out of memory.

---

## Context for Future Sessions

**What this project does:** A multi-script Python toolkit for consolidating family photos/videos from Google Takeout, NAS archives, and phone backups into `Organized_Photos/` and `Organized_Videos/` with year/month hierarchy. Includes photo triage (blur detection, duplicate grouping, HTML review pages), video conversion (H.264→H.265), and event folder creation.

**Current state:** The import/organization pipeline is stable and has processed 30k+ photos across multiple family members. The triage/review tools work but have known bugs in keeper selection and decision persistence. HTML review pages recently received lightbox enhancements (keep/remove outline, spacebar toggle, warning footer, up/down navigation, blur badges).

**Key architectural facts:**
- Two separate duplicate detection systems exist: `scan_for_duplicates()` (MD5 + pHash, used by `photo_triage.py`) and `DuplicateDetector` (date pattern + duration + size, used by import workflows). They share no logic.
- Per-directory `.analysis_cache.json` files store blur scores, MD5, pHash, and EXIF dates. These do NOT store user triage decisions.
- HTML review decisions live exclusively in browser `localStorage`. Clearing browser data = lost decisions.
- `photo_triage.py` is 4400+ lines, generating two full HTML apps with inline JS/CSS.

---

## Confirmed Bugs

### BUG-1: Keeper selection uses filesystem mtime, not EXIF date

**Impact:** HIGH — When multiple copies exist, the file with the newest filesystem modification time is kept, regardless of which is the true original. Google Takeout export dates, file copy dates, and trivial microsecond rounding differences all corrupt this heuristic. The user explicitly reported this: "the timestamps differ by a single microsecond" and "the shared photo in an odd folder is what is preselected for keeping."

**Root cause:** Both `auto-triage` (line ~1016) and `_render_duplicate_group()` (line ~3993) sort by `Path.stat().st_mtime` descending, blindly keeping index 0.

**Fix approach:**
1. Prefer EXIF `DateTimeOriginal` (available in the analysis cache) as the primary sort key
2. Use `st_mtime` as fallback when EXIF is unavailable
3. Prefer the file in a "proper" year/month folder over one in `_TO_REVIEW_/` or a shared-photo directory
4. When timestamps are within 1 second of each other, apply tiebreakers: prefer non-`_TO_REVIEW_` path → prefer larger file size → prefer shorter filename (less likely to be a copy)

**Risk:** Changes to keeper selection affect both auto-triage (file moves) and HTML rendering (pre-selected removals). Must verify both code paths.

---

### BUG-2: Perceptually similar duplicates don't compare resolution

**Impact:** MEDIUM — A full-resolution photo and a texted/compressed thumbnail with similar perceptual hash default to "keep newest by mtime." The user explicitly requested: "the duplicate resolver should also take resolution into account."

**Root cause:** `_render_duplicate_group()` and auto-triage only sort by mtime. No image dimensions are read or compared for pHash-similar groups.

**Fix approach:**
1. For perceptually similar (non-exact-MD5) groups: read image dimensions via cache or Pillow
2. Prefer the highest resolution (pixel count) as the keeper
3. If resolutions match, fall back to the EXIF-date-based logic from BUG-1
4. Display resolution in the HTML review cards for transparency

**Dependency:** Requires storing image dimensions in the analysis cache (new field).

---

### BUG-3: Identical duplicates not being reported

**Impact:** MEDIUM — User reports "identical duplicates are still not being called out as such."

**Likely causes (in order of probability):**
1. Files that are truly byte-identical but live in directories excluded from scanning (e.g., inside event subfolders created by `create_event_folders.py`)
2. Cache staleness: if files were moved/renamed after hash computation, cache entries keyed by old paths won't match
3. Files where hash computation silently fails (unreadable/corrupted) — these go to `results['errors']` and are never grouped

**Diagnostic steps:**
1. Create a test script that takes two known-identical files and traces the `scan_for_duplicates()` path to see where they diverge
2. Check whether event subfolders are being excluded from the scan
3. Verify cache key stability after file moves

---

### BUG-4: Shell script export has injection vulnerabilities

**Impact:** MEDIUM (security) — Filenames containing `$`, backticks, or `"` can execute arbitrary commands when the exported removal script is run.

**Root cause:**
- Browse-all export: escapes `"` but not `$` or backticks
- Review-issues export: does ZERO escaping

**Fix approach:** Use single-quoted paths in the generated script. Escape embedded single quotes via `'\''` (close quote, literal quote, reopen quote). This is the only shell-safe approach for arbitrary filenames.

---

## Engineering Concerns (Non-Bug)

### CONCERN-1: No persistence of keep/remove decisions across sessions

RULING: Skip, for now

**Impact:** HIGH (workflow) — If you're partway through reviewing thousands of photos and either clear browser data, switch browsers, or regenerate the HTML, all decisions are lost. The README TODO explicitly asks: "are we adding the KEEP designation to the cache?"

**Recommended approach:**
1. Add a `decision` field to `.analysis_cache.json` entries: `"keep"`, `"remove"`, or absent (unreviewed)
2. When generating HTML, pre-populate the UI state from cached decisions
3. Add an "Import Decisions" button in the HTML that reads a JSON file (exported from the HTML) and writes to the cache via a small Python helper script
4. Alternative (simpler): a `.triage_decisions.json` file per directory (parallel to `.analysis_cache.json`)

**Trade-offs:** Writing a separate decisions file is simpler but adds another file per directory. Adding to the existing cache is cleaner but increases coupling.

---

### CONCERN-2: `photo_triage.py` is 4400+ lines (SRP violation)

**Impact:** MEDIUM (maintainability) — The file handles EXIF extraction, blur analysis, burst detection, duplicate scanning, auto-triage file moves, TWO complete HTML report generators (including 1200+ lines of inline CSS/JS), and a CLI argument parser.

**Recommendation:** Not urgent, but when making significant changes, consider extracting:
- HTML generation into `triage_html_browse.py` and `triage_html_review.py`
- Or at minimum, the CSS/JS templates into separate `.html` template files loaded at runtime

---

### CONCERN-3: Two separate duplicate detection systems

`scan_for_duplicates()` (content hash) and `DuplicateDetector` (date + size + duration) make different decisions with no shared interface. This isn't necessarily wrong — they serve different purposes (triage vs import). But it means fixes to keeper selection in one don't propagate to the other.

---

### CONCERN-4: No test infrastructure

No tests exist. The `_CONVERSATION.md` analysis concludes: "implementing TDD could have prevented 30-50% of the regression debugging sessions." For a project that processes irreplaceable family photos, this is a significant risk.

---

## TODO Items Analysis & Priority

### Priority 1 — Fix What's Broken (bugs affecting correctness of file operations)

| Item | Effort | Risk |
|------|--------|------|
| BUG-1: Fix keeper selection (mtime → EXIF date + tiebreakers) | Medium | Medium (affects existing auto-triage results) |
| BUG-4: Fix shell script injection | Small | Low |
| BUG-2: Add resolution comparison for perceptual duplicates | Medium | Low |
| BUG-3: Diagnose identical-duplicate detection failure | Small (diagnostic) | Low |

### Priority 2 — Protect Against Data Loss (workflow safety)

| Item | Effort | Risk |
|------|--------|------|
| CONCERN-1: Persist keep/remove decisions to cache/file | Medium | Low |
| Add basic test coverage for date extraction + duplicate detection | Medium | Low |
| Verify shared-folder handling (comma-named folders) | Small | Low |

### Priority 3 — Data Consolidation (the highlighted TODOs)

| Item | Effort | Notes |
|------|--------|-------|
| Find missing home movies (2013-2016, 2017-2019) | Manual | Check physical archives BEFORE processing new data |
| Process NIKON SD card + DSCN-prefixed photos | Medium | Need to extend filename patterns for `DSCN_XXXX` |
| Sync old high-quality Google Photo export | Large | Resolution comparison across exports needed (see BUG-2 fix) |
| Process PhotoSync NAS data | Medium | Depends on NAS path compatibility |
| Find and digitize old DVD (first year of marriage) | Manual | Physical media search |

### Priority 4 — Workflow Improvements

| Item | Effort | Notes |
|------|--------|-------|
| NAS-compatible HTML review (network paths) | Medium | `file://` URLs work with mounted volumes; main risk is unmounted NAS during review |
| Removal script → Google Photos cloud sync | Large | Requires Google Photos API integration (complex, rate-limited) |
| Resolve hundreds of `-edited` files | Medium | Need quality comparison (BUG-2 resolution fix enables this) |
| Combine cache-clear + recache + re-browse into single command | Small | Workflow convenience |
| Add tags for "best of", people, events | Large | Needs EXIF keyword/tag strategy and UI for tagging |

### Priority 5 — Deferred / Research Needed

| Item | Notes |
|------|-------|
| Handle reprocessing without re-reviewing kept photos | Blocked by CONCERN-1 (need decision persistence first) |
| Full NAS integration (avoid transferring hundreds of GB) | Research: test performance of tools over network mount |
| Determine if PhotoSync originals are truly higher-resolution | Manual sample comparison needed before building automation |

---

## Recommended Execution Order

### Phase A: Safety & Correctness (do first, before any more file operations)

1. **Fix shell script injection (BUG-4)** — 15-minute fix, eliminates command injection risk
2. **Fix keeper selection logic (BUG-1)** — Most impactful bug, affects every duplicate review
3. **Add resolution to perceptual duplicate comparison (BUG-2)** — Enables correct handling of texted/compressed copies
4. **Diagnose identical-duplicate miss (BUG-3)** — Create a targeted test case with known-identical files

### Phase B: Workflow Durability

5. **Persist triage decisions** — Add `decision` field or parallel `.triage_decisions.json`, so partial reviews survive browser restarts and HTML regeneration
6. **Add test cases** for:
   - Date extraction from filenames (all supported patterns)
   - Duplicate grouping (exact + perceptual)
   - Keeper selection with various scenarios (same mtime, similar mtime, different resolution)
   - Shell script output escaping

### Phase C: Data Consolidation (the real goal)

7. **Manual reconnaissance first:** Check physical NAS and archives for home movies and old DVDs before writing any code
8. **NIKON/DSCN support:** Add `DSCN_XXXX` to filename date patterns and test with actual SD card contents
9. **High-quality Google export comparison:** After BUG-2 fix is in place, compare resolutions between old export and current organized files
10. **PhotoSync data:** Mount NAS, run `check_nas_archive.py` to understand scope, then process

### Phase D: Advanced Features (future sessions)

11. **Google Photos API sync** — Research feasibility; may not be worth the complexity
12. **Tags/favorites** — Determine EXIF keyword strategy (XMP:Subject? IPTC:Keywords?)
13. **Full NAS workflow** — Test whether processing from network mount is viable performance-wise

---

## Clarifying Questions That Should Be Answered Before Phase C

1. **Home movies location:** Are the 2013-2016 and 2017-2019 home movies expected to be on the NAS, a physical DVD, or in a previous Google Takeout? This determines where to look first. A: _They *should* be on the NAS, but are not, and also should be on an old SD card that was not with the rest. I need to continue looking._

2. **PhotoSync archive:** Where exactly is the PhotoSync data? Is it currently accessible on the NAS? What's the approximate file count and total size? A: _It is on the NAS, is 58GB in size, across 8,800 files, and is under `/Volumes/photosync/Photo Uploads`. SkyePhone StylusOrig is from Clif, and NikkoPhoneOrig is Nicole_

3. **Old Google export:** Is the "old theoretically high-quality" Google export already downloaded somewhere, or does it need to be re-exported? If already downloaded, where? A: _In 2021, I did a manual Google Photo (and screenshot and video) export, prior to downsizing the backed-up quality of my phone photos and videos. It is 38GB, across 15,000 files, in a single directory, without any of the current Takeout "niceties". `/Volumes/photosync/2021GooglePhotoArchive` We will not want to put *back* anything that we have already deleted through our previous runs at processing (and I have kept the removal scripts, so we know what we have removed), but will want to analyze between these two sources of data to see if there is a quality difference._

4. **NIKON SD card:** Is this a physical SD card that needs to be inserted, or has it been copied somewhere already? A: _We already processed *one*. The problem is that we have pulled photos off of that camera for years, renamed them, and moved them around, so there are likely visual duplicates that have different creation/modified dates, or files that started out the same, but then had some manual post-processing applied. And then I just found another NIKON archive of 13GB for 5,000 photos that may be from *another* camera. We will need to reconcile what we have with what is contained there. Also available on the NAS: `/Volumes/photosync/NIKON`_

5. **Resolution threshold for "better":** When comparing two perceptually similar photos at different resolutions, what minimum difference matters? (e.g., 4032×3024 vs 3024×3024 = keep larger; 4032×3024 vs 4000×3000 = probably same photo at different crop, keep either?) A: _If there is a very high SSIM between the two, then the higher-resolution photo should win (even though I am trying to save space, I do not want to accidentally never be able to print a favorite photo because at some point we automatically decided a *thumbnail* was the right version to keep). However, to your point, if we could detect cropping in a reasonable way, then I would likely want to keep the cropped photo, but I do not see a way to do that (because I will periodically crop down, but keep the same aspect ratio, so that is not a good indicator)._

6. **`-edited` files:** When an original and edited version exist, is the current "keep edited" default correct? Or should it depend on whether the edit is significant (requires visual comparison)? A: _The automatic winner should probably be determined by if the blur factor or other indicators of poor quality measure as less._

7. **NAS workflow:** When processing NAS-hosted photos, should they be:
   - (a) Copied to local, processed, then results synced back
   - (b) Processed in-place over the network mount
   - (c) Only verified against local (no changes to NAS)

   A: _We want this process to be as clean and painless as possible. Copy+pasting and/or re-syncing feels dangerous. Only working locally is a little broken for a process that is going to be repeated at least yearly from now on--it is ok, right now, as we refine the processing logic and functionality. In-place processing seems like the only reasonable long-term option, but the most dangerous._

**Because you keep asking: NAS location of all of the files we are going to need to process as well, without doubling the file count of our new photo/video archive with duplicates everywhere: `/Volumes/photosync/`**

---

## Instructions for the Next AI Session

When this conversation compacts:

1. **Read this file (NEXT.md)** to understand the full state
2. **Read `_CONVERSATION.md`** for the history of decisions and regressions
3. **Do not regenerate HTML or run auto-triage** until BUG-1 and BUG-4 are fixed
4. **The user's priorities are correctness over features** — fix the keeper selection before adding new capabilities
5. **The most frustrating pattern from the previous session was regression introduction** — make incremental changes, verify each one
6. **KEEP/REMOVE decisions currently live only in browser localStorage** — ask the user if they have in-progress reviews before clearing or regenerating HTML
7. **`photo_triage.py` is 4000+ lines** — read the specific section you need, don't try to hold the whole file in context
8. **The analysis cache (`get_analysis_cache()`)** stores blur, MD5, pHash, and EXIF date per file. It does NOT store triage decisions (yet).
9. **Two HTML reports exist with different localStorage keys** — `photo_browse_removals` (browse page) and `photo_triage_decisions` (review-issues page). They don't share state.
10. **The user prefers JavaScript, not TypeScript.** Node.js with ES6 modules for scripts. JSDocs for documentation. No Jest.

---

## Suggested Organizational Tools Not Currently Present

| Tool | Purpose | Complexity |
|------|---------|------------|
| `compare_exports.py` | Given two directory trees (e.g., old Google export + current organized), find files present in one but missing from the other, with resolution comparison | Medium |
| `tag_favorites.py` | Interactive CLI to add XMP:Subject tags to selected photos (could work from the "keep" decisions list) | Medium |
| `import_decisions.py` | Read an exported JSON decisions file and write `decision: keep` or `decision: remove` into the per-directory analysis cache | Small |
| `audit_cache_health.py` | Walk all `.analysis_cache.json` files, report stale entries (files that no longer exist at cached path), orphaned caches, and coverage gaps | Small |
| `verify_decisions.py` | Read localStorage export JSON + check which files still exist → report "stale" decisions for deleted/moved files | Small |

---

## Changelog

### 2026-04-30:

- Full codebase analysis performed (no code changes to organized media)
- Identified 4 confirmed bugs (keeper selection, resolution comparison, identical-duplicate miss, shell injection)
- Identified 4 engineering concerns (decision persistence, file size, dual detection systems, no tests)
- Analyzed and prioritized all README TODO items
- Created this NEXT.md as planning document for future sessions

### 2026-05-17 (this session):

- Fixed BUG-1: keeper selection replaced with `_sort_paths_by_keeper_priority()` using EXIF date, review-area penalty, size tiebreakers (`photo_triage.py`)
- Fixed BUG-2: resolution comparison added — `get_dimensions`/`set_dimensions` in `AnalysisCache`, `get_image_dimensions()` helper, batch EXIF call extended to fetch dimensions, HTML cards now show resolution (`analyze_photo_quality.py`, `photo_triage.py`)
- BUG-3 diagnosed: cross-year duplicate miss caused by scanning sub-directory instead of full `Organized_Photos/` root — no code change, README note added, but worth checking up on after another batch run
- Fixed BUG-4: shell script injection — single-quoted paths + `'\''` escaping in both export functions (`photo_triage.py`)
- DSCN/Nikon: confirmed no code change needed — existing DCIM folder guard and EXIF fallback handle it
- **Wire `auto-triage` as a CLI subcommand** ✅ done — `python3 photo_triage.py auto-triage [dir] [--dry-run] [--symlinks]`. Scans the full `Organized_Photos/` root (not a subdirectory) to catch cross-year identical duplicates. The `review-issues` HTML path remains the primary workflow; `auto-triage` is for unattended batch moves of high-confidence cases.
- DSLR batch (DSC_) processed via v4 archive workflow
- Generated CHANGELOG.md

---

## Remaining Items for Next Sessions

### Phase B: Workflow Durability (unstarted)

- **Add test coverage** for date extraction, duplicate grouping, keeper selection (especially the new priority chain), and shell script escaping.

### Phase C: Data Consolidation — Next Three Batches

1. **Nikon NAS** (`/Volumes/photosync/NIKON`, DSCN_XXXX.JPG, ~4500 files, two cameras: S3100 + S3500):
   - Run `apply_date_from_neighbor.py` first to stamp the 39 NO_EXIF files with mtime (use `--date YYYYMMDD` to override if the neighbor date is wrong)
   - Then ingest via `workflow_archive.py` — model suffixes are auto-detected from EXIF per file; `--person-suffix` is not needed for this batch (no per-owner split)
   - Command: `python3 workflow_archive.py TO_PROCESS/NIKON --dry-run` then without `--dry-run`
2. **High-quality Google Photo export**: requires BUG-2 fix (now done). Run `compare_exports.py` (tool not yet built) to identify files in the old export that differ in resolution from the current organized version. Until that tool exists, process the export through `workflow_takeout.py` normally and let the HTML review surface the resolution differences.
3. **PhotoSync NAS data**: mount NAS, run `check_nas_archive.py` to understand scope, then process with `workflow_archive.py`. No code changes anticipated unless NAS paths use UNC (`//server/share/`) format, which `Path` handles correctly on macOS.

### Phase D: Engineering Concerns (deferred)

- CONCERN-1: add `decision` field to `.analysis_cache.json` or parallel `.triage_decisions.json`. Blocked on agreeing on the storage model.
- CONCERN-2: `photo_triage.py` is now ~4600 lines — consider extracting HTML generation
- CONCERN-3: dual duplicate detection systems — acceptable for now, document the distinction
- CONCERN-4: no test infrastructure — high value, medium effort; prioritize before next major refactor
