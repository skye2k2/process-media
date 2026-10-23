# Family-History Import and External Backup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import the family takeout so scans file by depicted era (never by scan date), establish the Clifford Bergmann person-tag convention, and stand up a verified external-drive backup that unblocks deleting the 158 GB Desktop duplicate.

**Architecture:** A pre-classification router (`route_family_scans.py` + pure `family_scan_classifier.py`) moves circa/unknown scans to their destinations *before* `workflow_takeout.py` runs, because `organize_media.py`'s date priority (filename → JSON → EXIF) would otherwise file every scan by its 2013–2014 scan date. Backup and reconciliation are two standalone tools (`backup_archive.py`, `reconcile_quicksave.py`) with pure, unit-tested decision functions and operational run steps.

**Tech Stack:** Python 3.14 (`.venv/bin/python`), `unittest` (new modules `test_family_import.py`, `test_backup_tools.py`, run standalone like `test_core.py`), exiftool batch via argfiles, rsync, `hashlib.md5`. No new pip dependencies.

**Spec:** `docs/superpowers/specs/2026-10-21-family-history-import-and-backup-design.md`

## Global Constraints

- Every script invocation uses `.venv/bin/python`, never bare `python3` (AGENTS.md).
- Bulk-output runs redirect to a log: `> .TMP_<name>.log 2>&1`.
- `workflow_takeout.py` runs with the person prompt left EMPTY — this import uses no `--person` suffix and never writes `Artist` (spec §2).
- Person tag value is exactly `Clifford Bergmann`; estimated-date marker keyword is exactly `date-estimated`.
- Tag fields, always together: `-XMP-iptcExt:PersonInImage+=`, `-XMP-dc:Subject+=`, `-IPTC:Keywords+=`.
- Circa destination folder is literally `00 Circa` under the year (matches `MONTH_NAMES` "NN Name" format); holding root is `Organized_Photos/_FAMILY_HISTORY_/<batch>/`.
- Scan-era boundary is 2013: a JSON `photoTakenTime` year < 2013 is a real (backdated) date; filename-year extraction accepts 1900–2012 only.
- Destructive operations (drive erase, Desktop-copy deletion) execute only at their own plan step, after their stated gate; deletion additionally requires the owner's in-session approval at execution time.
- Git commits end with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Keep `README.md`/`CHANGELOG.md` current with functional changes (Task 11 owns the sweep).

## Review Focus

1. **Pre-1970 sidecar timestamps** (1963 albums have negative epoch values): classifier must return year 1963, not crash or misclassify — test in Task 7.
2. **Media with no sidecar** in a standard folder: classifier receives `taken_year=None` and must still route safely (defaults toward holding, never a fabricated year) — test in Task 7.
3. **Identical unknown scans duplicated across Takeout parts**: router must content-hash-dedupe into the holding folder, not write `_1` copies of identical bytes — test in Task 8.
4. **exiftool failures on extension-mismatched scans** (WebP saved as `.jpg` is a known repo quirk): the tag pass must collect and report per-file failures and exit nonzero, never silently skip — test in Task 8, live check in Task 9.
5. **A reconcile/verify check that cannot fail is not a check**: both the backup manifest comparison (Task 3) and the quick-save reconciliation (Task 5) get planted-defect tests, and the live runs (Tasks 4, 6) each plant one known-positive before trusting a clean result.

---

### Task 1: Rescue the removal records and screenshots from the Desktop copy

**Files:**
- Create: `_records/removal-scripts/` (three `remove_photos.sh` + the quick-save `README.md`, renamed `quicksave-README.md`)
- Create: `_Timeline/` entries for the rescued PNGs

**Interfaces:**
- Produces: `_records/removal-scripts/*.sh` — Task 5's `RemovalHistory.from_directory()` second source.

- [ ] **Step 1: Copy the removal scripts and README**

```bash
mkdir -p _records/removal-scripts
QS="/Users/skye2k2/Desktop/Active Projects/PERSONAL/process-media/2025-12 google-photo-original-takeout/_Quick Save of Processed Files"
cp "$QS"/*remove_photos.sh _records/removal-scripts/
cp "$QS/README.md" _records/removal-scripts/quicksave-README.md
```

- [ ] **Step 2: Copy every PNG from both the quick-save root and the takeout root into `_Timeline/`, renaming each to lead with its ISO date** (e.g. `Screenshot 2026-02-06 at 13.07.31.png` → `2026-02-06 takeout-processing-130731.png`; the already-dated ones keep their names)

- [ ] **Step 3: Verify the rescue is complete**

Run: `find "$QS/.." -maxdepth 2 \( -name "*.png" -o -name "*.sh" -o -name "README.md" \) | wc -l` and compare against the rescued file count in `_records/removal-scripts/` + new `_Timeline/` entries.
Expected: every source file has a rescued counterpart (list both sides if counts differ).

- [ ] **Step 4: Commit**

```bash
git add _records/removal-scripts _Timeline
git commit -m "Rescue removal scripts and timeline screenshots from the Desktop quick-save"
```

---

### Task 2: Reformat the external drive and run the snapshot feasibility test

**Files:** none (operational; result recorded in Task 11's NEXT.md update)

**Interfaces:**
- Produces: mounted `/Volumes/MEDIA_BACKUP` (APFS) and a recorded versioning decision (`apfs-snapshot` or `link-dest`) that Task 3 implements.

- [ ] **Step 1: Re-identify the drive** (device IDs shift across replugs)

Run: `diskutil list external`
Expected: one 4 TB external disk whose data partition is named `BACKUP` and holds ~27 MB. If anything else appears, STOP and surface it — do not erase a drive that doesn't match.

- [ ] **Step 2: Erase to APFS** (gate: Step 1 matched; this is the spec-sanctioned destructive step)

Run: `diskutil eraseDisk APFS MEDIA_BACKUP GPT disk4` (substitute the verified identifier)
Expected: exit 0; `/Volumes/MEDIA_BACKUP` mounted, APFS, ~4 TB free. Unencrypted APFS and default block size are owner/spec decisions — do not add encryption.

- [ ] **Step 3: Snapshot feasibility test**

Run: `tmutil localsnapshot && diskutil apfs listSnapshots /Volumes/MEDIA_BACKUP`
Expected: either a snapshot listed for this volume (decision: `apfs-snapshot`) or none/error (decision: `link-dest`). Clean up any test snapshot (`tmutil deletelocalsnapshots <date>`). Record the decision for Task 3 and Task 11.

---

### Task 3: `backup_archive.py` — sync, versioning, and manifest verification

**Files:**
- Create: `backup_archive.py`
- Test: `test_backup_tools.py`

**Interfaces:**
- Produces: `build_manifest(root: Path, exclude: set[str]) -> dict[str, tuple[int, str]]` (relpath → (size, md5 hex)); `compare_manifests(src: dict, dst: dict) -> ManifestDiff` (dataclass: `missing: list[str]`, `extra: list[str]`, `mismatched: list[str]`, `ok` property = all three empty); CLI `backup_archive.py {sync,verify} [--dest /Volumes/MEDIA_BACKUP] [--dry-run]`.
- Consumes: Task 2's versioning decision.

- [ ] **Step 1: Write failing tests in `test_backup_tools.py` (unittest)** — build two temp trees; assert `compare_manifests` reports a planted missing file, a planted size mismatch, a planted content mismatch (same size, different bytes — this is why md5 exists), and `ok` on identical trees; assert `build_manifest` honors excludes (`.venv`, `__pycache__`, `.TMP_*`, `.DS_Store`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python test_backup_tools.py -v` — Expected: FAIL (module not found).

- [ ] **Step 3: Implement `backup_archive.py`**

Module pattern per AGENTS.md; `# eslint` n/a, but include the standard docstring-justified functions. Sync behavior: source is the repo root (`SCRIPT_DIR`), destination `<dest>/process-media/`, excludes as above. Versioning per Task 2's decision — `link-dest`: each sync writes `<dest>/process-media/snapshots/<YYYY-MM-DD-HHMM>/` with `rsync -a --delete --link-dest=<previous>` and repoints a `current` symlink; `apfs-snapshot`: run `tmutil localsnapshot` first, then `rsync -a --delete` into `<dest>/process-media/current/`. Verify mode: `build_manifest` both sides (progress line every 500 files), write the source manifest to `<dest>/manifests/<date>.json`, print the `ManifestDiff`, exit nonzero unless `ok`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python test_backup_tools.py -v` — Expected: PASS, and `.venv/bin/python test_core.py` still passes.

- [ ] **Step 5: Commit** — `git add backup_archive.py test_backup_tools.py && git commit -m "Add backup_archive: versioned external-drive sync with manifest verification"`

---

### Task 4: Initial backup run and full verification

**Files:** none (operational)

- [ ] **Step 1: Dry-run** — `.venv/bin/python backup_archive.py sync --dry-run > .TMP_backup_dryrun.log 2>&1`; inspect the log: file count plausible (~200 GB scope), excludes honored, destination paths correct.
- [ ] **Step 2: Real sync** — same command without `--dry-run`, output to `.TMP_backup_sync.log`. Expected: exit 0. (~200 GB; run in background and monitor the log tail.)
- [ ] **Step 3: Prove verification can fail** — append a byte to one file on the DESTINATION copy, run `backup_archive.py verify`, Expected: nonzero exit naming that file. Restore by re-syncing that one file.
- [ ] **Step 4: Full verify** — `.venv/bin/python backup_archive.py verify > .TMP_backup_verify.log 2>&1`. Expected: exit 0, diff empty, manifest written to the drive. The takeout insurance copy requirement (spec §5 step 6) is satisfied here because `TO_PROCESS/` is inside the synced tree and the import has not run yet.

---

### Task 5: `reconcile_quicksave.py` — prove the quick-save is fully represented

**Files:**
- Create: `reconcile_quicksave.py`
- Test: `test_backup_tools.py` (new test class)

**Interfaces:**
- Consumes: `removal_history.RemovalHistory.from_directory(directory)` and `.was_removed(filename)`; Task 1's `_records/removal-scripts/`.
- Produces: `classify_quicksave_file(relpath: str, size: int, archive_index: dict[str, list[tuple[str, int]]], history: RemovalHistory) -> str` returning `'present' | 'modified' | 'removed' | 'unexplained'`; CLI `reconcile_quicksave.py <quicksave_root> [--deep]` writing `_records/reconcile-quicksave-<date>.txt`.

- [ ] **Step 1: Write failing tests** — `archive_index` maps bare filename → [(relpath, size)]. Assert: name+size match → `present`; name match wrong size → `modified`; no match but `was_removed` true → `removed`; no match, not in history → `unexplained`. Build the history from a temp removal script via `parse_removal_script` so the integration with `normalize_media_name` is exercised, not mocked.
- [ ] **Step 2: Run tests, verify FAIL** — `.venv/bin/python test_backup_tools.py -v`
- [ ] **Step 3: Implement** — index the live `Organized_Photos/` + `Organized_Videos/` by filename; walk the quick-save's two Organized trees; load `RemovalHistory` from BOTH `Organized_Photos/` (default) and `_records/removal-scripts/` and union the names. `--deep` md5-compares each `present` pair and demotes mismatches to `modified`. Report: counts per class and the full `modified`/`unexplained` file lists.
- [ ] **Step 4: Run tests, verify PASS**
- [ ] **Step 5: Commit** — `git commit -m "Add reconcile_quicksave: prove the Desktop copy is represented before deletion"`

---

### Task 6: Reconcile, owner approval, delete the Desktop copy

**Files:** none (operational)

- [ ] **Step 1: Prove the check can fail** — plant a uniquely named dummy JPEG inside the quick-save's `Organized_Photos/`, run the reconcile, Expected: it appears as `unexplained`. Remove the plant.
- [ ] **Step 2: Real run** — `.venv/bin/python reconcile_quicksave.py "<quicksave path>" > .TMP_reconcile.log 2>&1`; commit the `_records/reconcile-quicksave-<date>.txt` report.
- [ ] **Step 3: Owner gate** — present the report (counts + every `modified`/`unexplained` entry) to the owner in-session. HARD STOP: no deletion without their explicit approval of this specific report.
- [ ] **Step 4: Delete** (only after Step 3 approval) — `rm -rf "/Users/skye2k2/Desktop/Active Projects/PERSONAL/process-media/2025-12 google-photo-original-takeout"`; verify with `df -h /System/Volumes/Data` (~158 GB freed) and that the path is gone.

---

### Task 7: `family_scan_classifier.py` — pure classification

**Files:**
- Create: `family_scan_classifier.py`
- Test: `test_family_import.py`

**Interfaces:**
- Consumes: `organize_media.get_date_from_filename(Path) -> datetime | None` (existing).
- Produces: `classify_file(album_name: str, filename: str, taken_year: int | None, camera_model: str | None) -> str` returning `'backdated' | 'circa' | 'unknown' | 'modern'`; `extract_filename_year(filename: str) -> int | None`; `extract_batch_prefix(filename: str) -> str`.

Classification order (pin): (1) `get_date_from_filename` returns a date → `modern` (a real full date; `organize_media` handles it). (2) `taken_year` is not None and < 2013 → `backdated`. (3) `extract_filename_year` hits → `circa`. (4) `camera_model` truthy → `modern`. (5) otherwise → `unknown` (fails safe toward holding).

`extract_filename_year`: leading 4-digit year 1900–2012 followed by `-` or `_` (e.g. `1980-youth-065`, `1990_13`, `1997_8`). `extract_batch_prefix`: strip the extension, then strip a trailing `(?:[-_]?\d+[A-Za-z]?)$` group at most twice, refusing a strip that empties the stem; empty/all-digit stems return `'misc'`. Pinned examples: `cars-045`→`cars`, `family-BB-016`→`family-BB`, `FH000011`→`FH`, `0NBergm-R1-040-18A`→`0NBergm-R1`, `1060605356`→`misc`.

- [ ] **Step 1: Write failing tests** covering: each pinned batch-prefix example; filename-year acceptance (`1980-…`→1980) and rejection (`2013-…`, `20240520_1919…`, bare `1990` with no separator); the 1963 negative-epoch path — convert a real 1963 sidecar timestamp with `datetime.fromtimestamp` in the test to prove the platform handles negatives, then assert `classify_file(…, taken_year=1963, …) == 'backdated'`; `taken_year=None` with no other signal → `'unknown'`; `camera_model='Pixel 6'` with numeric filename → `'modern'`; `IMG_20240520_191937921` → `'modern'` via rule 1.
- [ ] **Step 2: Run, verify FAIL** — `.venv/bin/python test_family_import.py -v`
- [ ] **Step 3: Implement** (the `.TMP_classify_takeout_dates.py` sketch is reference only — its `\b` year regex bug is exactly what Step 1's `1990_13` case pins against).
- [ ] **Step 4: Run, verify PASS** — plus `.venv/bin/python test_core.py` still green.
- [ ] **Step 5: Commit** — `git commit -m "Add family_scan_classifier: route scans by recoverable date, not scan date"`

---

### Task 8: `route_family_scans.py` — the routing layer

**Files:**
- Create: `route_family_scans.py`
- Test: `test_family_import.py` (new test classes)

**Interfaces:**
- Consumes: Task 7's three functions; `media_utils.parse_json_metadata`, `get_metadata_path`, `MEDIA_EXTENSIONS`, `MONTH_NAMES`; `merge_metadata.py` CLI (`<dir> --recursive --remove-json`).
- Produces: CLI `route_family_scans.py --input-dir <takeout root> [--output-root Organized_Photos] [--person "Clifford Bergmann"] [--dry-run]`; `plan_routes(input_dir: Path, output_root: Path) -> list[RouteAction]` where `RouteAction` is a dataclass `(src: Path, sidecar: Path | None, bucket: str, year: int | None, batch: str | None, dst: Path)`; `tag_files(paths: list[Path], person: str, extra_keywords: list[str]) -> list[tuple[Path, str]]` returning failures.

Behavior to pin:

- Scope: only `Google Photos/Photos from \d{4}` album folders under the input dir (all four Takeout parts). Project folders (wedding, `Friends `) and comma-named shared folders are untouched — existing machinery owns them.
- Camera-model lookup: one batched `exiftool -Model -json` pass, only over files rules 1–3 left ambiguous.
- `backdated` → tag in place (person keyword set), leave for `workflow_takeout.py`.
- `circa` → move media+sidecar to `<output-root>/<year>/00 Circa/`; then `merge_metadata.py` on each touched `00 Circa` dir (`--remove-json`); THEN overwrite dates: `-DateTimeOriginal="<year>:01:01 00:00:00"` `-CreateDate=` `-FileCreateDate=` `-FileModifyDate=` same value, plus person tags plus `date-estimated` keyword. Order matters: the merge writes the scan date, the overwrite must come after.
- `unknown` → move media+sidecar to `<output-root>/_FAMILY_HISTORY_/<batch>/`; `merge_metadata.py` each batch dir (`--remove-json`); person tags (no date overwrite — the scan date is factual there).
- `modern` → untouched.
- Dedupe on move: destination name exists → md5 both; equal → delete source + sidecar, count as duplicate; differ → `_1` suffix (match `move_file_safely` convention).
- Tagging: exiftool argfile batches of ≤500; collect per-file failures; nonzero exit listing them (Review Focus 4).
- Report: per-bucket and per-batch counts, duplicates deleted, tag failures; `--dry-run` plans and reports without moving or tagging.
- Idempotent: re-running after a partial run must only act on files still present.

- [ ] **Step 1: Write failing tests** — fixture temp tree with fake Takeout parts (tiny files + real-shape sidecar JSONs): assert `plan_routes` bucket/destination for one file per bucket; duplicate identical bytes across two parts → one `RouteAction` + one duplicate deletion (Review Focus 3); `dry-run` leaves the tree byte-identical; `tag_files` against a text file masquerading as `.jpg` returns it as a failure (Review Focus 4 — exiftool errors on it).
- [ ] **Step 2: Run, verify FAIL**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run, verify PASS** (+ `test_core.py` green)
- [ ] **Step 5: Commit** — `git commit -m "Add route_family_scans: pre-organize routing for scanned family photos"`

---

### Task 9: Live small-subset test (repo convention: 5–10 files first)

**Files:** none (scratch output root; nothing lands in the real archive)

- [ ] **Step 1: Build the subset** — copy into `TO_PROCESS/test/Takeout/Google Photos/Photos from <year>/` (preserving album names): one 1963 file (negative epoch), one 1980 backdated, one `1980-youth-*`, one `1990_*`, one `cars-*`, one `FH*`, one modern `IMG_*`, plus one file with its sidecar deliberately omitted. Include sidecars otherwise.
- [ ] **Step 2: Dry-run** — `route_family_scans.py --input-dir TO_PROCESS/test --output-root .TMP_test_organized --person "Clifford Bergmann" --dry-run`; Expected: report shows each file in its predicted bucket.
- [ ] **Step 3: Live run on the subset**, then verify with exiftool: circa file has `DateTimeOriginal 1980:01:01`, `date-estimated` keyword, person tag in all three fields; unknown file sits in `_FAMILY_HISTORY_/cars/` with person tag and NO date overwrite; backdated file tagged in place; no-sidecar file went to holding (`misc` or its prefix), not a fabricated year.
- [ ] **Step 4: Pre-1990 validator check** — run `organize_media.py --input-dir TO_PROCESS/test` against the remaining (backdated) subset files into the scratch root is NOT possible (output dirs are module constants), so instead verify the two date paths directly: `.venv/bin/python -c` snippets calling `media_utils.parse_json_metadata` on the 1963 sidecar (expect 1963 datetime) and `organize_media.get_exif_date` semantics are unchanged. Expected: 1963 parses; nothing raises. (The full organize path for backdated files is exercised in Task 10 and spot-verified there.)
- [ ] **Step 5: Clean up** — delete `TO_PROCESS/test/` and `.TMP_test_organized/`; verify both gone.

---

### Task 10: Full import run and scatter verification

**Files:** none (operational)

- [ ] **Step 1: Baseline snapshot of the scatter targets** — record file counts of `Organized_Photos/2013/` and `2014/` month folders (`find … | wc -l` per month dir) to `.TMP_scatter_baseline.txt`.
- [ ] **Step 2: Router dry-run on the real takeout** — `--input-dir "TO_PROCESS/thebergmannfamily google takeout" --person "Clifford Bergmann" --dry-run > .TMP_route_dryrun.log 2>&1`; sanity-check bucket counts against the brainstorm classification (~144 backdated / ~600+ circa / ~1,750 unknown before dedupe) — large deviations STOP for investigation.
- [ ] **Step 3: Live routing run** — same command without `--dry-run`, log to `.TMP_route_live.log`; Expected exit 0, zero tag failures (or stop and fix).
- [ ] **Step 4: Run the takeout workflow** — `.venv/bin/python workflow_takeout.py` with person prompt EMPTY (press Enter), log output. Handles the modern files, the wedding project folders, shared folders, JSON cleanup, and the backdated scans the router tagged in place.
- [ ] **Step 5: Scatter verification** — first prove it can fail: plant one `cars-999.jpg` in `Organized_Photos/2014/03 March/`, confirm the check below finds it, remove it. Then: diff month-folder counts against Step 1's baseline and list any new arrivals in 2013/2014 whose names match scanner patterns (`cars-*`, `cards-*`, `family-*`, `FH*`, `*-R1-*`). Expected: none.
- [ ] **Step 6: Destination verification** — backdated files present in their pre-2013 year folders (1963 through 2012, spot-check EXIF dates); `00 Circa` folders exist under the filename-year years; `_FAMILY_HISTORY_/` populated by batch; wedding albums merged under `2023/06 Carina + Charlie - */`; review `_TO_REVIEW_/` contents and surface anything unexpected to the owner.

---

### Task 11: `_PRODUCED`, documentation, and decision-record sweep

**Files:**
- Create: `Organized_Videos/_PRODUCED/_README.md`
- Modify: `README.md`, `CHANGELOG.md`, `NEXT.md`

- [ ] **Step 1: Create `Organized_Videos/_PRODUCED/`** with a `_README.md` stating: home of finished/edited video work; contents arrive from the NAS `_Produced` share (14 GB) at the next NAS session; two follow-ups owed that session — hash-check `Shooting` against the archive (expected all-duplicates) and check whether `_Produced` covers the 2009-12-25 footage lost in the two scrambled MTS files.
- [ ] **Step 2: Update `NEXT.md`** — mark deferred decision 1 resolved (destination: `Organized_Videos/_PRODUCED/`, copy pending NAS session); record the backup system (drive name, versioning mechanism chosen in Task 2, re-sync-after-each-milestone cadence) and the Desktop-copy deletion with its reconcile report reference.
- [ ] **Step 3: Update `README.md`** — document `_FAMILY_HISTORY_/`, `00 Circa`, the person-tag + `date-estimated` conventions, and `backup_archive.py` / `reconcile_quicksave.py` / `route_family_scans.py` usage (SCRIPTS.md too if it indexes scripts).
- [ ] **Step 4: Add a `CHANGELOG.md` entry** for the feature set.
- [ ] **Step 5: Verify docs claims** — every referenced path exists (`git ls-files` + `ls` checks); run the full test suite once more.
- [ ] **Step 6: Commit** — `git commit -m "Document family-history conventions, _PRODUCED home, and backup system"`

---

### Task 12: Post-import backup re-sync

**Files:** none (operational)

- [ ] **Step 1: Version, then sync** — `.venv/bin/python backup_archive.py sync > .TMP_backup_resync.log 2>&1` (the tool versions before mirroring by design; confirm the log shows the snapshot/link-dest step preceding rsync).
- [ ] **Step 2: Verify** — `backup_archive.py verify`; Expected exit 0; prior version still accessible on the drive (list snapshots or the dated link-dest tree).
- [ ] **Step 3: Wrap-up report to owner** — bucket counts imported, holding-folder contents by batch, freed disk, backup state, and the standing NAS-session follow-ups.
