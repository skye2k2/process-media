# Design: Family-history takeout import, person tagging, and external-drive backup

**Date:** 2026-10-21
**Status:** Builder-checked, owner decisions incorporated — pending final owner approval

## Intent and why

Two goals converge here. First, a new Google Takeout (7.1 GB, four parts, in `TO_PROCESS/thebergmannfamily google takeout/`) holds a mix of scanned family-history photos, a sister's wedding, and genuine modern digital photos — and the scans must not scatter into the real 2013–2014 archive, because their timestamps are scan dates, not depicted dates. Second, the organized archive (91 GB photos + 106 GB videos) currently has no backup at all, while a stale 158 GB point-in-time copy squats on the internal disk. The owner wants one working copy, one verified external backup, and the internal duplicate gone — then curation can continue with confidence.

The scanned photos are curated highlights associated with the owner's father, **Clifford Bergmann**, scanned in 2013–2014 around his death (plus a smaller second scanning session visible in "Photos from 2023"). They belong in the main chronological archive filed by the era they depict, tagged with his name using a convention that will later extend to other family members.

## Goals

1. Import the new takeout so every file lands correctly: scans chronologically where a real or recoverable date exists, undated scans in a holding area, wedding photos as one event, modern photos through the normal workflow.
2. Establish the person-tagging metadata convention and apply "Clifford Bergmann" to every scan in this import.
3. Create `Organized_Videos/_PRODUCED/` as the home for finished/edited video work (contents copied from the NAS `_Produced` share when the NAS is next powered on).
4. Reformat the external 4 TB drive to APFS and establish a browsable-mirror-plus-snapshots backup of the live archive, verified by hash.
5. Rescue the unique records (removal scripts, README, screenshots) out of the Desktop copy into the repo, then — with explicit owner approval — delete the 158 GB Desktop duplicate.

## Non-goals

- Re-processing the corrupted originals recovered in the earlier rescue effort. They stay parked next to their recovered counterparts and ride along in the backup. Deferred by owner decision.
- The remaining unscanned photo albums (a possible future scanning project).
- The Chromecast / Google Photos round-trip for the tagged highlights. Future work; this design must simply not block it (embedded, standards-based metadata is the enabler).
- The one-way local→NAS sync. Already decided separately (NEXT.md decision 4: content-addressed tool, e.g. restic, not rsync). Out of scope here except that nothing in this design may contradict it.
- Resolving the `Shooting` folder on the NAS. Expected to duplicate already-imported raw footage; verification is a recorded follow-up for the next NAS session, not part of this work.

## Anti-goals (failure even if it "works")

- Any undated scan filed into a real year/month folder it does not belong to. Scattering is the original sin this design exists to prevent.
- Any deletion (especially the 158 GB Desktop copy) before the backup is written **and verified by hash** and the owner has approved the deletion.
- A backup that silently inherits a bad curation pass with no way back — hence snapshots before every sync while curation is still reshaping the archive.
- Person-tag metadata written in a proprietary or sidecar-only form that does not travel with the file to the NAS, the backup drive, or a future photo service.

## The decisions, as the owner made them

### 1. Scanned photos: chronological, three buckets

Classification of the takeout's ~3,700 sidecars (dupes across parts not yet merged) found:

| Bucket | Approx. count | Rule |
|---|---|---|
| Backdated — `photoTakenTime` already in 1963–2012 | ~144 | Normal chronological filing; no new machinery. |
| Filename-year — scan-era timestamp, year in the filename (`1980-youth-065.jpg`, `1990_13.jpg`, `1997_8.jpg`) | ~600+ | Backdate mechanically to the named year; file chronologically. |
| Unknown — batch-scanner names (`cars-045`, `cards-010`, `family-BB-016`, `FH000011`, `0NBergm-R1-040-18A`), no year anywhere | ~1,750 | Holding folder. **No manual dating pass now** — these span 40 years and placing each would mean paging through 20 physical albums. |
| Wedding ("Carina + Charlie" albums, split across parts 1/3/4) | ~166 | Existing dedupe/merge reunites them; sidecars carry a real date (2023-06-04), so it lands as one event folder in 2023. |
| Modern digital (2021–2024 tablet/phone, "Friends", shared albums) | ~600 | Normal takeout workflow. |

The ~140 unknown-named files inside "Photos from 2023" are a second scanning session and follow the same rules.

**Holding folder** (lead's call, owner may veto): `Organized_Photos/_FAMILY_HISTORY_/`, a top-level sibling of the year folders — visually separate from real years. Inside it, subfolders by scan-batch prefix (`cars/`, `cards/`, `family-BB/`, …) so the future review works one batch at a time. Files graduate out into year folders as the owner dates them.

**Estimated-date convention** (lead's call): a mechanically backdated file gets its date set to the named year with a marker that the date is estimated (e.g., a keyword such as `date-estimated`), so the future enrichment pass can distinguish real dates from circa dates. Exact marker form is the builder's choice, but it must be embedded and queryable.

**Month placement for year-only estimates** (owner decision): year-only backdates land in a `YYYY/00 Circa/` folder — sorts first within the year, honestly labeled, and files graduate into real month folders as the owner dates them. Real month folders never receive fabricated dates.

### 2. Person tagging: the archive-wide convention starts here

Write "Clifford Bergmann" into every file in the three scan buckets (backdated, filename-year, unknown/holding) as embedded metadata:

- `XMP-iptcExt:PersonInImage` — the standards-correct field, read by self-hosted tools (Immich, PhotoPrism).
- A plain keyword (`XMP-dc:Subject` / IPTC Keywords) with the same value — the broad-compatibility field read by Apple Photos, Lightroom, and survivable through most pipelines.

Both fields, always, on **every file in the scan buckets** — including the object-photo batches (`cars`, `cards`). Owner decision, made aware of the person-view pollution tradeoff: object photos are a minority of the scan set, so stripping the tag from the few obvious non-person photos later is cheaper than adding it to hundreds the other way. This is the convention for all future family-member tagging; this import is its first application. The owner's later enrichment pass (event details) will use the embedded `Description`/`ImageDescription` fields the same way — nothing to build now, just don't fight it.

**Never write `Artist`/`Creator` for scans** (lead's call): those fields assert authorship, and Clifford Bergmann is the subject, not the photographer. **This import runs without `--person` entirely** (owner decision): the takeout is the family account, so no single-name filename suffix fits; person identity lives in the embedded-tag convention above, filenames stay clean, and collision resolution falls back to the content hashing the workflow already performs.

### 3. Produced videos: `Organized_Videos/_PRODUCED/`

Finished, edited video work (e.g., "Jacen's First Year" compilation, the annotated Frozen scene) lives in `Organized_Videos/_PRODUCED/`, a top-level sibling of the year folders. Contents come from the NAS `_Produced` share (14 GB, includes multiple resolution exports of the first-year video) at the next NAS session. Two recorded follow-ups for that session, not blockers here: hash-check `Shooting` against the archive (expected all-duplicates), and check whether `_Produced` covers the footage lost in the two scrambled 2009 MTS files.

### 4. Backup: APFS, browsable mirror, snapshots while curation is live

- **Reformat** the 4 TB external (`/Volumes/BACKUP`, currently exFAT, 27 MB used — nothing to preserve) to **unencrypted APFS** (owner decision, offsite tradeoff surfaced: zero-friction mounting on any Mac over at-rest protection) on the existing GUID scheme. Default APFS block size (the owner raised block size; APFS defaults are correct for a media backup — lead's call). Volume name: builder's choice, something unambiguous like `MEDIA_BACKUP`.
- **Contents:** the live `Organized_Photos/`, `Organized_Videos/`, the repo's `_records/`, `_Timeline/`, caches, and the rescued removal records. Plain browsable folders — plug into any Mac and see the years.
- **Snapshots:** take a snapshot on the destination before each sync, so a bad curation pass that reaches the backup still has a prior state to fall back to. Owner's explicit framing: this versioning matters **while curation is reshaping the archive**; once the drive's role changes to a pure offsite clone of the NAS, the snapshot layer may be dropped. **Mechanism (lead's call, feasibility-gated):** macOS has no clearly supported path to APFS snapshots on a non-boot volume — `tmutil snapshot`/`localsnapshot` target the boot volume group and `diskutil apfs` can only list/delete. First, test `tmutil localsnapshot` against the freshly formatted drive and confirm a snapshot appears in `diskutil apfs listSnapshots`; if that fails, fall back to rsync `--link-dest` hard-link rotation (dated, browsable, hard-linked tree per sync). No commercial backup software and no custom `fs_snapshot_create` sudo code. Snapshot retention/pruning: builder's choice, simple is fine.
- **Verification:** after the initial sync, verify by hash (full manifest, not spot checks — this backup gates a 158 GB deletion).
- **Sequencing of the Desktop copy:** before anything else, rescue out of `…/2025-12 google-photo-original-takeout/`: the three dated `remove_photos.sh` scripts, the `README.md` beside them, and all screenshots/PNGs (both at the quick-save root and the takeout root). Destination in-repo: removal scripts into `_records/`, screenshots into `_Timeline/` (lead's call on exact placement). Only after the backup is verified AND the owner gives explicit approval is the 158 GB Desktop duplicate deleted.

### 5. Order of operations

1. Rescue removal scripts, README, and screenshots from the Desktop copy into the repo; commit.
2. Reformat the external drive to APFS.
3. Initial backup sync of the live archive + records to the drive; full hash verification.
4. **Reconciliation pass** (lead's call, added after builder review): hash-check the Desktop quick-save against the live archive plus the recorded removal history. Every quick-save file must be either present in the archive by content hash or accounted for in removal records; unexplained absences surface for owner review. The backup-verified gate alone proves archive→drive and nothing about quick-save→archive, and deletion is the one irreversible step in this plan.
5. Owner-approved deletion of the Desktop duplicate (frees ~158 GB; internal disk goes from 200 GiB free to ~358 GiB).
6. Process the new takeout per §1–§2 (small-subset test first, per repo convention). Copy the 7.1 GB takeout to the backup drive beforehand as cheap insurance against an import that mutates it.
7. Snapshot + re-sync the backup.
8. Curation continues; re-sync after each milestone. NAS sync happens later under the separately recorded plan.

Backup-before-import is deliberate: the current archive state is protected before the takeout import changes it.

## Constraints

- All metadata operations via exiftool (batch mode — thousands of files); scripts invoked as `.venv/bin/python`, per AGENTS.md.
- The takeout import should reuse the existing `workflow_takeout.py` machinery (dedupe across parts, JSON sidecar merge, event foldering) rather than invent a parallel path; the scan-bucket handling is a pre-classification/routing layer in front of it, not a replacement.
- Test on 5–10 files before any bulk pass; dry-run flags where available.
- The sync tool for local→drive is the builder's choice (rsync is acceptable here — unlike the NAS case, the drive is dedicated and renames are cheap on first sync; if the event-folder rename problem recurs on later syncs, revisit).
- Nothing in this project touches the NAS.

## What's left to the builder

- Exact exiftool field writes and the estimated-date marker form.
- **Known hazard:** `organize_media.py`'s filename/path date validators hard-bound years to 1990–2100, while this import legitimately reaches 1963 — whose sidecar timestamps are *negative* epoch values (`media_utils.py` parses JSON timestamps unbounded, so sidecar-sourced dates are fine, but any path through the filename/EXIF validators must be small-subset tested against pre-1990 files before the bulk pass).
- The classification script that routes takeout files into buckets (the throwaway `.TMP_classify_takeout_dates.py` from the brainstorm is a starting sketch, not product code).
- Sync invocation, snapshot mechanism (`tmutil`/`diskutil apfs` specifics), manifest/verification tooling.
- Snapshot retention policy.
- Exact in-repo placement of rescued records and the commit structure.
