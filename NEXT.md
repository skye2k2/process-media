# NEXT.md — what is actually left to do

> **Anything fixed now lives in [CHANGELOG.md](CHANGELOG.md)**, which is the permanent record; this file is only the forward-looking list and should stay short. Standing conventions and the lessons worth not relearning are distilled in [DECISIONS.md](DECISIONS.md); the August video-recovery effort's full findings live in [`_records/video-recovery-history.md`](_records/video-recovery-history.md).

---

## Current state

The archive lives in `Organized_Photos/` and `Organized_Videos/` (year/month folders plus named event folders), is hash-verified onto the external `MEDIA_BACKUP` drive, and the test suite passes via `.venv/bin/python test_core.py` (plus `test_family_import.py` and `test_backup_tools.py`).

Remember: **Always run scripts as `.venv/bin/python`, never bare `python3`** — see README "Setup".

Four NAS shares mount from TrueNAS: `photos` (a stale Jan-2026 mirror of the archive — *not* a source), `photosync` (the source trees), `videos`, and `home-movies`. Nothing has been synced local→NAS yet, deliberately (decision 3 below).

**Last session (2026-10-22, CHANGELOG v22):** external backup established and verified; family-history takeout imported via the new `route_family_scans.py` pre-pass with zero scatter into real 2013–2014; the 158 GB Desktop quick-save reconciled and deleted. Full design in `docs/superpowers/specs/2026-10-21-family-history-import-and-backup-design.md`.

---

## Ready to run

1. **PhotoSync import** — 649 of 8,609 files would import; verified with all gates active. `organize_archive.py` *moves* files, so stage a copy rather than pointing it at the share.
2. **2021 Google archive** — 1,277 of 13,889 would import, but these are **not yet classified** for same-dimension recompression pairs; expect the recompression gate to absorb most. Classify before importing.
3. **Event folders** — re-run `create_event_folders.py` after imports land so new arrivals get filed.
4. **Review and prune** — reports at `Organized_Photos/_review_issues.html` and `_browse_all.html`. Deliberately deferred until conversions, imports and cataloguing finish, because review state is path-keyed and every import invalidates it.
5. **Family-history dating pass** — `Organized_Photos/_FAMILY_HISTORY_/` holds the undated scans by batch folder; files graduate into year/month folders as they're dated, and `YYYY/00 Circa/` files graduate as real dates replace the `date-estimated` estimates. Human-paced; no tooling blocker.
6. **Backup re-sync** after every curation milestone: `.venv/bin/python backup_archive.py sync`, then `verify`.

## Next NAS session, in one batch

- Copy `_Produced` (14 GB) into `Organized_Videos/_PRODUCED/` (destination decided 2026-10-21; see its `_README.md`).
- Hash-check `Shooting` against the archive — expected all-duplicates of imported raw footage.
- Check whether `_Produced` covers the lost 2009-12-25 footage before writing off the two scrambled 2009 MTS files (decision 2 below).

## Standing warnings (video recovery — details in `_records/video-recovery-history.md`)

- **Do not delete the NAS sources** for `2009/00009`, `2009/00017`, `2010/00039`, `2010/00065`, `2010/00071` — the transcodes hold only part of their footage.
- **13 home-movies files hold no footage at all** (foreign content); the only plausible clean source is the original SD cards/camcorder media, if they still exist. Check before the share is retired.
- `_RESCUED/` can be cleared only after its **9 MP3s are hand-discarded** (deliberately not automated).

---

## Decisions waiting on a human

| # | Decision | Why it is not mine to make |
|---|---|---|
| 1 | **`convert_legacy.py` CRF 20 vs `camcorder_convert.py` CRF 26** | Camcorder was raised to 26 after 20 produced bloated files. The reasoning probably transfers, but changing it alters quality and size for every future legacy conversion. |
| 2 | **11 zero-byte + 2 scrambled MTS** (`home-movies/2014/00123–00133`, `2009/00006`, `2009/00026`) | The two 2009 files are unrecoverable — structurally scrambled rather than truncated. Both sit inside a 2009-12-25 session with ~20 healthy clips, so coverage survives. Check `_Produced` first (NAS-session batch above). |
| 3 | **NAS sync strategy** | Must be one-way local→NAS. Prefer a content-addressed tool (`restic`) over a path-based one (`rsync`): ~10,500 archived files sit at different paths after the event-folder pass, which `rsync` would read as mass delete plus mass re-upload. |

---

## Open engineering concerns

**CONCERN-1 — review decisions are not durable.** KEEP/REMOVE state lives only in browser `localStorage`, keyed by path, so any import or event-folder run orphans it. `removal_history.py` already makes *removal* decisions durable; the gap is **KEEP** decisions, which are never recorded, so every re-review re-presents them. 53,087 MD5s are now cached, so keying decisions to content hash is realistic. **Deferred by choice** until imports and cataloguing are done.

**CONCERN-2 — `photo_triage.py` is ~4,600 lines.** Extracting the two inline HTML-app generators is the obvious first cut. Not urgent, and it is the riskiest file in the project to touch — leave it until imports are finished.

**CONCERN-3 — two independent duplicate-detection systems.** `scan_for_duplicates()` (triage) and `DuplicateDetector` (imports) share no interface. Accepted: they answer different questions. The cost is that a fix to one does not propagate, which is how BUG-6 survived in only one of them.

**CONCERN-4 — one-level takeout discovery.** `find_google_photos_dirs` and `cleanup_orphaned_json` only look one level below the input dir, so a takeout nested inside a wrapper folder bypasses project-folder handling (bit us 2026-10-22; README documents the trap). Fix = recursive discovery, or keep the documented convention.

**CONCERN-5 — `move_file_safely`'s `-edited_{suffix}` check** matches `-edited__Name` (double underscore) and likely never fires on person runs. Pre-existing; behavior deliberately preserved by the 2026-10-22 personless-crash fix.

Deferred minors from the 2026-10-22 review (ledgered, none urgent): exiftool `+=` appends duplicate tag values on router re-runs; `merge_sidecars` ignores merge exit codes; no snapshot retention policy on the backup drive yet (unbounded, manual pruning); the project-twin guard matches basename only; `RouteAction` annotations don't admit `None`.

---

## Longer horizon

**Immich** (evaluated 2026-07-30, deferred). Would dissolve CONCERN-1 outright, but it does not do blur/quality triage or multi-signal keeper selection, and external libraries treat a **moved file as a new asset** — incompatible with a pipeline that relocates thousands of files, and under an upstream feature freeze. Viable shape: this toolkit as pre-processing, freeze the tree, then Immich for browse/search/faces. `immich upload --album` converts the event folders directly.

**Re-encode pass** (deferred, poor value at current scale): ~230 files, ~270 MB saved, in exchange for a lossy rewrite of irreplaceable originals. Safeguards recorded in CHANGELOG v15 if revisited at archive scale.

## Still open from the original hand-written TODO (reconciled 2026-07-31; resolved items in DECISIONS.md)

- **Shared Takeout directory cleanup** — 11 comma-named shared folders holding 53 orphaned sidecar JSONs; verify every photo has a counterpart in its proper year/month, then remove the folders. Straightforward now that content-hash matching exists.
- **The 898 `-edited` files** — ruling recorded (quality-measure decides the keeper) but unimplemented; `analyze_photo_quality.py` already detects edited pairs, so the missing piece is the decision rule plus a batch pass. `removal_history.py` deliberately treats `-edited` as a distinct asset.
- **A real-file test corpus** — the suite uses synthetic fixtures (right call for speed); still missing is a small integration corpus of genuine oddities found in the wild: truncated JPEG, scrambled MTS, HEIC, AVCHD clip, `~2` crop variant, burst pair, same-second collision.
- **The wedding/college DVD** — physical media search, including the first and second Nikon pocket camera photos; add the wedding DVD in its entirety as an event.
- **Tags for best-of and people** — events are solved (folders); best-of and people are not. The person-tag metadata convention (first applied 2026-10-22) is the foundation; Immich remains the biggest argument for faces.
- **Google Photos cloud reconciliation** — `removal_history.py` holds 2,529 removed names; what remains is the rate-limited Google Photos API work to delete them in the cloud.
- **"I never want to do a full Takeout again"** — delivered except for the NAS sync strategy (decision 3), so the archive is published somewhere durable.
