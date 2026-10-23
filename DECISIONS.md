# DECISIONS.md — standing decisions and hard-won lessons

The clean map of what was decided, what was measured, and which problems must not be repeated. Each entry is dated and points at its evidence (a CHANGELOG version, a records file, or a spec). [CHANGELOG.md](CHANGELOG.md) remains the full chronological record; [NEXT.md](NEXT.md) holds only what is still ahead.

---

## Conventions in force

- **Keeper floor: SSIM 0.92** (2026-07-30, CHANGELOG v15). Calibrated by eye against a re-encoding ladder; everything at or above it is "not worth caring about" visually. The same floor cleared every home-movies transcode.
- **Camcorder conversions use CRF 26** (CHANGELOG, camcorder effort). CRF 20 produced bloated files. Whether `convert_legacy.py`'s CRF 20 should follow is an open decision in NEXT.md.
- **Archive naming is capture-date-first**: `YYYYMMDD_HHMMSS…`, with `_CAM` marking camcorder conversions and `_DAMAGED` permanently marking partial recoveries so they are never mistaken for clean originals (2026-08-09, `_records/video-recovery-history.md`).
- **`-edited` is a distinct asset** everywhere — dedupe, removal history, routing. Removing or keeping one implies nothing about the other.
- **Person identity is embedded metadata, not filename suffixes** (2026-10-21, family-history spec): `XMP-iptcExt:PersonInImage` + `XMP-dc:Subject` + `IPTC:Keywords`, all three, never `Artist` (that field asserts photographership). Family-account takeouts run without `--person` entirely. First applied as "Clifford Bergmann" across the scan buckets.
- **Estimated dates are marked**: a mechanically backdated file gets Jan 1 of its year plus the `date-estimated` keyword, and lives in `YYYY/00 Circa/` rather than a real month folder. Real month folders never receive fabricated dates. Undated scans wait in `Organized_Photos/_FAMILY_HISTORY_/<batch>/`.
- **Scan-bearing takeouts run `route_family_scans.py` before `workflow_takeout.py`** — organize_media trusts filename dates then sidecar JSON, and a scan's sidecar date is its scan date. The router also deletes identical scan-year twins of backdated files so the name dedupe can never discard the correctly dated copy (2026-10-22, CHANGELOG v22).
- **Backup is link-dest rotation with full-manifest verification** (2026-10-22): dated browsable trees on the APFS `MEDIA_BACKUP` drive (unencrypted by owner decision; `tmutil` cannot snapshot a non-boot volume — tested), `verify` reads every byte on both sides, and no deletion of a source copy happens without a verified backup plus an explicit reconciliation of that copy. Re-sync after every curation milestone.
- **The backup set is data, not code** (2026-10-23, owner decision): `Organized_*`, `TO_PROCESS`, `_RESCUED`, `_records`, and the caches. Git plus the GitHub remote protect code and docs — backing them up on the drive would shadow version control. Corollary: unpushed commits are protected by *nothing*, so push state matters.
- **Stage a copy before importing from an archive.** `organize_archive.py` moves files and `camcorder_convert.py` deletes sources; both are correct against disposable `TO_PROCESS/` copies and destructive against a NAS share or card. Guards exist; the habit is still the protection.
- **Takeouts are extracted so `Takeout*/` sits directly under the input dir** — project-folder (album) discovery looks exactly one level down (bit us 2026-10-22; CONCERN-4 in NEXT.md tracks the code fix).

## Measured lessons — problems not to repeat

- **Perceptual hashing cannot verify a duplicate match.** Across 500 real decisions, true duplicates scored pHash distance 0 *every time*, but mispaired burst frames scored 0–16 — one at exactly 0 with an SSIM of 0.7597. Burst frames are the same scene, which is precisely what pHash calls identical.
- **Duration alone cannot match videos.** At ±1.5 s across 2,169 videos it reported 94.3% overlap and was completely wrong — a 2009 camcorder clip "matched" a 2018 phone video. Match on the recording timestamp the naming convention preserves.
- **Duration is not footage either.** Salvaged files keep source timestamps, so recovered frames scatter with gaps; ranking rescues by duration rewarded the gappiest result. Selection and reporting use frame counts (2026-08-09).
- **Cutting at a splice is usually wrong, and so is never cutting.** Neither whole-file decode nor prefix-cut dominates damaged-file recovery; encode both and keep the better (2026-08-09, measured: prefix-cut alone would have lost more than half the recovered frames).
- **mtime is 88% reliable as a date source** — acceptable as a last-resort fallback, useless as confirmation.
- **A sampling loop with an early exit does not produce a rate.** "40 of 1,180" was a stop-at-N artifact; the real prevalence was ~49%.
- **Camcorder filenames recycle per card.** `00000.MTS` means nothing across cards; match on recording date and size.
- **ZFS cannot see inherited corruption.** Data that crossed pre-ZFS NAS generations has been checksummed as "correct" ever since it arrived damaged. Only format-level validation (`check_media_health.py --deep`) sees it — and a container probe is not a decode; video must be held to the photo standard.
- **"Does this decode" is not "is this the right content."** A damaged MTS can be a perfectly valid MP3 stream of someone else's audio. Structural-continuity checking (`detect_splices.py`) separates degraded footage (transcode and salvage) from replaced footage (simply gone) — the remedies are opposite (2026-08-06).
- **A checker that cries wolf teaches you to ignore it.** The first deep scan flagged 11.5% of a healthy archive over muxer noise; filtering attribution to the decoder reduced it to 2 real findings. Prove a check can fail, then make it quiet when nothing is wrong.
- **Google's year view duplicates album photos.** Both project-album copies and backdated-album copies reappear in year albums with different sidecars; any pass that moves one copy first can cause a name-dedupe to delete the better one. Guards now exist in the router; the pattern generalizes (2026-10-22).
- **Run the suspect code against real data before rating a bug.** Reading alone produced the wrong severity three times running (BUG-5, BUG-6, the unnecessary undated-AVCHD "repair").
- **Defaults safe for staging are destructive against an archive** — see the staging convention above; this earned its place by near-misses, not theory.

## The original hand-written TODO, resolved half (reconciled 2026-07-31)

The scratch notes kept at the end of the README while the tool was built, mapped to their outcomes. The still-open half lives in NEXT.md.

| Original note | Outcome |
|---|---|
| "identical duplicates are still not being called out as such" | Two separate causes. BUG-3 (v5) was scanning a subfolder instead of the archive root. BUG-6 (v12) was the deeper one: EXIF-only files, 26% of the archive, never reached the index at all. |
| "duplicate resolver prioritizes newer copies… timestamps differ by a single microsecond… shared photo in an odd folder is preselected" | BUG-1 (v5). `_sort_paths_by_keeper_priority()` replaced mtime with EXIF date, a review-area penalty, size, and filename length. |
| "duplicate resolver should also take resolution into account… if two photos have very high SSIM, same resolution, different filesizes, the smaller should probably win" | Both halves. BUG-2 (v5) added resolution comparison for perceptual duplicates. The same-resolution case became CONCERN-7 and the 0.92 SSIM ruling, implemented in v15. |
| "handle the NIKON DSCN-prefixed photos… copy over and process the NIKON SD card" | v5 confirmed no code change needed, v6 built `reconcile_nikon_archive.py`, and 2026-07-31 verified **4,502 of 4,502** already archived, byte-for-byte. |
| "find our missing home movies (2013-2016, 2017-2019)" | They were on the `home-movies` NAS share the whole time — never mounted in an earlier session. 130 GB, 1,465 files, 2009–2022. |
| "see the original PhotoSync files… and if they really are higher-resolution" | Same pixel dimensions, 2–8× larger bytes, and blockiness measurement proved the archived copies carry the compression damage — then the 0.92 ruling settled which copy wins. |
| "smash together the cache removal, recache, and re-browse functionality" | `workflow_review.py` (v9) chains cache warm-up, review report, and browse report into one command. |
| "we need all of this to work with pre-existing data on our NAS" | Proven: dry-runs and the camcorder conversion read directly off the share; encoding dominates, not the network. No local copy needed. |
