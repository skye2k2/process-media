# Video recovery history — the home-movies conversion, foreign-content discovery, and rescue (2026-08)

Extracted verbatim from NEXT.md on 2026-10-23, when that file was returned to its forward-looking-only contract. This is the complete record of the August 2026 video handling effort: the AVCHD conversion and its verification, the foreign-content discovery on the home-movies share, and the damage rescue. The CHANGELOG holds the version-by-version decisions; this file holds the findings, tables, and measurements in one place.

**Still-live warnings from this record** (also tracked in NEXT.md): do not delete the NAS sources for the five short-output conversions; the 13 entirely-foreign files' footage exists only on the original SD cards if those still exist; `_RESCUED/` holds everything recovered and can be cleared only after the 9 MP3s are hand-discarded.

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
