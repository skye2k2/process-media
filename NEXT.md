# NEXT.md — what is actually left to do

> Rewritten 2026-07-31. This file had grown to 955 lines, most of it resolved issues carrying their full investigation notes. **Anything fixed now lives in [CHANGELOG.md](CHANGELOG.md)**, which is the permanent record; this file is only the forward-looking list and should stay short. If you want to know *why* something was done, or need the measurements and the approaches that were tried and rejected, read the CHANGELOG. Versions v10–v17 all landed on 2026-07-30/31 and carry the detail.

---

## Current state

35,210 photos and 2,302 videos organized under `Organized_Photos/` and `Organized_Videos/`, in year/month folders plus 131 named event folders. 196 tests pass via `.venv/bin/python test_core.py`.

**Always run scripts as `.venv/bin/python`, never bare `python3`** — see README "Setup". Bare `python3` has no OpenCV, and `photo_triage.py` exits immediately without it.

Four NAS shares mount from TrueNAS: `photos` (a stale Jan-2026 mirror of the archive — *not* a source), `photosync` (the source trees), `videos`, and `home-movies`.

---

## In flight

**home-movies AVCHD conversion.** `workflow_camcorder.py /Volumes/home-movies --keep-originals --avchd-only`, running in background, log at `.TMP_camcorder_run.log`. 669 files, 86.7 GB, roughly 20 hours. Resumable — the conversion index is written per file, so an interruption costs one conversion.

```
grep -c "Converted:" .TMP_camcorder_run.log      # progress out of 669
tail -3 .TMP_camcorder_run.log                   # current file
```

---

## Ready to run, queued behind the conversion

1. **PhotoSync import** — 649 of 8,609 files would import; verified with all gates active. `organize_archive.py` *moves* files, so stage a copy rather than pointing it at the share. That is how the 21-file home-movies batch was done, and all 21 NAS originals stayed in place.
2. **2021 Google archive** — 1,277 of 13,889 would import, but these are **not yet classified** for same-dimension recompression pairs. That archive predates Google's storage-saver downsizing, so its originals should be systematically larger than what is archived; expect the recompression gate to absorb most of the 1,277. Classify before importing.
3. **Event folders** — re-run `create_event_folders.py` after the imports land so new arrivals get filed.
4. **Review and prune** — reports are current at `Organized_Photos/_review_issues.html` and `_browse_all.html`: 733 duplicate groups, 92 high-confidence removals, 598 needing judgement. Deliberately deferred until conversions, imports and cataloguing are finished, because review state is path-keyed and every import or event-folder run invalidates it.

---

## Decisions waiting on a human

| # | Decision | Why it is not mine to make |
|---|---|---|
| 1 | **`_Produced` (14 GB) and `Shooting`** on the home-movies share | Curated, edited output. Whether finished work belongs in a dated archive is an editorial call. Currently held back from the import. |
| 2 | **`convert_legacy.py` CRF 20 vs `camcorder_convert.py` CRF 26** | Camcorder was raised to 26 after 20 produced bloated files. The reasoning probably transfers, but changing it alters quality and size for every future legacy conversion. |
| 3 | **11 zero-byte + 2 scrambled MTS** (`home-movies/2014/00123–00133`, `2009/00006`, `2009/00026`) | The two 2009 files are unrecoverable — structurally scrambled rather than truncated. Both sit inside a 2009-12-25 session with ~20 healthy clips, so coverage survives. Worth checking whether `_Produced` covers that footage before writing it off. |
| 4 | **NAS sync strategy** | Nothing has been synced yet, deliberately. Must be one-way local→NAS. Prefer a content-addressed tool (`restic`) over a path-based one (`rsync`): ~10,500 archived files sit at different paths after the event-folder pass, which `rsync` would read as mass delete plus mass re-upload, writing far more to the NVMe pool than necessary. |

---

## Open engineering concerns

**CONCERN-1 — review decisions are not durable.** KEEP/REMOVE state lives only in browser `localStorage`, keyed by path, so any import or event-folder run orphans it. Half-solved already: `removal_history.py` makes *removal* decisions durable, matches by name rather than path, and currently blocks 2,529 previously-deleted files from returning. The gap is **KEEP** decisions — `exportDecisions`/`exportRemovals` only ever emit `rm` lines, so "I looked at this and chose to keep it" is never recorded, and every re-review re-presents it.

Far more tractable than when first raised: 53,087 MD5s are now cached, so keying decisions to content hash rather than path is realistic. **Deferred by choice** until conversions, imports and cataloguing are done — the right call, since reviewing first would only waste the decisions.

**CONCERN-2 — `photo_triage.py` is ~4,600 lines.** Generates two complete HTML apps with inline CSS/JS alongside EXIF extraction, blur analysis, burst detection, duplicate scanning, auto-triage moves, and a CLI. Extracting the HTML generators is the obvious first cut. Not urgent, and it is the riskiest file in the project to touch — leave it until imports are finished.

**CONCERN-3 — two independent duplicate-detection systems.** `scan_for_duplicates()` (MD5 + pHash, used by triage) and `DuplicateDetector` (date pattern + duration + size + content hash, used by imports) share no interface. Accepted rather than treated as a defect: they answer different questions. The cost is that a fix to one does not propagate, which is exactly how BUG-6 survived in only one of them.

---

## Longer horizon

**Immich** (evaluated 2026-07-30, deferred). Would dissolve CONCERN-1 outright — Postgres-backed state, a real review UI, face recognition, mobile ingest, in-place external-library indexing. But it does **not** do blur/quality triage, over-captured-day detection, or multi-signal keeper selection, and its duplicate preselection is by file size alone. The blocking conflict: external libraries treat a **moved file as a new asset** and discard metadata on rescan, which is incompatible with a pipeline that relocates thousands of files — and external libraries are under an upstream feature freeze. The viable shape is complementary: this toolkit as pre-processing, freeze the tree, then Immich for browse/search/faces. `immich upload --album` derives albums from folder names, so the 131 event folders convert directly.

**Re-encode pass** (deferred, poor value at current scale). Re-encoding originals at q85–q90 gives 0.44–0.61× size at SSIM 0.984–0.989. But with the 0.92 floor keeping archived copies, only ~230 files would be affected, saving ~270 MB in exchange for a lossy rewrite of irreplaceable originals. Six safeguards are recorded in CHANGELOG v15 if this is ever revisited at archive scale, where ~35 GB is recoverable across 91 GB.

---

## The original hand-written TODO list, reconciled

These were the scratch notes kept at the end of the README while the tool was built. Reconciled against what shipped on 2026-07-31; the README block was removed once each item had a home.

### Resolved

| Original note | Outcome |
|---|---|
| "identical duplicates are still not being called out as such" | Two separate causes. BUG-3 (v5) was scanning a subfolder instead of the archive root. BUG-6 (v12) was the deeper one: EXIF-only files, 26% of the archive, never reached the index at all. |
| "duplicate resolver prioritizes newer copies… timestamps differ by a single microsecond… shared photo in an odd folder is preselected" | BUG-1 (v5). `_sort_paths_by_keeper_priority()` replaced mtime with EXIF date, a review-area penalty, size, and filename length. |
| "duplicate resolver should also take resolution into account… if two photos have very high SSIM, same resolution, different filesizes, the smaller should probably win" | Both halves. BUG-2 (v5) added resolution comparison for perceptual duplicates. The same-resolution case became CONCERN-7 and the 0.92 SSIM ruling, implemented in v15 — calibrated against a re-encoding ladder by eye. |
| "handle the NIKON DSCN-prefixed photos… copy over and process the NIKON SD card (determine if any are missing)" | v5 confirmed no code change was needed, v6 built `reconcile_nikon_archive.py`, the May batch ingested them, and 2026-07-31 verified **4,502 of 4,502** already archived, byte-for-byte. |
| "find our missing home movies (2013-2016, 2017-2019)" | They were on the `home-movies` NAS share the whole time — never mounted in an earlier session. 130 GB, 1,465 files, 2009–2022, converting now. |
| "see the original PhotoSync files… and if they really are higher-resolution, before building in more complexity" | Answered. Same pixel dimensions, 2–8× larger bytes, and blockiness measurement proves the archived copies carry the compression damage. That answered "is it worth complexity" with a measured yes, then the 0.92 ruling settled which copy wins. |
| "smash together the cache removal, recache, and re-browse functionality" | `workflow_review.py` (v9) chains cache warm-up, review report, and browse report into one command. |
| "we need all of this to work with pre-existing data on our NAS, so we don't have to transfer hundreds of gigabytes" | Proven. Dry-runs and the camcorder conversion all read directly off the share; at ~2 MB/s of reading, the network is not the bottleneck and encoding dominates. No local copy needed. |

### Still open, with the scope now measured

- **Shared Takeout directory cleanup.** The original note: *"it might be better to just run a check across all takeout shared directories when detected to see if all photos exist in their proper places, and then just remove those directories, because this has caused a bunch of cleanup drama."* Still true, and now quantified: **11 comma-named shared folders** (`2022/08 Nicole, Sara Klein`, `2022/10 Clif, Jacen`, …) holding **53 orphaned sidecar JSONs**. The check is straightforward now that content-hash matching exists — verify every photo in a shared folder has a counterpart in its proper year/month, then remove the folder.

- **The 898 `-edited` files.** The original note asked how to resolve *"the hundreds of -edited files, many of which don't actually make a dramatic enough improvement to merit the space."* It is 898, not hundreds. A ruling was recorded earlier — *"the automatic winner should probably be determined by if the blur factor or other indicators of poor quality measure as less"* — but nothing implements it. `analyze_photo_quality.py` already has edited-pair detection, so the missing piece is the decision rule plus a batch pass. Note that `removal_history.py` deliberately treats `-edited` as a distinct asset, so removing one says nothing about the other.

- **A real-file test corpus.** The original note wanted *"a test directory containing each typical and problem file we are handling, to be able to exercise the code fully in a closed system."* Half-met: 196 tests exist, but they build synthetic fixtures rather than using real problem files. That was the right choice for speed and hermeticity, and it is why the suite runs in under two seconds. What is still missing is an integration corpus of genuine oddities — the truncated JPEG, a scrambled MTS, a HEIC, an AVCHD clip, a `~2` crop variant, a burst pair, a same-second collision. Every one of those has been found in the wild during this work and could be copied into a small fixture directory.

- **The wedding/college DVD.** Physical media search, including the first and second Nikon pocket camera photos, plus the wedding photo DVD to be added in its entirety as an event.

- **Tags for best-of, people, and events.** Events are effectively solved — they are folders now, 131 of them. Best-of and people are not. This is the single biggest argument for the Immich direction, which does face recognition and tagging out of the box.

- **Google Photos cloud reconciliation.** The original note: *"can we keep track of the removed files and build a tool to interact with google photos to remove them in the cloud, as well? i have kept each of the removal scripts."* The foundation now exists — `removal_history.py` parses exactly those scripts and holds 2,529 names. What remains is the Google Photos API work, which is rate-limited and awkward.

- **"I never want to do a full Takeout again."** Largely delivered — the incremental import path works, and the removal history stops deleted files returning. The remaining piece is the NAS sync strategy above, so that the archive is actually published somewhere durable.

---

## Hard-won lessons worth not relearning

Full detail in the CHANGELOG; these are the short forms.

- **Perceptual hashing cannot verify a duplicate match.** Across 500 real decisions, true duplicates scored a pHash distance of 0 *every time* while mispaired burst frames scored 0–16 — one at exactly 0 with an SSIM of 0.7597. Burst frames are the same scene, which is precisely what pHash is built to call identical.
- **Duration alone cannot match videos.** Reported 94.3% overlap and was completely wrong: at ±1.5 s across 2,169 videos, a 2009 camcorder clip "matched" a 2018 phone video. Use the recording timestamp, which the naming convention preserves.
- **mtime is 88% reliable as a date source** — acceptable as a last-resort fallback, useless as a confirmation signal.
- **A sampling loop with an early exit does not produce a rate.** "40 of 1,180" was a stop-at-N artifact, not 3.4% prevalence; the real figure was ~49%.
- **Defaults that are safe for `TO_PROCESS/` are destructive against an archive.** Both `camcorder_convert.py` (deletes sources) and `organize_archive.py` (moves them) assume a disposable staging copy. Guards now exist, but stage a copy anyway.
- **Camcorder filenames recycle per card.** `00000.MTS` means nothing across cards — NAS `00003.MTS` is 185 MB where the index records 49 MB for the same name. Match on recording date and size.
- **ZFS cannot see inherited corruption.** This data crossed three NAS generations and only the current one runs ZFS, so anything that arrived already damaged has been checksummed as "correct" ever since. Format-level validation via `check_media_health.py` is the only check that sees it.
- **Run the suspect code against real data before rating a bug.** Reading it produced the wrong severity three times running — BUG-5, BUG-6, and the undated-AVCHD "repair" that turned out to be unnecessary.
