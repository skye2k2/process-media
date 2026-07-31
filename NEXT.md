# NEXT.md — Analysis, Priorities, and Planned Work

> Generated on 2026-04-30 from analysis of the full codebase, `_CONVERSATION.md` session history, and README TODO list.
> This file is the "trail of breadcrumbs" for the next session after this conversation compacts out of memory.
>
> **⚠️ READ THE `2026-07-30 (state audit after a three-month gap)` SECTION IN THE CHANGELOG BELOW FIRST.** Several statements in the sections above — the "Current state" summary, CONCERN-4 (tests), and every `/Volumes/photosync` path — were accurate when written but are now stale. The audit section supersedes them.

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

### 2026-07-30 (state audit after a three-month gap):

Corrections to the statements above — several were accurate when written but are now stale. Trust this section over the older ones where they conflict.

- **Tests DO exist.** CONCERN-4 ("no test infrastructure") is resolved: `test_core.py` has 75 passing tests. It had simply never been committed to git until now. Same for `workflow_review.py`.
- **Event folders have ALREADY been executed** across the whole archive on 2026-03-13 (see `_Timeline/2026-03-13 create-event-directories.txt`). 107 `MM-DD Event` folders plus named holiday/birthday folders exist on disk, and roughly 10,500 files were relocated. This was never recorded in the CHANGELOG (there is no v7 entry) — hence the confusion.
- **A re-run is pending and safe.** A dry-run on 2026-07-30 finds 1,998 newly-eligible photos in 2013–2018 — these are the May Nikon ingest (`DSCN*_S3100`/`_S3500`) that landed in month folders after the March pass. Holiday/birthday folders merge by name via `mkdir(exist_ok=True)`, so re-running is idempotent for them.
- **Environment had silently broken.** A Homebrew Python 3.14 upgrade orphaned `numpy`/`cv2`, and `photo_triage.py` exits on missing OpenCV, so the entire review workflow was dead. Fixed in v10 via `.venv` + `requirements.txt`. **Always run `.venv/bin/python`, never bare `python3`.**
- **NAS paths in this file are wrong for the current mount.** The share actually mounted is `//truenas/photos` → `/Volumes/photos`, and it is **not a source** — it is a stale mirror of `Organized_Photos/` from 2026-01-30. The documented source paths (`/Volumes/photosync/NIKON`, `/Volumes/photosync/Photo Uploads`, `/Volumes/photosync/2021GooglePhotoArchive`) were not mounted at audit time; mount that share before Phase C.

#### The NAS copy is a cold backup, not a sync target

**Clarified by the user on 2026-07-30:** `/Volumes/photos` is a deliberate one-time hard backup of the initial data merge, taken *before* the review/prune/sort/import work began. It was never actively synced and was never intended to be. Real sync management was deferred until the pipeline stabilized, with `rsync`/`restic`-style tooling as the intended eventual mechanism. A constraint worth respecting: the NAS runs NVMe drives whose replacement cost has risen sharply, so gratuitous write churn is to be avoided — which is an argument for in-place indexing and against repeated bulk re-copies.

So the numbers below are **not** a warning about an imminent mistake. They are confirmation that the instinct to wait was correct: a naive bidirectional sync at any point in the last six months would have been destructive in both directions.

Measured by basename (relative-path comparison is meaningless now that event folders churned the paths):

| Measure | Count |
|---|---|
| Present in both trees | 27,017 |
| NAS only — a NAS→local pull would **resurrect** these | 3,211 |
| Local only — a destructive mirror would **delete** these | 8,176 |
| Same file at a different relative path (event-folder churn) | 10,490 |

The 3,211 NAS-only files are largely content deliberately pruned in earlier passes (project/tutorial shots, `-edited` variants, `_TO_REVIEW_` leftovers). **Any bidirectional sync resurrects thousands of intentionally deleted files.** When sync is eventually built, it must be one-way local→NAS publish, and the 10,490 moved-but-identical files argue for a content-addressed tool (`restic`) over a path-based one (`rsync`), which would otherwise see the event-folder churn as ~10,500 deletes plus ~10,500 re-uploads and write far more to the NVMe pool than necessary.

---

## Nikon NAS dry-run results (2026-07-30) — nothing left to ingest

Both the read-only reconciler and the real importer were run against `/Volumes/photosync/NIKON` (4,502 files, 12 GB). They agree exactly:

| Verdict | Count | Share |
|---|---|---|
| Byte-identical, already archived | 4,491 | 99.76% |
| Reported as new content | 11 | 0.24% |
| Date+size match, dest clash, no-EXIF, read errors | 0 | — |

**All 11 "new" files are the `.AVI` clips, and all 11 are already archived** as H.265 transcodes in `Organized_Videos/` under the v8 naming convention (e.g. `DSCN3019.AVI` → `2013/10 October/20131004_161529_DSCN3019_S3100.h265.mp4`). Verified by stem search across `Organized_Videos/`.

**True duplication is therefore 4,502 / 4,502 — 100%.** The May ingest was complete; the Nikon NAS archive needs nothing. This lands well inside the ">90%" band rather than the ambiguous middle, so there is no evidence here of content stranded on the missing SD card.

### Confidence levels behind that "100%", for deletion purposes

The figure covers two different standards of proof, and they are not equal:

- **4,491 JPGs (99.76%) — byte-identical, confirmed.** MD5-matched by two independent code paths, plus 40 randomly sampled pairs verified with `cmp` (byte-for-byte, no hashing involved, entirely outside this project's code). 40/40 identical.
- **11 AVIs (0.24%) — NOT byte-identical.** They exist locally only as *lossy* H.265 transcodes. What was verified is that all 11 match their archived counterpart on duration to the millisecond and on resolution exactly (1280×720). That is strong evidence of correspondence, but the original camera AVI files exist nowhere else locally.

Full census of the NAS directory: 4,491 JPG + 11 AVI + 1 `.DS_Store` = 4,503 files, no nested subdirectories, no other extensions. Nothing was skipped.

**Caveats worth weighing before deleting the NAS copy:**

1. The 11 original AVIs would survive only on the SD card. Their *content* survives locally as H.265, but a lossy re-encode is not the original.
2. The NAS directory spans **both** cameras — 3,972 `_S3500` and 530 `_S3100`. If the surviving SD card is from only one of the two, deleting the NAS copy leaves the other camera's files with just one copy.
3. The local archive has not yet been transferred to the NAS, and is still being actively pruned during review. Until that transfer happens, deleting the NAS copy makes the local drive the primary for this content.
4. A full byte-for-byte `cmp` over all 4,491 pairs (rather than a 40-pair sample) is available for roughly 12 GB of reads if certainty matters more than the ~10 minutes.

This also validated the v12 BUG-6 fix end-to-end on real data: all 4,491 skips came through the new content-hash path, each logged as `Byte-identical to <name> (no date in filename)`. Before v12 every one of those 4,491 files would have been re-imported with a `_1` suffix.

### BUG-7: `reconcile_nikon_archive.py` is blind to videos

Two defects, one root cause — it only ever compares against `Organized_Photos`:

1. **Every video is misreported as `NEW_CONTENT`.** In this run that was 11 of 11 reported-new files: a 100% false-positive rate on the tool's only actionable output.
2. **The destination it computes for videos is wrong.** It reported the AVIs would land in `Organized_Photos/2013/10 October/`, but `organize_archive.py` routes videos to `Organized_Videos/`.

Note that simply also indexing `Organized_Videos/` would not fix (1): the archived copies are *transcoded*, so no MD5 can match the source AVI. Detection needs stem-aware matching that understands the `YYYYMMDD_HHMMSS_<stem>.h265.mp4` convention — the archived name still contains the original stem.

**Consequence if not fixed:** a live ingest would add 11 redundant original AVIs beside their existing transcodes, which the next reprocess pass would likely re-transcode into `_1` collisions.

### CONCERN-6: reconcile re-hashes the whole archive, ignoring the cache

`build_archive_md5_index()` hashes all 35,152 archived files from cold on every run — 155.5 s here — using its own private `compute_md5()`. It ignores the 46,475 MD5s already sitting in `.analysis_cache.json`, which `duplicate_detector._get_cached_md5()` now reuses. Two copies of the same hashing logic, one of them cache-blind.

---

## CONCERN-7: PhotoSync originals are same-resolution but 2–8× larger (2026-07-30)

Confirmed with measurement. Sampling 300 date-stamped photos from `/Volumes/photosync/Photo Uploads`:

| Importer verdict | Count | Share |
|---|---|---|
| SKIP — recognized as duplicate | 276 | 92.0% |
| IMPORT — no same-date sibling archived | 14 | 4.7% |
| IMPORT — same-date sibling archived anyway | 10 | 3.3% |

For **all 10** of that last group, pixel dimensions are **identical** (every pair 4032×3024) while the PhotoSync file is **2.06× to 8.00× larger** in bytes. Zero pairs differed in dimensions.

**Why they slip through.** `find_duplicate()` matches the filename date pattern, then for a photo only accepts the match if sizes agree within `size_tolerance` (20%). A 2–8× ratio blows past that, no branch claims the file, the candidate loop falls through, and the result is `LOW` confidence / not-a-duplicate — so it gets imported *alongside* the copy already archived. The quality-comparison logic in `compare_quality()` exists but is only reachable from the **video** branch; photos never consult it.

**Why this is the uncomfortable case.** The archive currently holds the *smaller* copy — the Google-recompressed version. Same dimensions at one-eighth the bytes is aggressive recompression, so the PhotoSync original is plausibly the better image. But bigger is not automatically better: re-saving an already-compressed JPEG at high quality inflates bytes without restoring information, which is exactly the "structurally similar but potentially lower quality" trap. **Size and dimensions alone cannot settle which copy is better** — that needs a perceptual comparison, and the project already has the ingredients (`calculate_blur_score`, `calculate_edge_density`, `calculate_image_ssim`).

**Do not let this batch run through `workflow_archive.py` as-is.** At the observed rate, roughly 3% of 8,800 files (~260 photos) would be silently duplicated at 2–8× the storage, and the pair would then need manual reconciliation during review.

### Measured: the larger originals really are better

Eight landscape pairs at 4032×3024 were analyzed with SSIM, Canny edge density, and a JPEG blockiness ratio (mean gradient across 8×8 block boundaries divided by mean gradient within blocks — values above 1.0 mean the compression grid is becoming visible, which is an artifact rather than content).

| ratio | SSIM | edge density (orig → archived) | blockiness (orig → archived) |
|---|---|---|---|
| 3.44 | 0.9533 | 0.0229 → 0.0229 | 1.113 → 1.398 |
| 3.65 | 0.9579 | 0.0303 → 0.0302 | 1.118 → 1.417 |
| 6.17 | 0.9429 | 0.0175 → 0.0168 | 1.135 → 1.915 |
| 6.31 | 0.9345 | 0.0148 → 0.0144 | 1.173 → 2.130 |
| 7.02 | 0.9421 | 0.0174 → 0.0163 | 1.144 → 2.073 |
| 7.34 | 0.9339 | 0.0134 → 0.0127 | 1.194 → 2.761 |
| 7.37 | 0.9345 | 0.0137 → 0.0131 | 1.188 → 2.689 |
| 8.08 | 0.9584 | 0.0070 → 0.0068 | 1.217 → 2.255 |

Conclusions:

1. **Blockiness is higher in the archived copy in all 8 pairs, and scales with the compression ratio** — from 1.4 at ~3.5× up to 2.8 at ~7.3×, against a tight 1.11–1.22 for the originals. The archived copies carry visible block artifacts; the originals do not.
2. **SSIM sits at 0.934–0.958**, not the >0.99 that would indicate a visually lossless re-encode. The change is real and measurable.
3. **Edge density is equal or slightly lower in the archived copy**, so genuine high-frequency detail was discarded rather than merely re-packed.
4. An amplified difference map concentrates entirely on edges and texture — fabric, hair, brick, court lines — with flat regions showing almost no difference. That is the signature of discarded high-frequency detail.

**Why it is hard to see on screen.** The extreme ratios occur on the *least* detailed images: smooth walls, floors, and sky compress 7–8×, while a busy frame only compresses ~3.5×. So the biggest byte savings happen where there is least detail to lose. Viewing a 4032-pixel-wide frame scaled to fit a monitor also averages away precisely the high-frequency loss being measured. The difference shows up at 100% zoom on texture, and when printing large.

**Ruling implication.** The previously recorded rule — "high SSIM, same resolution, different filesize → the smaller should probably win" — was premised on SSIM being high enough that the two are interchangeable. At 0.93–0.96 with blockiness approaching 2.8 that premise does not hold, so for same-dimension pairs the **larger, less-compressed original should win**, with blockiness (not filesize) as the quality signal. Storage cost is minor: even at a few thousand files, the delta is a couple of GB.

### Calibration ladder (2026-07-30) — what the thresholds actually mean

A single well-lit, highly detailed outdoor photo (`IMG_20210627_201026804_HDR.jpg`, 4032×3024, edge density 0.0614 — kids at a pool with foliage, mountain rock, fence-slat shadows, water ripples, and fine twigs) was re-encoded across 18 JPEG quality levels and measured against itself.

| quality | size vs orig | SSIM | edge density Δ | blockiness |
|---|---|---|---|---|
| 98 | 1.06× | 0.9991 | −0.4% | 1.076 |
| 95 | 0.83× | 0.9993 | −0.4% | 1.073 |
| 92 | 0.68× | 0.9933 | +0.3% | 1.067 |
| 90 | 0.61× | 0.9890 | +0.3% | 1.103 |
| 87 | 0.48× | 0.9857 | −1.0% | 1.201 |
| 85 | 0.44× | 0.9842 | −0.7% | 1.204 |
| 82 | 0.40× | 0.9815 | −0.3% | 1.208 |
| 80 | 0.37× | 0.9797 | −0.2% | 1.229 |
| 75 | 0.32× | 0.9764 | −0.7% | 1.293 |
| 70 | 0.29× | 0.9735 | −0.4% | 1.327 |
| 65 | 0.26× | 0.9708 | −0.5% | 1.375 |
| 60 | 0.24× | 0.9680 | −0.2% | 1.407 |
| 55 | 0.23× | 0.9657 | −0.2% | 1.451 |
| 50 | 0.21× | 0.9633 | −0.1% | 1.478 |
| 45 | 0.20× | 0.9607 | +0.1% | 1.522 |
| 40 | 0.19× | 0.9574 | +0.2% | 1.572 |
| 35 | 0.18× | 0.9539 | +0.3% | 1.622 |
| 30 | 0.16× | 0.9487 | +0.4% | 1.699 |

Four conclusions that bear directly on the keeper policy:

1. **An SSIM floor of 0.91 sits below the entire ladder.** Even quality 30 — more aggressive than anything observed in the archive — only reaches 0.9487. A rule of "smaller wins unless SSIM < 0.91" is therefore operationally identical to "smaller always wins." That is a legitimate decision, but it is a decision rather than a discriminating test.
2. **The observed Google copies (SSIM 0.934–0.958) map to roughly quality 30–40 on this ladder.** Google's recompression was aggressive, and it is still hard to see — which is a real finding about human vision, not a failure of inspection.
3. **Edge density is useless as a threshold.** It moves by at most 1.0% across the whole ladder and not even monotonically. Drop it as a criterion.
4. **Blockiness is the only well-behaved metric** — monotonic from 1.07 to 1.70 as quality falls. If any automatic guardrail is wanted, this is the one to use. Note it is image-dependent: the busy pool photo tops out at 1.70, while a flat indoor gym frame reached 2.76 at a similar ratio, because a busy image dilutes the boundary-to-interior ratio.

**A third option, not previously considered:** rather than choosing between the two existing files, re-encode the original at quality 85–90 for 0.44–0.61× the size at SSIM 0.984–0.989. That captures most of Google's space saving with a fraction of the damage — Google's own copy is ~0.25× at SSIM ~0.95. Costs: one extra generation of loss, and it rewrites files.

If a threshold that actually binds is wanted instead of "always smaller", it needs to sit near **0.95–0.96**: a 0.95 floor would preserve the larger original in roughly half the observed cases, a 0.94 floor in one or two.

Ladder crops are exported to `.TMP_calibration/ladder/` as lossless PNG, named with their SSIM, in both a busy and a smooth window. At 300 dpi this image prints 13.4 × 10.1 inches, so viewing a crop at 100% approximates a section of a 13-inch print rather than an unrealistic pixel-peep.

### Incidental findings from building the ladder

- **`~N` Takeout variants are probably deliberate crops, not thumbnails.** 89 archived files carry a `~N` marker; of 57 groups holding a `~N` plus a plain sibling, 45 have the `~N` copy at *lower* resolution. Their aspect ratios frequently differ from the sibling (1441×2066 portrait against 4032×3024 landscape, 3538×2128 wide, 3024×3615 portrait), which points to intentional cropping in Google Photos. **Do not prune these.** Usefully, this also supplies the crop-detection signal previously assumed unavailable: a changed aspect ratio between two otherwise-matching images indicates a crop, even though a same-aspect-ratio crop remains undetectable.
- **`find_duplicate()` picks an arbitrary sibling.** When several archived files share one timestamp, candidates are examined in index order, so which one a source is compared against depends on index ordering. In this case a full-resolution original and a `~2` crop shared a timestamp and the crop came first. Minor, but it makes some verdicts order-dependent.
- For the calibration photo, the full-resolution original is **already archived** at 4,356,523 bytes against the PhotoSync original's 4,356,524 — a one-byte difference. Some PhotoSync files are already present at full quality, reinforcing that prevalence needs proper measurement.

### RULING SUPERSEDED (2026-07-30, later the same day): floor lowered to 0.92

After reviewing the full 25-pair set including `pair01` at SSIM **0.9282** — the worst real recompression found anywhere in the data — the user reported still being unable to care about the difference. The 0.96 figure below was a first pass; the operative rule is now:

- **SSIM ≥ 0.92** → keep the smaller (archived) copy.
- **SSIM < 0.92** → keep the larger original.

**In practice this means the smaller copy wins for every same-dimension pair observed to date**, since the worst measured case is 0.9282. The floor's job has changed accordingly: it is no longer a discriminator between normal recompressions but a **safety net for pathological cases** that have not yet appeared — a genuinely mangled file, or an extreme same-dimension re-encode in the 2021 Google archive that has not been examined yet.

Two things worth keeping in mind about this floor:

1. **Resolution, not SSIM, is the real thumbnail guard.** A downscaled copy has different dimensions, so it never reaches the SSIM test at all — it is handled by the pixel-count comparison in `_sort_paths_by_keeper_priority()`. The SSIM floor only governs same-dimension pathologies, which is a much narrower risk.
2. **Content-aware refinement, if it ever seems worth it.** The user's own observation is the key: both hard cases (`pair01`, and the earlier gym shot) were *blurry indoor photos*, where there is little fine detail for compression to destroy and therefore little to see. A sharp, detailed photo would justify a stricter floor than a soft one. The project already computes a blur score per file, so the floor could scale with it — stricter for sharp images, looser for soft ones. Not needed now, but it is the principled version of this rule.

### Earlier first-pass ruling (kept for the reasoning): 0.96

Calibrated by the user against the ladder crops: artifact differences become *visible* around SSIM 0.965, and become *objectionable* below 0.96. So the keeper rule for same-dimension pairs is:

- **SSIM ≥ 0.96** → keep the smaller (archived) copy. Space wins; the difference is not objectionable.
- **SSIM < 0.96** → keep the larger original.

Edge density is explicitly **not** a criterion (it moves ≤1% across the entire quality ladder). Blockiness is informative but image-dependent, so it is a diagnostic rather than a gate.

On the 25-pair review set (worst-SSIM-first, range 0.9282–0.9722), this rule keeps the original for **19 of 25**. Note the consequence: every one of the high-ratio Google recompressions measured so far falls below 0.96, so in practice this rule preserves the original for essentially all of the *badly* recompressed pairs while still discarding the originals of mildly recompressed ones.

### Prevalence: ~3.4%, and the earlier doubt was my own bug

**Measured:** 40 same-dimension pairs at ratio ≥ 1.5 out of 1,180 timestamp matches = **3.38%**. This confirms the original 3.3% estimate.

The earlier worry that prevalence might be far higher — "a separate scan collected 600 pairs at ratio ≥ 2.0 almost immediately" — was an artifact of the sibling-selection bug: that scan compared each source against the *first* archived file sharing its timestamp without verifying dimensions, so it counted crops and resized `~N` variants as though they were same-dimension pairs. With dimension verification the figure is ~3.4%.

Extrapolated to the full 8,800 PhotoSync files: roughly 300 same-dimension pairs, of which about 230 would keep the original under the 0.96 rule. Storage delta is around **700 MB** — negligible.

### Re-encode pass: target is PhotoSync "Photo Uploads" (53 GB), deferred

**Decided (2026-07-30):** the re-encode idea is reserved for the PhotoSync `Photo Uploads` originals rather than the organized archive. That tree is 53 GB and is expected to overlap heavily with what is already archived.

**HOWEVER, comma** — this decision interacts with the 0.92 floor above, and the interaction cuts the scope down sharply. With the floor at 0.92, every same-dimension pair observed keeps the *archived* copy, so the roughly 300 same-dimension pairs no longer get upgraded to PhotoSync originals at all. What is left for a re-encode pass is only PhotoSync's **genuinely new** content — files with no archived counterpart.

From the 300-file probe: 92.0% were recognized as duplicates, 3.3% were same-dimension pairs (now resolved in favour of the archived copy), and **4.7% had no archived sibling at all**. If that holds across the tree, the genuinely-new share of 53 GB is on the order of **2–3 GB**, not 53 GB.

So the honest sequencing is:

1. Import PhotoSync and find out how much is actually new. The content-hash fallback (v12) plus the 0.92 floor will do the deciding.
2. *Then* judge whether a re-encode pass is worth building. At 2–3 GB of new content it almost certainly is not; the six safeguards below cost more than the space they would reclaim.
3. The re-encode pass regains its appeal only if the incoming volume turns out much larger than the probe predicts, or if it is aimed at the full 91 GB archive instead.

### On re-encoding originals: mechanics and required safeguards

The "best of both worlds" option — re-encode the original at quality 85–90 instead of choosing between the two existing files — is sound in principle. Ladder numbers: q90 gives 0.61× the original size at SSIM 0.989, q85 gives 0.44× at SSIM 0.984. Both sit far above the 0.96 comfort threshold.

**But the arithmetic does not justify it for the PhotoSync merge.** Keeping ~230 originals outright costs about 700 MB. Re-encoding them at q90 would save roughly 270 MB of that, in exchange for a lossy rewrite of irreplaceable originals plus all the machinery below. Not worth it at this scale — just keep the originals.

Re-encoding only becomes interesting as a deliberate space-reclamation pass over the whole 91 GB photo archive, where a 0.61× factor could recover something on the order of 35 GB. That is a much higher-stakes project and needs all of the following before it touches a single file:

1. **Metadata preservation.** OpenCV and PIL both discard EXIF/XMP/IPTC/ICC on write. The only robust path is to re-encode, then `exiftool -TagsFromFile <source> -all:all` onto the result, and verify `DateTimeOriginal` survived. Orientation and ICC profile must be checked explicitly.
2. **Sorting stability.** Same filename, same directory, replaced in place. Nothing may change a path, or event folders and any path-keyed review state break.
3. **No file loss.** Encode to a temp file, verify (dimensions equal, SSIM against source above a floor, EXIF date present and matching), and only then atomically replace. Never unlink the source before verification passes.
4. **Filesystem date re-stamping.** Re-encoding resets mtime, which the pipeline stamps to capture date via `stamp_filesystem_dates()`. Must be re-applied.
5. **Cache invalidation is expected.** Changing size and mtime invalidates cached blur, phash, and md5 for that file — correct behaviour, but it forces re-analysis, so plan for a re-cache pass afterward.
6. **Idempotency, or generation loss compounds.** A re-encoded file must never be re-encoded again. The marker has to survive file moves, since event folders relocate files, so it must be **embedded in the file** (a dedicated XMP tag) rather than kept in a path-keyed index.

---

## Strategic direction under evaluation: Immich (raised 2026-07-30)

A friend recommended [Immich](https://immich.app/) — self-hosted, open-source, AGPL — with the idea of rebuilding this project's features inside it and upstreaming them. Researched on 2026-07-30; findings below.

### What Immich would replace outright

- **Decision persistence (CONCERN-1) dissolves.** Postgres-backed state instead of browser `localStorage`. This is the single largest pain point in the current design.
- **Review UX.** Real web app with mobile clients, instead of a 41 MB static HTML file.
- **Tags / people / favorites.** Face recognition, tags, and CLIP-based semantic search ship today. This closes the "add tags for best-ofs, people and events" TODO without writing any of it.
- **Continuous ingest.** Mobile background backup means new photos arrive incrementally — this is the actual answer to "never do a full Takeout again."
- **In-place indexing.** External libraries index files where they sit, with no copy and no move. Directly serves the no-bulk-transfer and low-NVMe-churn goals.

### What Immich does NOT do — the genuinely novel work here

- **Blur / quality triage does not exist.** No consolidated feature request either; every "blur" issue in their tracker is about *applying* blur for privacy or progressive loading, not detecting it as a quality signal. This is the most defensible original contribution in this repo.
- **Over-captured-day detection** (`EVENT_CLUSTER_THRESHOLD`) has no equivalent.
- **Duplicate keeper selection is far weaker.** Immich preselects the copy to keep by **file size in bytes alone**. `_sort_paths_by_keeper_priority()` uses EXIF date, review-area penalty, pixel count for perceptually-similar groups, size, then filename length. The community is actively asking for better rules (Immich discussions #10665 "Duplicate Rules", #25831 "Deduplication workflow could be so much better").
- **Date repair** from filename patterns and neighbor inference (`apply_date_from_neighbor.py`) has no equivalent.
- **Space-reclaiming transcode.** Immich transcodes for playback but preserves originals by design — philosophically opposed to the goal of replacing legacy originals with H.265 to reclaim space. This part of the toolkit will not upstream.

### The hard architectural conflict — read before committing to anything

External libraries treat a **moved file as a brand-new asset**, discarding Immich-side metadata on rescan: *"If you move an asset to another location within the library all such metadata will be lost upon rescan."* This pipeline moves files constantly — the March event-folder pass alone relocated ~10,500 of them.

Therefore "the Python toolkit keeps reorganizing the tree" and "Immich holds durable metadata about those files" are **mutually exclusive at the same point in time**. Worse, **(External) libraries are currently under an upstream feature freeze** (only minor bug fixes accepted), so this cannot be fixed by contributing.

Also note the storage-template engine (the `{{y}}/{{MM}}` folder layout feature) applies **only to uploaded assets, not external libraries** — so choosing external-library mode means the filesystem layout stays this project's responsibility, permanently.

### Recommended sequencing

Treat the two as complementary rather than competing, with a one-way handoff:

1. **Python toolkit = pre-processing.** Ingest, date repair, dedupe, prune, normalize, organize, event folders. All destructive and all path-churning work happens here.
2. **Freeze the tree.** Finish the ~17,000-photo review backlog and the Phase C imports *first*, because every move invalidates Immich metadata.
3. **Immich = post-processing.** Browse, review, faces, semantic search, sharing.

The current work is not wasted: `immich upload --album` derives album names from folder names, so the event folders created in March convert directly into an Immich album taxonomy.

### Upstream contribution strategy

Immich requires prior discussion for large PRs (`#contributing` on Discord) and explicitly notes they "hate to throw away work." Ranked by likelihood of acceptance:

1. **Resolution-aware duplicate keeper preselection** — small, well-scoped, community-requested, replaces a naive size-only heuristic. Best first PR.
2. **Blur/quality scoring** as an asset attribute plus a "low quality" filter — larger, novel, needs design buy-in first. Plausibly lands in the Python ML service, where the existing OpenCV Laplacian-variance approach ports reasonably well.
3. **Do NOT start with anything touching external libraries** — frozen.

**Honest friction to weigh:** the Immich server is TypeScript/NestJS. Per the stated language preference in this repo, TypeScript is unfamiliar territory. The Python ML service is the friendlier landing zone, which conveniently is also where the blur work belongs.

---

#### BUG-5: cluster detection ignored existing event folders — ✅ FIXED in v11

`_detect_photo_clusters()` evaluated the ≥35-photos-per-day threshold against *loose direct-child files only*, never considering that a day might already own an `MM-DD Event` folder from a previous run.

Fixed with a two-pass design (adoption, then discovery) plus a new `map_days_to_cluster_folders()` helper. 19 tests added (Section 8; suite 75 → 94). See CHANGELOG v11 for the full write-up.

**Worth remembering — the audit that under-reported.** The initial estimate of this bug's severity was "1 stranded file, low impact," measured by a throwaway script that counted loose files per day using *filename dates only*. That was wrong in two ways, and the pattern is worth avoiding next time:

1. It missed files whose date comes from EXIF or the analysis cache rather than the filename — precisely the Nikon `DSCN*` batch, which is the whole reason there was a backlog. Real count of stranded files: 36, not 1.
2. It only looked for loose counts *below* threshold, reasoning that above-threshold days were fine. They were not: an above-threshold day covered by an existing **span** folder creates a competing sibling folder. This was the worst instance in the archive — 102 photos would have landed in a new `2016/07 July/07-19 Event` beside the existing `07-18–07-19 Event`, splitting one event in two — and the audit rated it benign.

Lesson: when auditing a function's behavior, drive it through the function's own date-resolution path rather than reimplementing a simplified version of it.

#### Not bugs — checked and cleared

- Cluster folders intentionally omit the year prefix (documented at README "Create Event Folders"); the year is implicit in the containing directory.
- The sidecar rename in `_move_file()` uses `sidecar.name[len(file_path.name):]`, which is safe: `get_metadata_path()` only returns names anchored to the exact media filename, so the slice can never yield an empty suffix and overwrite the photo.
- `build_file_index()` uses `rglob`, so files inside event subfolders remain visible to import-time duplicate detection. Event folders do not hide files from the dedupe index.

#### CONCERN-5 was wrong, and investigating it uncovered BUG-6 — ✅ RESOLVED in v12

**The original claim was mistaken.** CONCERN-5 described `organize_archive.find_existing_by_date()` as an O(index) scan on the hot import path. That function had **no call sites**. The live path is `DuplicateDetector.find_duplicate()`, which was already O(1)-indexed by date pattern and already iterated every candidate. The "billion substring comparisons" estimate described dead code.

**What the investigation found instead — BUG-6, far more serious.** `find_duplicate()` returned `is_duplicate=False` immediately whenever the source filename lacked a `YYYYMMDD_HHMMSS` stamp, never consulting the index. That is **26.1% of the archive — 9,753 of 37,300 files**: every Nikon `DSCN*`, DSLR `DSC_*`, old `IMG_####`, and scanned image. Re-ingesting the Nikon card would have imported all ~5,000 photos a second time, with `move_file()` appending `_1` and logging it as a resolved collision.

Fixed in v12 with a size-narrowed content-hash fallback. Verified: 250/250 already-archived EXIF-only photos detected, no misses, 5.8 ms/file, ~167 s projected for the full 28,800-file backlog. See CHANGELOG v12.

**Why this hid for so long, and the lesson.** Eight tests asserted the behavior of the dead function, under a docstring claiming it covered "the primary deduplication mechanism for DSCN and other EXIF-only files." The suite therefore *looked* like it covered EXIF-only dedupe. Dead code with live tests is worse than no tests: it manufactures confidence in a path that never executes. Those tests are deleted; Section 9 covers the real path.

Two audits in a row now (BUG-5, BUG-6) have been misjudged by reasoning about code rather than executing it. Both times, running the real function against the real archive gave a different and worse answer than reading it did. **Default to executing the suspect path against live data before rating a bug's severity.**

#### CONCERN-1 has graduated to top priority

Decision persistence was previously ruled "skip, for now." That ruling should be revisited: the March event-folder pass moved ~10,500 files, which orphans any path-keyed `localStorage` decision, and ~17,000 photos remain to review. Key decisions to content hash rather than path so they survive both event-folder moves and future imports. Confirmed with the user on 2026-07-30 that no unexported decisions were live at audit time, so there is a clean slate to build on — but the next review pass will accumulate state that must survive.

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
