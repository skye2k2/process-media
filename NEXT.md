# NEXT.md — what is actually left to do

> **Anything fixed now lives in [CHANGELOG.md](CHANGELOG.md)**, which is the permanent record; this file is only the forward-looking list and should stay short. If you want to know *why* something was done, or need the measurements and the approaches that were tried and rejected, read the CHANGELOG.

---

## Current state

35,210 photos and 2,815 videos organized under `Organized_Photos/` and `Organized_Videos/`, in year/month folders plus 131 named event folders. 198 tests pass via `.venv/bin/python test_core.py`.

Remember: **Always run scripts as `.venv/bin/python`, never bare `python3`** — see README "Setup". Bare `python3` has no OpenCV, and `photo_triage.py` exits immediately without it.

Four NAS shares mount from TrueNAS: `photos` (a stale Jan-2026 mirror of the archive — *not* a source), `photosync` (the source trees), `videos`, and `home-movies`.

---

## ✅ home-movies conversion complete and verified (2026-08-01)

646 converted, **0 failed**, 76 skipped as already-indexed, 28 held back as damaged. All 750 AVCHD files accounted for. 83.74 GB became 34.04 GB, a 59.4% saving, in 22h 9m against a 19h 34m estimate.

### Verification: no transcoding-caused degradation

Two tiers, because "ffmpeg exited zero" is not evidence when these outputs are about to become authoritative.

**Tier 1, all 646 pairs** — duration, resolution, frame count, audio presence, decodability, mapped from the conversion index rather than guessed from filenames:

| verdict | count |
|---|---|
| ok | **641** |
| short output | 5 |

**Tier 2, 16 files sampled evenly across the size range** — SSIM against the source: worst **0.9277**, median **0.9539**, best **0.9691**. Eleven land in "nearly indistinguishable" (0.95–0.98), five in "minor visible differences" (0.90–0.95). Spot PSNR on the worst and best cases: **36.07 dB** and **44.02 dB**, which is good-to-excellent for lossy H.265.

Worth connecting: the worst transcode at 0.9277 is essentially the same SSIM as the Google recompression reviewed by eye on 2026-07-30 (0.9282), which was judged not worth caring about. The 0.92 keeper floor was set from that judgement, so every transcode here clears the bar the archive already uses.

### The 5 short outputs are inherited damage, not transcoding failure

| source | source errors | duration |
|---|---|---|
| `2009/00009.MTS` | 112 | 103.0s → 30.6s |
| `2009/00017.MTS` | 55 | 54.2s → 41.9s |
| `2010/00039.MTS` | 46 | 54.4s → 44.3s |
| `2010/00065.MTS` | 108 | 81.4s → 32.3s |
| `2010/00071.MTS` | 244 | 105.1s → 56.8s |

All five are in 2009 or 2010, and all five sources carry heavy mid-stream H.264 damage. Every other file sharing those basenames — from the 2011 through 2015 folders — decodes with **zero** errors and transcoded at full duration. ffmpeg decoded until it hit an unrecoverable error, stopped, and exited zero, producing short but structurally valid output.

So roughly 192 seconds of footage is unavailable, and it was already unrecoverable before this project touched it. This fits the pattern of every other defect found on this share: clustered in 2009, 2010 and 2014, consistent with corruption inherited from the pre-ZFS NAS generations.

**Do not delete the NAS sources for these five.** The transcodes hold only part of the footage, and an error-tolerant recovery attempt is still possible.

### Deep reconciliation: the archive is clean, and 3.2 minutes of footage is unavailable

The earlier shallow scan reported 19 problems on this share and called five genuinely damaged sources fine. Its video check probed the **container**, which reports a clean duration regardless of mid-stream damage, while images had always been fully decoded — video was held to a weaker standard than photos, in the one tool whose whole job is answering "is this intact". Added `--deep`, which decodes the entire stream.

**Both trees were then deep-decoded in full.**

`Organized_Videos` — the authoritative copies — is **2,813 of 2,815 clean**. The two exceptions are AAC audio warnings ("channel element 0.0 duplicate") in 2024 phone videos that have nothing to do with any transcoding; their video decodes fine.

`/Volumes/home-movies` — 1,465 files, **43 problems**, against 19 from the shallow scan:

| status | count | share |
|---|---|---|
| ok | 1,420 | 96.9% |
| stream errors | 29 | 2.0% |
| empty | 11 | 0.8% |
| unreadable | 3 | 0.2% |
| not checked | 2 | 0.1% |

**Attribution of all 43, by what actually reached the archive:**

| outcome | count |
|---|---|
| Never converted — held back by the pre-screen or not AVCHD | 30 |
| Converted, **full duration preserved** despite source damage | 8 |
| Converted, **footage lost** | 5 |

The eight in the middle row are the reassuring result: ffmpeg recovered from stream damage in those sources and produced complete transcodes anyway. Only five lost anything.

| source | decode errors | duration |
|---|---|---|
| `2009/00009.MTS` | 110 | 103.0s → 30.6s (−72.4s) |
| `2010/00071.MTS` | 234 | 105.1s → 56.8s (−48.3s) |
| `2010/00065.MTS` | 104 | 81.4s → 32.3s (−49.1s) |
| `2009/00017.MTS` | 52 | 54.2s → 41.9s (−12.4s) |
| `2010/00039.MTS` | 42 | 54.4s → 44.3s (−10.0s) |

**Total unavailable: 192 seconds, 3.2 minutes**, out of roughly 14.5 hours of footage on the share. All five are 2009 or 2010, matching the year-clustering of every other defect found here and consistent with corruption inherited from the pre-ZFS NAS generations.

**Do not delete the NAS sources for those five.** The transcodes hold only part of the footage, and error-tolerant recovery has not been attempted.

### A second false-positive problem, in the deep check itself

The first full deep scan flagged **325 of 2,815** archived videos — 11.5%. **323 of those were one warning**: `Application provided invalid, non monotonic DTS`, attributed to `[null @ ...]`, which is the output muxer that `-f null -` invokes. It describes the verification command, not the file.

A checker that reports 11.5% of a healthy archive as damaged only teaches you to ignore it, which is worse than having no checker. `_is_muxer_noise()` now drops muxer-attributed lines while leaving anything a decoder reports untouched. Re-checking those 325 with the filter: 323 ok, 2 real.

---

## ⚠️ Foreign content on the home-movies share (2026-08-06)

Discovered by inspection, not by any tool: `2010/00066.MTS` previews as **174 MB of MP3 fragments** — 40 LAME encoder tags, ID3 tag 7.4 MB in rather than at offset 0, so it holds *middle chunks* of several different MP3s. Neighbouring files jump mid-playback into completely unrelated footage.

This is a failure class nothing here was checking. `check_media_health.py --deep` sees the symptom and attributes it to codec damage, which points at the wrong remedy: **degraded footage transcodes and salvages; replaced footage is simply gone.** `detect_splices.py` now separates them.

### Detection method

Structural continuity. Every container here is a chain with a predictable next step, and foreign data breaks it in a way random corruption does not. AVCHD `.MTS` holds a `0x47` sync byte every 192 bytes for the whole file, ISOBMFF walks a box chain, JPEG runs marker segments to one End-of-Image, PNG walks chunks to IEND.

Transport streams give the strongest signal, and the trick is **phase**. Blocks lifted from another `.MTS` still hold sync every 192 bytes, just at a different offset within the packet grid, because the splice point does not respect the donor's alignment. Host files here run at phase 4; donor data repeatedly appears at phase 64. That distinguishes another recording's blocks from an MP3's blocks from unstructured data.

### The clustering answers the question that matters

| year | files | with foreign content | rate |
|---|---|---|---|
| 2009 | 23 | 10 | **43.5%** |
| 2010 | 35 | 12 | **34.3%** |
| 2011 | 24 | 0 | 0.0% |
| 2012–2022 | 1,211 | 0 | 0.0% |
| unfoldered | 172 | 2 | 1.2% |

**This is a bounded historical event, not ongoing rot.** Every year from 2011 forward is pristine across 1,235 files. The two unfoldered exceptions sit in `2011 Summer Vacation/New-after reset/` and are numbered `00024` and `00043` — the same range as the 2009/2010 files, so almost certainly the same card and the same era as the folder name suggests.

### Share totals, 1,463 files

| status | count |
|---|---|
| ok | 1,428 |
| entirely foreign — no footage anywhere in the file | **13** |
| spliced — real video, then someone else's data | 11 |
| empty (all 11 in 2014, a separate pre-existing issue) | 11 |

**2.02 GB is definitely not video.** A further 0.28 GB is transport-stream data on a different packet grid, which is genuinely ambiguous: donor blocks, or the recording resuming after a gap. Phase cannot tell those apart, so it is reported separately rather than counted as loss.

### The archive was never contaminated

`Organized_Videos` (2,815 files) and `TO_PROCESS`: **zero findings**, every box chain continuous.

Of the 24 affected sources, **19 were held back** by the conversion pre-screen and 5 were converted — and those 5 are exactly the files already known to have lost footage. Nothing masquerading as a home movie ever reached the archive.

### 13 files whose footage does not exist in this copy

These are not damaged, they are absent. No transcode recovers them, and their reported durations are fiction.

| file | size | content |
|---|---|---|
| `2009/00006.MTS` | 225.6 MB | unidentified compressed data |
| `2010/00037.MTS` | 182.0 MB | MP3 audio |
| `2010/00057.MTS` | 142.6 MB | foreign format |
| `2010/00050.MTS` | 138.8 MB | unidentified compressed data |
| `2009/00026.MTS` | 107.1 MB | foreign format |
| `2010/00033.MTS` | 94.7 MB | MP3 audio (ffprobe: a valid 2,959-second stream) |
| `2010/00041.MTS` | 81.0 MB | MP3 audio |
| `2009/00027.MTS` | 77.5 MB | foreign format |
| `2010/00034.MTS` | 16.1 MB | foreign format |
| `2010/00045.MTS` | 14.1 MB | m4v video, not MPEG-TS |
| `2009/00023.MTS` | 9.1 MB | MP3 audio |
| `2010/00066.MTS` | 174.6 MB | MP3 fragments |
| `2009/00021.MTS` | 3.1 MB | foreign format |

**Action:** if the original AVCHD SD cards or camcorder media still exist, they predate whatever happened here and are the only plausible source of clean copies. Worth checking before the share is retired.

### Why every earlier check passed these

```
00033.MTS → format_name=mp3, codec_type=audio, duration=2959.86
```

ffprobe reports a valid 49-minute audio stream, so "does this decode" answers yes — it is a perfectly intact file of entirely the wrong content. `check_video()` now also reports `not a video` when no video stream is present and `wrong container` when the detected format contradicts the extension.

### The photo library escaped: 9 findings in 35,152 files

All 35,152 archived photos were checked. **One** holds foreign content:

- `_TO_REVIEW_/Family/DSC_4375a.jpg` — a complete, correctly-decoding 1722×2504 image followed by **307 KB that is the tail of a different JPEG**: entropy-coded data with stuffing at 2.18 per KB, no SOI, SOS, DHT or DQT anywhere, terminating in its donor's `FFD9`. The visible photograph is unaffected.

The other 8 carry between 169 KB and 1.6 MB of trailing bytes that are **entirely zeros**. Every one decodes at full resolution, so no image data is lost — 5.4 MB of waste, and worth noting that zeroed blocks are a materially better outcome than cross-linked ones.

Nothing on the photo side shows the 2009/2010 pattern.

---

## ✅ Rescue complete — 6 hours recovered from the 24 damaged sources (2026-08-09)

The originating SD cards are gone from the hard archive, so these damaged NAS copies are the only surviving record. `rescue_damaged_media.py` extracted everything readable. **All 24 sources yielded something; nothing was a total loss.**

| recovered | amount |
|---|---|
| video | 13.5 minutes |
| audio | 348.9 minutes |
| images | 1 |
| **total** | **362.4 minutes across 29 files, 1.08 GB** |

Output is in `_RESCUED/<year>/`, every filename carrying `_DAMAGED`. Nothing was imported into the archive and no source was modified.

### The part that mattered: 6 files nobody had ever rescued

The conversion pre-screen correctly kept damaged files out of the archive, but *held back* had quietly become *forgotten*. These six had no converted form at all:

| file | frames recovered |
|---|---|
| `New-after reset/00024.MTS` | **3,641** |
| `New-after reset/00043.MTS` | 1,273 |
| `2009/00030.MTS` | 1,192 |
| `2009/00003.MTS` | 242 |
| `2009/00010.MTS` | 71 |
| `2010/00042.MTS` | 43 |

**6,462 frames — roughly 3.6 minutes of footage that existed nowhere else.**

### The archive needs no changes

For the five spliced files that *were* converted, the archived copy is equal or better in every case, measured by frame count:

| file | rescued | archived |
|---|---|---|
| `00009` | 875f | 889f |
| `00017` | 1,143f | 1,145f |
| `00039` | 1,298f | 1,298f |
| `00065` | 731f | **942f** |
| `00071` | 1,416f | **1,646f** |

The original conversion did its job. Nothing in `Organized_Videos` should be replaced.

### Two measurement errors worth not repeating

**Cutting at the splice is usually wrong.** The intuition that a clean cut beats letting ffmpeg fight through foreign data is false, and expensively so. On `00071` the prefix cut yielded 15 frames against 1,416 from a whole-file decode — its first splice lands 1 MB in, so nearly all surviving footage sits *after* the damage. But `00030` and `00042` reverse it: whole-file decode produced nothing at all and only the cut worked. Neither dominates, so both are encoded and the better kept. Prefix-cut alone would have recovered 2,957 of the 6,462 new frames.

**Duration is not footage.** A salvaged file keeps the source's timestamps, so recovered frames scatter across the original timeline with gaps. `00003` reports 27.19s while holding 242 frames — an average of 8.9 fps. Ranking by duration rewards the gappiest result, and it produced a false conclusion here: `00017` looked like it beat the archive 47.7s to 41.9s, when by frames the two are identical at 1,143 and 1,145. Selection and reporting now use frame counts.

### Carving found what ffprobe could not

ffprobe only inspects the start of a file, so "no readable stream" means "nothing at the beginning". Forcing a full carve over the thin results:

| file | direct extraction | after carving |
|---|---|---|
| `2010/00057.MTS` | 21s | **938s** (+917s, almost all audio) |
| `2009/00006.MTS` | nothing | 48s of video |
| `2010/00050.MTS` | 70s | 69s (no gain) |

### Deleting the damaged sources is safe, but do it last

The share is `smbfs` to TrueNAS. A client-side delete is an unlink RPC with no visibility into block allocation; ZFS is copy-on-write and refcounted; and the foreign bytes are a *copy* baked into file content when the data was moved off the pre-ZFS generations, not a live reference. The MP3s and videos those bytes came from cannot be fragmented by deleting these files.

**HOWEVER** — deletion destroys the only surviving copy of anything not yet extracted. Review `_RESCUED/` first.

### Imported: 11 files, filed to their real dates (2026-08-09)

Reviewed by hand, then imported. All 11 verified in place and decoding:

| destination | file | recovered |
|---|---|---|
| `2011/07 July` | `20110719_131110_00024_DAMAGED.mp4` | 128.3s |
| `2011/10 October` | `20111001_163041_00043_DAMAGED.mp4` | 44.1s |
| `2011/10 October` | `20111004_215652_00030_DAMAGED.mp4` | 40.1s |
| `2011/10 October` | `20111002_110802_00010_DAMAGED.mp4` | 7.4s |
| `2011/10 October` | `20111006_130705_00042_DAMAGED.mp4` | 2.0s |
| `2010/12 December` | `20101217_175837_00003_DAMAGED.mp4` | 27.2s |
| `2010/03 March` | `20100316_202902_00057_DAMAGED.mp4` | 21.0s |
| `2010/02 February` | `20100212_103904_00045_DAMAGED.mp4` | 122.8s |
| `2010/02 February` | `20100214_152739_00050_DAMAGED.mp4` | 69.6s |
| `2009/12 December` | `20091225_191220_00006_DAMAGED_extracted1.mp4` | 48.2s |
| `2006/05 May` | `20060511_193329_00021_DAMAGED.jpg` | 2560×1920 |

Named capture-date-first, matching the `20091225_202803_CAM.h265.mp4` convention the rest of the archive uses, so they interleave chronologically instead of sorting to the top of the folder. The source reel number is kept after the date for provenance, and `_DAMAGED` stays so a partial recovery is never mistaken for a clean original.

Several were mis-foldered on the NAS — `00003` sat in `2009/` but was recorded 2010-12-17, and four `2009/`-`2010/` files are really 2011.

**Not imported, deliberately:**

- **5 already-archived re-encodes** (`00009`, `00017`, `00039`, `00065`, `00071`). The archived copy is equal or better in every case, and the rescued version carries seconds of foreign footage spliced in.
- **9 MP3s.** The archive has no audio destination and these are not family recordings. To be discarded by hand — deliberately not automated.
- **4 redundant carved siblings.** `00050` and `00057` each produced a direct extraction *and* carved files holding the same footage; only the direct one was imported. `00006` is the exception whose carve is its only output, since direct extraction produced nothing there.

`_RESCUED/` still holds every rescued file and can be cleared once the MP3s are dealt with.

---

## Ready to run

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
