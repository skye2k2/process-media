# process-media CHANGELOG

---

## v21 — 2026-08-09 — "Promotion and cleanup"

Two temporary scripts earned permanent homes; 5.4 GB of scaffolding did not.

<details>

### Promoted

**`verify_conversions.py`** — verifies a conversion batch did not degrade the archive. Tier 1 checks duration, resolution, frame count, audio and decodability on every pair; tier 2 measures SSIM and PSNR on a sample taken evenly across the size range, because degradation concentrates in the busiest footage and a random sample is mostly short simple clips. Pairs come from the conversion index, never from filenames.

Promoting it surfaced two defects the throwaway version had been carrying.

`analyze_video_quality` disagrees with itself about its own return key: `calculate_ssim` gives `{'all': ...}` and `calculate_psnr` gives `{'average': ...}`. Reading `'all'` for both *appears* to work, because SSIM answers and PSNR silently returns `None` — which is what earlier made a verification report PSNR as unavailable against a perfectly healthy tool.

And 12 of 646 home-movies outputs reported as **missing**. They were not: `create_event_folders.py` had relocated them into named event subfolders after import, leaving the conversion index pointing at paths that no longer existed. A tool reporting a dozen phantom failures on every run is one nobody reads, so outputs are now resolved by filename when the recorded path is gone — and refuses to guess when a name is ambiguous. With that fixed, the batch verifies **641 ok, 5 mismatched**, the five being the known damaged sources.

**`attribute_splices.py`** — turns findings into decisions. Clustering by year separates a bounded historical event from ongoing rot, and the archive-impact join answers whether the archive is contaminated or merely incomplete. Both were the analyses that made the splice findings actionable, and the `photosync` and `videos` shares are still unscanned.

### Removed

52 items, **5.4 GB**, dominated by `.TMP_all_similars` at 5.0 GB — the exported comparison set from the SSIM calibration session, whose conclusion now lives as the 0.92 keeper floor in `duplicate_detector.py`.

Also gone: the splice investigation scaffolding superseded by `detect_splices.py`; the one-off repairs for rescue dates and naming, now done natively by `rescue_damaged_media.py`, where keeping them would only invite a destructive re-run; and the dedupe diagnostics whose findings survive as regression tests.

Two deleted with prejudice: `probe_duration_overlap` and `probe_home_movies_overlap`. That method produced the 94.3% overlap figure that was completely wrong, and leaving them invites someone to trust them again.

Two kept, still blocked on open work: the `-edited` pair analyses, since NEXT.md's 898-file ruling remains unimplemented.

### Added `_records/`

`detect_splices.py` output for the home-movies share, preserved because it stops being reproducible the moment the damaged sources are deleted — it is the only per-file record of what was wrong with each one. Everything else this project produces is derived and regenerable; this is not.

### Also in this cycle

The rescued files were imported and then reviewed by hand, which produced the naming correction in the previous entry. The archive now also holds several deliberately-duplicated recoveries: the excluded re-encodes were copied in on purpose, to be resolved during a manual per-video review rather than by tooling.

- **Tests** — 248 to 256

</details>

---

## v20 — 2026-08-09 — "Damaged-media rescue"

Six hours of content pulled out of the 24 sources holding foreign data, after confirming the originating SD cards are gone from the hard archive and these damaged copies are the only surviving record.

<details>

### What was recovered

All 24 sources yielded something. Nothing was a total loss.

| | amount |
|---|---|
| video | 13.5 minutes |
| audio | 348.9 minutes |
| images | 1 |
| **total** | **362.4 minutes across 29 files, 1.08 GB** |

The part that mattered is six spliced files nobody had ever rescued. The conversion pre-screen correctly kept them out of the archive during the original run, but "held back" had quietly become "forgotten", and they had no converted form at all — `00024` alone gave back 3,641 frames, and the six together **6,462 frames of footage that existed nowhere else**.

For the five spliced files that *were* converted, the archived copy turns out to be equal or better in every case, so nothing in `Organized_Videos` needs replacing.

### Three strategies, because none of them dominates

| situation | approach |
|---|---|
| spliced | encode the valid prefix **and** the whole file, keep whichever holds more frames |
| foreign | extract whatever the file actually holds, as its own type |
| unreadable | carve region by region |

### The assumption that cost the most

Cutting a spliced file at its first splice and encoding only the clean prefix seemed obviously right: why make ffmpeg fight through foreign data? It is wrong, and wrong in the direction that discards footage. Valid video *resumes* after the first foreign region — the phase-shifted stretches `detect_splices.py` deliberately refuses to count as lost are, at least partly, the recording continuing.

On `00071` the prefix cut yielded **15 frames** against **1,416** from a whole-file decode, because its first splice lands 1 MB into a 210 MB file.

But the reverse happens too: on `00030` and `00042` the whole-file decode produced *nothing at all* and only the cut worked. So both are encoded and the better kept. Had the first approach run to completion unchallenged it would have recovered 2,957 of the 6,462 new frames and called it done.

### Duration is not footage

A salvaged file keeps the source's timestamps, so recovered frames scatter across the original timeline with gaps where the damage was. `00003` reports 27.19 seconds while holding 242 frames — an average of 8.9 fps.

This produced a wrong conclusion before it was caught: `00017` appeared to beat its archived copy 47.7s to 41.9s, suggesting the error-tolerant decode flags were recovering material the original conversion missed. By frame count the two are identical, 1,143 against 1,145. The extra seconds were gaps. Selection between rescue candidates and all reporting now use frame counts.

### Carving beats ffprobe on files ffprobe cannot open

ffprobe inspects only the start of a file, so "no readable stream" means "nothing at the beginning" — the same shape of error that let an MP3 pass as a healthy home movie in v19.

| file | direct extraction | after carving |
|---|---|---|
| `2010/00057.MTS` | 21s | **938s** (+917s, almost all audio) |
| `2009/00006.MTS` | nothing | 48s of video |
| `2010/00050.MTS` | 70s | 69s (no gain) |

Carving maps a file megabyte by megabyte into `ts`, `mp3`, `jpeg` or `unknown` regions, trims transport-stream fragments to a packet boundary so ffmpeg will accept them, and validates every carved JPEG by decoding it. Regions that produce nothing decodable are deleted rather than left behind — one of `00057`'s two MP3 regions failed that check and was discarded.

### Deleting the damaged sources is safe

The share is `smbfs` to TrueNAS. A client-side delete is an unlink RPC with no visibility into block allocation; ZFS is copy-on-write and refcounted; and the foreign bytes are a copy baked into file content when the data moved off the pre-ZFS generations, not a live reference. The files those bytes came from cannot be fragmented by deleting these. The real risk is different: deletion destroys the only surviving copy of anything not yet extracted.

### Import preflight, and what it caught

Inspecting one rescued file by hand showed it was mostly a re-encode of footage already archived, plus a couple of seconds of snippets from other recordings. Checking what an import would really do found all 29 rescued files were problems, and none of it was visible to `--dry-run`.

`preflight_import.py` predicts the outcome using the organizer's own `get_creation_date()`, `get_destination_folder()` and `compute_destination_filename()`, so the prediction cannot drift from behavior.

| failure | effect |
|---|---|
| dates | a rescue is a fresh encode with no capture metadata, so mtime dated 2009 recordings to the day they were rescued — all 29 into one 2026 folder |
| routing | `is_video_file()` says an mp3 is not a video, so 5.8 hours of recovered audio would enter `Organized_Photos` |
| redundancy | the duplicate detector cleared every one, because a re-encode shares no bytes with the archived copy of the same footage |

The redundancy case is the dangerous one and no heuristic finds it. It is knowable only from provenance: the conversion index records which source produced which archived file, the rescue manifest records which source produced which rescued file, and joining them makes it exact. Five rescues are correctly blocked.

Building it exposed two defects in the rescue tool. Outputs carried no capture date — now stamped from the source, recovering a real date for all 24. And the manifest was overwritten by each of the three rescue passes rather than merged, leaving only the last, which silently disabled the provenance check.

A further check came out of importing: several outputs rescued from one source are often the same footage extracted two ways. `00050` produced a direct extraction of 2,065 frames beside two carved files holding 2,007 between them; importing all three would have filed one clip as three. A warning rather than a blocker, since `00006`'s carve is its only output.

### Imported

11 files, filed to their recovered dates and verified in place — 511 seconds of video and one 2560×1920 photograph, spanning 2006 to 2011. Several were mis-foldered on the NAS: `00003` sat in `2009/` but was recorded 2010-12-17.

Not imported: the 5 already-archived re-encodes, the 9 MP3s (no audio destination, and to be discarded by hand rather than by any automated rule), and 4 redundant carved siblings.

### Naming, corrected after reviewing the imported batch

Two problems, both visible only once the files sat beside real footage.

The archive is ordered by date -- neighbouring files are named `20091225_202803_CAM.h265.mp4` -- so `00006_DAMAGED_carved1.mp4` sorted to the top of its folder and broke the chronology the folder exists to express. Rescued files now lead with the capture date, keep the source stem for provenance, and keep `_DAMAGED`:

    20091225_191220_00006_DAMAGED_extracted1.mp4

The suffix is now `_extracted` rather than `_carved`, describing the result instead of the technique, so one word covers a whole-file decode, a prefix cut and a region carve alike.

And the numbering was wrong. It ran over regions *found*, so a region that failed validation burned its number permanently: `00057` shipped as `carved2`, `carved3` and `carved4` with **no `carved1`**, because its first region did not decode and was deleted. Numbering now follows the outputs that survive, which also answers what the sequence is for -- `00050` legitimately has `extracted1` and `extracted2`, and a source with one output simply has no suffix at all.

40 files renamed in place across `_RESCUED/` and the archive, and the rescued clips now interleave chronologically: `20091225_191220_00006_DAMAGED_extracted1.mp4` sits before the 20:12 clip rather than above the whole folder.

### Changed

- **`preflight_import.py`** (new) — `--manifest`, `--verbose`; exits non-zero on blockers
- **`rescue_damaged_media.py`** (new) — `--dry-run`, `--only`, `--force-carve`. Output to `_RESCUED/<year>/` with `_DAMAGED` in every filename so a partial recovery cannot be mistaken for a clean original. Encoder settings match `camcorder_convert.py`. Sources are never modified and nothing is imported
- **Tests** — 222 to 248

</details>

---

## v19 — 2026-08-06 — "Foreign content detection"

A failure class nothing here was checking: files containing data that belongs to *other* files. Found by eye, not by tooling — previewing `2010/00066.MTS` produced 174 MB of MP3 snippets, and neighbouring videos jump mid-playback into unrelated footage.

<details>

### Why the existing checks could not see it

`check_media_health.py --deep` observes the symptom and attributes it to codec damage, which points at the wrong remedy. The distinction is the whole point:

| | meaning | remedy |
|---|---|---|
| codec damage | footage degraded but present | transcode salvages what it can |
| foreign content | footage **replaced** by unrelated bytes | none. It is gone, and the reported duration is fiction |

Worse, the cheap container check passed the most extreme cases outright. `2010/00033.MTS` is 94 MB of MP3 audio, and ffprobe describes it as a valid 2,959-second stream — so "does this decode" answers yes, beautifully. It is a perfectly intact file of entirely the wrong content.

### Detection: structural continuity

Every container here is a chain with a predictable next step, and foreign data breaks it in a way random corruption does not. AVCHD `.MTS` holds a `0x47` sync byte every 192 bytes for the whole file; ISOBMFF walks a box chain; JPEG runs marker segments to one End-of-Image; PNG walks length-prefixed chunks to IEND.

Transport streams give the strongest signal, and the useful trick is **phase**. Blocks lifted from another `.MTS` still hold sync every 192 bytes, just at a different offset within the packet grid, because the splice point does not respect the donor's alignment. Host files here run at phase 4 and donor data repeatedly appears at phase 64 — which separates another recording's blocks from an MP3's blocks from unstructured data.

Sampling makes it cheap: 64 KB read per megabyte detects any foreign region above ~1 MB, and every case found spans 20–140 MB. The whole 130 GB share scanned in **123 seconds** versus 4,406 for the deep decode. `--full` disables sampling.

### Three states, not two

Reporting "good or foreign" gets the accounting wrong in both directions, so windows are classified as aligned, **phase-shifted**, or foreign. Only the last supports a confident claim that footage is gone.

An earlier revision counted phase-shifted data as lost and reported `2010/00071.MTS` as **99.5% destroyed**; the honest figure is 64.6%, which matches ffmpeg independently recovering 54% of its duration. Phase cannot distinguish a donor's blocks from this recording resuming after a gap — resumed data has no reason to land back on the original grid — so pretending otherwise overstates the damage in the one direction that would get files thrown away.

### What the scan found

**`/Volumes/home-movies`, 1,463 files:** 1,428 ok, 13 entirely foreign, 11 spliced, 11 empty. 2.02 GB is definitely not video; a further 0.28 GB is ambiguous phase-shifted data.

The clustering settles the question that actually matters:

| year | files | with foreign content | rate |
|---|---|---|---|
| 2009 | 23 | 10 | **43.5%** |
| 2010 | 35 | 12 | **34.3%** |
| 2011 | 24 | 0 | 0.0% |
| 2012–2022 | 1,211 | 0 | 0.0% |
| unfoldered | 172 | 2 | 1.2% |

**A bounded historical event, not ongoing rot.** Every year from 2011 forward is pristine across 1,235 files. The two unfoldered exceptions live in `2011 Summer Vacation/New-after reset/` numbered `00024` and `00043` — the same range as the 2009/2010 files, so the same card and era the folder name implies.

**The archive was never contaminated.** `Organized_Videos` (2,815 files) and `TO_PROCESS`: zero findings, every box chain continuous. Of the 24 affected sources, 19 were held back by the conversion pre-screen, and the 5 that converted are exactly the files already known to have lost footage.

**13 sources contain no footage whatsoever** — absent, not damaged, totalling 1.1 GB of filenames with nothing behind them. If the original AVCHD cards still exist they predate this and are the only plausible clean copies.

**35,152 photos, 9 findings.** One holds foreign content: `DSC_4375a.jpg` carries 307 KB that is the tail of a different JPEG — entropy data with stuffing at 2.18 per KB, no SOI/SOS/DHT/DQT, ending in its donor's `FFD9`. The visible image decodes correctly. The other 8 carry 169 KB–1.6 MB of trailing **zeros** and all decode at full resolution; zeroed blocks are a materially better outcome than cross-linked ones.

### The mechanism is not established

The expectation was allocation-boundary alignment, which would have proven filesystem block cross-linking. Measured honestly as a range against the uncertainty of one 192-byte packet, the splices land 68, 132, 4, and 316 bytes off the nearest boundary — inconsistent. The first attempt appeared to show clean 1 MB alignment, but that was an artifact of using 1 MB windows, and the second appeared to show none, because the packet walk can only return offsets on the host's own grid. So: proven that these files contain other files' data, not proven how.

### False positives, which were the real engineering risk

A checker that cries wolf is worse than no checker, and this one nearly did three times over.

**3,950 of the first 3,959 photo findings were vendor metadata.** Phone cameras deliberately append data after End-of-Image: 2,036 Samsung Extended Format trailers (`SEFH`, `Image_UTC_Data`) and 1,914 Motorola camera-settings blocks (`<camera>appversion=...`). Both are now allowlisted, alongside the motion-photo and MPO cases anticipated from the start.

**A JPEG marker-walk bug invented corruption.** A run of `0xFF` is legal fill before a marker, not a marker itself. Breaking on it derailed the walk on every JPEG using restart intervals: four archived scans reported "no end marker" despite decoding perfectly and ending in `FFD9`, and one file reported 307 KB of trailing data fabricated from its own image data. Fixed by skipping fill bytes inside the entropy-coded scan.

**Twenty "another transport stream" verdicts came from 98-byte buffers.** Over a buffer shorter than a few dozen packets, `range(phase, 98, 192)` yields one position, so a single chance `0x47` scores a perfect 1.000 sync ratio. The phase test now requires at least 32 packets of data.

### Changed

- **`detect_splices.py`** (new) — handlers for MPEG-TS, ISOBMFF, JPEG and PNG; `--output`, `--workers`, `--full`
- **`check_media_health.py`** — `check_video()` now reports `not a video` when no video stream is present and `wrong container` when the detected format contradicts the extension. Closes the gap that passed 13 files holding no footage
- **Tests** — 199 to 222

</details>

---

## v18 — 2026-07-31 — "Documentation restructure"

Four documents, each with one job, after the project's notes had grown to the point where finding an answer meant reading past it.

<details>

### The problem

`README.md` had reached 1,013 lines documenting nine tools at equal depth, which buried the five workflows that are the intended way to use any of it. `NEXT.md` had reached 955 lines, most of it resolved issues still carrying their full investigation notes, superseded rulings kept beside their replacements, and remediation advice for things already remediated. Neither could answer a question without the reader wading.

### The split

| file | lines | job |
|---|---|---|
| `README.md` | 214 | how to run the five workflows |
| `SCRIPTS.md` | 473 | what each of the 29 scripts does |
| `NEXT.md` | 114 | what is left to do |
| `CHANGELOG.md` | — | permanent record of what changed and why |

`README.md` now has one section per workflow — Takeout import, archive import, video conversion, review and prune, reprocessing — each with its flags, what it decides and why, and the failure modes worth knowing. The two rules that cost the most time are hoisted above Setup: use the venv interpreter, and stage a copy before importing from an archive.

`SCRIPTS.md` is new, and itemizes every script in six groups: workflow orchestrators, processing engines, analysis, verification and diagnostics, repair and cleanup, shared libraries, and tests.

### Documentation bugs fixed, not just prose tidied

**Sixty-two of sixty-three examples invoked bare `python3`** while the Setup section insisted on `.venv/bin/python`. That contradiction is precisely the trap that silently disabled the review workflow for months — the README was actively teaching the thing that broke it. Only `python3 -m venv` still uses the system interpreter, since it is needed to create the environment.

`check_media_health.py` and `removal_history.py` had **no documentation at all** despite both being in active use.

A stale "Ran 75 tests" became 196.

### The hand-written TODO list, reconciled

The scratch notes kept at the end of the README were checked item by item against what shipped. **Eight of fifteen were already resolved**: identical-duplicate detection (BUG-3 and BUG-6), the microsecond and shared-folder keeper bug (BUG-1), resolution comparison and the same-resolution ruling (BUG-2 and CONCERN-7), the Nikon DSCN work, the missing home movies, whether the PhotoSync originals are genuinely better, the combined cache/recache/rebrowse command, and in-place NAS processing.

**Seven remain, and were measured rather than restated.** Shared Takeout cleanup is 11 comma-named folders holding 53 orphaned sidecars. The "hundreds of `-edited` files" is 898. The wanted real-file test corpus is half-met, since 196 synthetic tests exist but no integration corpus of genuine oddities. Plus the DVD, tags for best-of and people, Google Photos cloud reconciliation, and the NAS sync strategy.

### Hard-wrapping removed

Every Markdown file had been hard-wrapped at roughly 90 columns, contrary to a standing instruction — editors word-wrap, so manual wrapping only adds noise and makes diffs harder to read. Unwrapped across all five files, dropping 562 lines without losing a word; `CHANGELOG.md` alone shed 424.

Done with a script that refused to write unless whitespace-normalized content matched exactly before and after. That guard fired on two files and was itself wrong: collapsing a multi-line blockquote legitimately removes redundant `>` prefixes, so the comparison strips quote markers rather than counting them as content.

### Verified rather than assumed

Every `.py` file is reachable from one of the two documents. Every cross-reference anchor in both resolves to a real heading. Code fences stay balanced, table-row and heading counts are unchanged, and the only remaining adjacent prose lines are numbered list items.

One genuine loss was caught and undone. The first README rewrite replaced the file wholesale and dropped reference material worth keeping: the SSIM and PSNR interpretation tables, CRF comparison mode, frame extraction, the worked DVD-rip example, the converted-versus-skipped codec table, edited-pair detection, archive performance notes, and 147 lines of naming and placement rules. All recovered from git and folded into `SCRIPTS.md`, with naming and placement promoted to its own section since it applies to every import path.

</details>

---

## v17 — 2026-07-31 — "Reconciler video awareness and cache reuse"

Small-item cleanup while the home-movies conversion ran.

<details>

### BUG-7: the reconciler was blind to videos

`reconcile_nikon_archive.py` indexed only `Organized_Photos`, which broke it two ways. Every video was reported as `NEW_CONTENT` — on the Nikon archive that was **11 of 11** reported-new files, a 100% false-positive rate on the tool's only actionable output — and the destination it predicted for a video named the photo root, which the importer would never use. Acting on that advice would have re-imported 11 original AVIs beside the H.265 transcodes that already existed.

Both symptoms share one cause: a transcode shares no bytes with its source, so MD5 cannot see it, while the naming convention preserves the original stem (`DSCN3019.AVI` → `20131004_161529_DSCN3019_S3100.h265.mp4`).

Added `build_archive_stem_index()` across both roots, `find_transcoded_match()`, a `TRANSCODED_MATCH` category, `is_video_source()`, and video-aware destination routing.

Matching is deliberately narrow: whole tokens rather than substrings, so `DSCN301` does not match `DSCN3019`, and stems under four characters are refused since `001` would match half the archive. Tokenizing splits on dots as well as underscores, because a compound extension leaves part of itself in the stem — `Path("x.h265.mp4").stem` keeps `.h265` — so a stem sitting last would otherwise never match. That gap was found by a test whose own expectation was initially wrong.

**Verified against the live archive: 11 of 11 resolve to their transcodes**, and a genuinely new video routes to `Organized_Videos`.

### CONCERN-6: the reconciler ignored the MD5 cache

It hashed all 35,000 archived files from cold on every run — 155 seconds of pure re-reading — using its own private MD5 implementation while ignoring the digests already sitting in the `.analysis_cache.json` files that photo triage and the duplicate detector both populate. Now reuses them through `cached_archive_md5()` and persists what it computes. Source-side hashing stays uncached, since source trees are frequently mounted shares that must not be written to.

### README CRF drift — three inconsistencies, not one

The Encoding Settings table claimed CRF 20 while `camcorder_convert.py` uses 26. Beyond that, `convert_legacy.py` carried the comment "match camcorder_convert.py" beside `CRF = 20`, which was simply false.

Documented the real values for both tools and corrected the misleading comment. Deliberately did **not** change `convert_legacy`'s value: the camcorder default was raised after 20 produced bloated output and the same reasoning probably applies, but altering it changes the quality and size of every future legacy conversion, which is a decision rather than a cleanup. Flagged in both the README and the code for a ruling.

### Also resolved earlier but never recorded by name

- **CONCERN-4 (no test infrastructure)** — resolved in v10, which committed the previously-uncommitted `test_core.py`. The suite now stands at 196 tests.
- **CONCERN-5** — was itself mistaken; it described an O(index) scan on a function with no call sites. Investigating it uncovered BUG-6, fixed in v12.

### Tests — 184 → 196

`TestReconcilerVideoAwareness` covers video detection across AVCHD and standard formats, transcode matching including the last-token compound-extension case, the refusal of short and partial stems, stem indexing across both roots, and destination routing for videos, photos, and the video-root-omitted fallback.

</details>

---

## v16 — 2026-07-31 — "Integrity gates and archive-safe defaults"

Preparation for ingesting three remaining source trees. The theme is that defaults which are correct for a local staging directory become destructive when pointed at an archive, and that nothing was verifying files are actually intact.

<details>

### Archive-safe defaults

Two workflows had defaults tuned for `TO_PROCESS/`, where the source is a disposable copy:

- **`camcorder_convert.py` deletes each original after converting it**, and `keep_originals` defaults to False. Pointed at the NAS home-movies share that would have deleted 675 original MTS files, 94 GB, currently the only copy. `is_staging_path()` now refuses deletion when the source lies outside a `TO_PROCESS` directory, so the flag is no longer the only safeguard.
- **`organize_archive.py` moves files**, so a live run against a share removes them. Mitigated procedurally for the first home-movies batch by staging a copy; the 21 imported files left all 21 NAS originals in place.

### `--avchd-only`, and the duplicate transcode it prevents

`scan_video_files()` collects every video extension. Pointed at the home-movies share it queued **1,368 files and 113 GB** rather than the expected 675 and 94 GB. The extra 679 were MP4s, **673 of which were already in `Organized_Videos`** — imported by `organize_archive.py`, which does not write to the conversion index, so the camcorder workflow could not tell they were present and would have written H.265 duplicates alongside them.

Scoping to AVCHD gives 669 files and 86.68 GB, with 53 correctly skipped as already indexed — matching an independently measured overlap figure exactly.

### Damage detection, and refusing to import it

`check_media_health.py` gained real coverage:

- **HEIC**: the first run reported 103 archived files as unreadable, every one a HEIC, because PIL was never given the HEIF opener. All were fine. Now registered, and HEIC reports `not_checked` rather than "damaged" when pillow-heif is genuinely absent.
- **AVCHD**: 741 of 1,465 files on the home-movies share were going unvalidated — 750 MTS clips nobody had checked. `.mts` is deliberately outside `VIDEO_EXTENSIONS` because the camcorder workflow owns its routing, but integrity still needs testing. Now reuses the existing `AVCHD_EXTENSIONS` constant.
- **Documents**: added ZIP-family CRC verification (`.docx`, `.xlsx`, `.pptx`, OpenDocument, `.epub`) and a PDF `%%EOF` check. The ZIP check is the strongest verification in the project — ZIP stores a CRC32 per member, so damage is proven rather than inferred. It also works on exactly the corruption a ZFS scrub cannot see, since this data crossed two pre-ZFS NAS generations.

Both import paths now refuse damaged sources: `organize_archive.py` quarantines them before the move, and `camcorder_convert.py` pre-screens before spending an encode. `duration_is_plausible()` additionally rejects corrupt timing metadata — one real file reports 66,315 seconds (18.4 hours) for 142 MB while only 610 frames decode, which would have produced a run-away encode.

### Mid-run share loss no longer reads as "everything is new"

Undocking dropped the SMB share partway through a dry-run. Every remaining file became unreadable, `find_duplicate()` reported "source does not exist", and **4,114 files flipped from skip to import** while the run reported success. An unreadable source is now an error, and the loose-file loop aborts if the input root vanishes.

### Review reports are findable again

Reports moved from `_TO_REVIEW_/.TMP_*.html` to the archive root as `_review_issues.html` and `_browse_all.html`. A `.TMP_` prefix marks a disposable artifact, which is wrong for a document worked from for hours, and the leading dot hid it from Finder. The archive root is also where they historically lived, so regenerating now replaces the stale copy — the March pair had sat there for months with links into paths the event-folder reorganization had already invalidated.

### Measured, not estimated

- **PhotoSync**: 649 of 8,609 would import, down from 4,466 before the v15 gates. 3,638 skipped by the recompression gate, 229 by removal history.
- **Health**: local archive clean (35,210 photos, 0 damaged). PhotoSync 4 damaged of 8,631; home-movies 19 of 1,465, **all MTS, all in 2009, 2010 or 2014** — clustering that looks like inherited corruption rather than random rot. Two are structurally scrambled rather than truncated, which an interrupted write cannot produce.
- **home-movies overlap**: 94% of non-AVCHD already archived, but only 7% of AVCHD. Confirmed by two independent methods agreeing exactly (53 archived, 675 new, 11 undated).

The 7% looks wrong against 462 already-converted videos, and the explanation is that **camcorder filenames recycle per card** — every card restarts at `00000.MTS`, so a shared name means nothing. Measured directly: NAS `00003.MTS` is **185,382,912 bytes** while the conversion index records `00003.MTS` at **49,336,320 bytes** — same name, unrelated footage. This is why `conversion_index.py` keys on date and size rather than name, as its own docstring states.

So the 462 converted videos are not 462 recordings from this share. They came from `TO_PROCESS/CAMCORDER BACKUPS/Camcorder 2013/Z First Year/`, and only 53 correspond to NAS footage — every confirmed match sits in `2013/105/`, a single card. The other 409 are footage absent from this share entirely.
- **Throughput**: derived from the index's own `converted_at` timestamps rather than guessed.

### Rejected approaches, recorded so they are not retried

- **Perceptual hashing to verify a duplicate match.** Across 500 real skip decisions, true duplicates scored a pHash distance of 0 every time while mispaired burst frames scored 0 to 16 — one at exactly 0 with an SSIM of 0.7597. Burst frames are the same scene, which is what pHash is built to call identical.
- **Duration matching for video overlap.** Reported 94.3% already archived and was completely wrong: with 2,169 archived videos at ±1.5 s, a 2009 camcorder clip "matched" a 2018 phone video and two clips matched the same file.
- **mtime as a date source in general** (88% agreement) — though for the 11 undated AVCHD it is trustworthy, since every derived date matches its folder year.

### Corrections to earlier claims in this project's own notes

- The "residual BUG-8 false skips" were **damaged files**, not detection failures. Three of five appear verbatim in the truncated list. True residual rate ~0.03%.
- The undated-AVCHD repair step was **unnecessary**: `get_creation_date()` already falls back to mtime, and the probe that found the "gap" skipped that wrapper.
- Prevalence figures were wrong twice — once by counting crops as recompressions, once because a sampling loop exited at its limit, making "40 of 1,180" a stop-at-N artifact rather than a rate.

### Tests — 126 → 184

New sections cover the recompression keeper gate, removal history normalization (weighted toward the over-stripping failure that would have blocked every import), the source-liveness guard, damaged-source quarantine, media health checks including a HEIF-registration regression guard, and the staging-path and duration-plausibility decisions.

</details>

---

## v15 — 2026-07-31 — "Keeper gate, removal history, health checks"

Three additions, all aimed at not losing or duplicating data during the remaining imports.

<details>

### The 0.92 SSIM keeper gate (implements the CONCERN-7 ruling)

`find_duplicate()`'s size gate is 20% wide, but Google's storage-saver recompressions are 1.2x to 8x smaller at identical pixel dimensions. Nothing claimed them, so they were reported as new: **3,725 of 4,403** photos in the PhotoSync dry-run. Importing would have duplicated thousands of photographs already archived, event-filed and reviewed.

For a photo candidate whose size gate fails, dimensions are now compared from the header first — a crop or resize is a different asset and must not be confused for a recompression — and only on an exact dimension match is SSIM computed. At or above `SAME_PHOTO_SSIM_THRESHOLD` (0.92, calibrated by eye against a re-encoding ladder) the two are one photograph and the **archived copy is kept**.

Deviation worth flagging: the ruling as stated was "the smaller wins". This keeps the *archived* copy instead. In this data they are the same file — the archived copy is always the smaller one — and where they would differ, rewriting an organized, event-filed, already-reviewed file to reclaim a few hundred kilobytes is not worth the disturbance.

Undecidable cases fail toward importing: if SSIM cannot be computed, the file is treated as new. A duplicate is recoverable; a discarded original is not.

Verdicts are cached in `.ssim_cache.json`, keyed by both paths plus each file's mtime and size, because each one costs decoding two 12-megapixel images.

**Verified** against 300 real pairs held locally: 299 agreed with their recorded SSIM verdict, and the single disagreement was a rounding artifact — a filename recording `0.9200` for a live value of `0.9197`, correctly below threshold.

### removal_history.py — do not resurrect what was deliberately deleted

Each manual review exports a shell script of files to remove. Nothing consulted them, so re-importing an older source tree would restore rejected files and cost the same review attention a second time.

`RemovalHistory.from_directory()` reads every `*remove*.sh` in `Organized_Photos/` and answers `was_removed(filename)`. Matching is by **name, not location**, because the organizing scripts move files freely. Both quoting styles are parsed: `rm "path"` from the older exports and `rm 'path'` with `'\''` escaping from those generated after the shell-injection fix.

Currently loads **2,529 unique names** from 2,621 entries across three scripts.

Names are normalized so a photo removed under its archived name is recognized when it arrives under its source name — `DSCN1234_S3500_Clif_2.JPG` and `DSCN1234.JPG` share a key. `-edited` is preserved, since an edited variant is a separate asset.

**A dangerous bug was caught here before it shipped.** The first normalizer used `_\d+$` for the collision counter, which chewed through timestamps: `IMG_20240101_120000_Nicole.jpg` reduced to `img`. Every date-stamped file would have collapsed onto one key and the entire import would have been blocked. The counter is now capped at two digits, stripping is bounded to three passes, and any strip that would remove a `YYYYMMDD_HHMMSS` group is refused outright. The collapse rate fell from 1,641-of-2,621 to 92, which is genuine cross-script overlap.

Wired into `organize_archive.py` ahead of duplicate detection — a file a human rejected should not even be compared. `--ignore-removal-history` overrides it.

### check_media_health.py — detect damaged files, not just misplaced ones

Nothing verified that files are intact. A truncated JPEG was found in the PhotoSync archive by accident: it reported its dimensions happily and passed every existing check, while missing its final 17 bytes including the End-of-Image marker. Confirmed structurally — a healthy file there ends `3f ff d9`, that one ends `29 ed`.

Images are **fully decoded** rather than header-read, since dimensions live in the first few hundred bytes and a file missing most of its scan data still reports a size. Videos are probed with ffprobe, inspecting stderr rather than trusting a zero exit. Zero-byte files are flagged separately. Threaded, since the work is I/O bound and often across a network share.

Statuses: `ok`, `truncated`, `empty`, `unreadable`, `suspect`, `not_checked`. Exits non-zero when anything is damaged, so a wrapper can react.

Verified against deliberately damaged copies: truncated, empty, and non-image files were each correctly categorised, with the intact control passing.

### Tests — 133 → 153

- `TestRecompressionKeeperGate` (7): heavy recompression recognized, a different photograph at identical dimensions still imported, dimension mismatch short-circuiting before any decode, the fast path untouched when sizes agree, verdict caching and reload, a burst conflict still overriding the gate, and the threshold constant actually being honoured. The fixture quality pair was chosen by measurement — white noise was tried first and rejected because JPEG destroys it, giving an unrepresentative SSIM of 0.77.
- `TestNormalizeMediaName` (11) and `TestRemovalHistory` (9): weighted toward the over-stripping failure mode, including an explicit regression guard that a timestamp is never removed and that distinct timestamps never share a key.

</details>

---

## v14 — 2026-07-30 — "BUG-8: burst frames were skipped as duplicates"

The importer silently discarded distinct photographs. Measured at 2.8% of all skip decisions; now 0%.

<details>

### BUG-8: sub-second frames collapsed onto one date pattern

`extract_date_pattern()` resolves only to `YYYYMMDD_HHMMSS`, which is what lets it match across naming conventions. Two mechanisms defeat that resolution:

1. **Milliseconds are discarded.** `IMG_20210616_120804026.jpg` and `IMG_20210616_120804916_Nicole.jpg` are different photographs from the same second, but both reduce to `20210616_120804`.
2. **Burst frames share everything but the index.** `..._190213263_BURST000_COVER_TOP.jpg` and `..._190213263_BURST001_Nicole.jpg` match down to the millisecond.

`find_duplicate()` then accepted the first candidate whose size fell within `size_tolerance` (20%). Burst frames of one scene compress to nearly identical sizes — several were reported as "exact size" — so the gate passed and the source was skipped.

Measured on 600 PhotoSync files the importer would skip: **583 genuine duplicates, 17 (2.8%) matched the WRONG photograph**, SSIM from 0.2244 to 0.7999. The archive holds 562 date patterns mapping to more than one file, each an opportunity for the mispairing. At that rate the PhotoSync import alone would have dropped roughly 200 distinct photographs.

### Perceptual hashing was measured and REJECTED

The obvious fix — verify a name-and-size match with a pHash comparison — does not work, and the measurement is worth keeping so nobody tries it again. Across 500 real skip decisions:

| population | pHash hamming distance |
|---|---|
| Same photograph (SSIM ≥ 0.90), n=487 | min 0, p50 0, **max 0** |
| Different photograph (SSIM < 0.90), n=13 | **min 0**, p50 4, max 16 |

There is no separating threshold: one mispairing scored distance **0** at an SSIM of 0.7597. Burst frames are the same scene, which is exactly what a perceptual hash is built to call identical. It cannot distinguish "same scene, a moment later."

### Fix: filename frame discriminators

New in `duplicate_detector.py`:

- `extract_frame_signature(filename)` — pulls the millisecond field (three digits immediately after `HHMMSS`) and the burst index (digits after `_BURST`), as ints so padding differences compare equal.
- `frame_signatures_conflict(name_a, name_b)` — true only when a field is present in **both** names and differs. Absence never counts as a conflict, which keeps the check purely additive: it can prevent a false match but never cause one.

`find_duplicate()` rejects any candidate that conflicts, before the size gate.

Also closed a related gap: when the date pattern matched but nothing was accepted — including the new case where every candidate was rejected as a different frame — the result now falls through to a content-hash check. Byte equality settles identity regardless of what filenames imply, so a file whose name conflicts but whose bytes match is still recognized rather than re-imported.

### Verified

Re-running the same 600-file check after the fix: **600 genuine duplicates, 0 matched the wrong photo.** The true-positive rate did not regress.

Note this never affected the Nikon archive: those 4,491 files matched byte-identically via the v12 content-hash path, which cannot mispair.

The same logic governed every previous import, so earlier Takeout runs may have dropped burst frames. The sources still exist, so a re-run of the affected imports should now surface them.

### Tests — 106 → 126

- `TestFrameSignature` (14): extraction of milliseconds and burst indices across Pixel, Takeout, camcorder and organized naming; a `_1` collision counter not being mistaken for milliseconds; zero-padding equivalence; absence never conflicting; and a regression guard asserting all 17 real observed mispairings are caught.
- `TestBurstFramesNotSkipped` (6): neighbouring burst frame imported rather than skipped, same-second/different-millisecond imported, true duplicate of the same frame still skipped, the correct frame chosen when both are archived, byte-identity overriding a name conflict, and discriminator-free names behaving exactly as before.

</details>

---

## v13 — 2026-07-30 — "Source hash cache + dry-run purity"

Follow-ups found while validating v12 against the real Nikon NAS archive. Three fixes, all concerning where and when caches get written.

<details>

### Dry-run no longer writes into the source tree

v12's `_get_cached_md5()` stored the hash of an *incoming* file in an `.analysis_cache.json` inside that file's own directory. For a NAS-hosted or memory-card source that meant writing to the source tree — during `--dry-run`, which must modify nothing, onto media that may be read-only, and in the NAS case putting avoidable wear on the drives.

Source hashing now goes through a separate `_hash_source()`, and `_get_cached_md5()` is documented as archive-only. A test asserts that no cache file appears in the source directory even after an explicit flush.

### Source hashes cached outside the source tree

Rather than discard those hashes, they are recorded in `.source_hash_cache.json` beside the module, alongside the existing `.duration_cache.json`. Validated by mtime and size like every other cache here.

This matters because the normal workflow is dry-run, inspect, then live run — and without a cache each pass re-reads every source byte. The pending import backlog is over 100 GB, much of it across an SMB share.

`save_source_hashes()` prunes entries whose file no longer exists before writing. The expected outcome of an import is that the source file *moves* into the archive, so without pruning the cache would grow without bound.

Measured against `/Volumes/photosync/NIKON` (4,502 files, 12 GB): a repeat `--dry-run` reached identical verdicts in 99.8 s wall / 23.4 s CPU. For scale, the reconciliation run measured **190.9 s to MD5 that same file set** from cold.

`DuplicateDetector` accepts a `source_hash_cache` override so tests never write into the working directory.

### ImageAnalysisCache.save() tolerates an unwritable destination

`save_all_caches()` iterates every registered cache and previously let `FileNotFoundError` escape. Caches are flushed in bulk at the very *end* of a long run, and by then a directory may legitimately be gone — pruned during the run, or on a share that has since unmounted. The exception aborted the flush partway through and discarded every hash the run had just computed.

It now warns and moves on, leaving the cache marked dirty. Surfaced by a test that was itself wrong in an instructive way: it passed a *directory* to `ImageAnalysisCache`, which takes a cache *file* path, so `open()` created a plain file and the save appeared to succeed.

### Housekeeping

- `.gitignore`: added `.analysis_cache.json`, `.duration_cache.json`, and `.source_hash_cache.json`. None were ignored, so the first real run would have left them as untracked noise.
- Cleared a `SyntaxWarning` from an unescaped `\d` in a test docstring.

### Tests — 99 → 106

`test_source_directory_is_never_written_to`, `test_source_hash_is_cached_outside_the_source_tree`, `test_cached_source_hash_is_actually_consulted` (poisons the cache with a wrong hash to prove it is genuinely read rather than silently recomputed), `test_modified_source_invalidates_its_cached_hash`, `test_saving_prunes_entries_for_vanished_sources`, `test_corrupt_source_hash_cache_is_ignored`, and `test_save_survives_a_vanished_directory`.

</details>

---

## v12 — 2026-07-30 — "BUG-6: EXIF-only files were invisible to dedupe"

Import-time duplicate detection ignored 26.1% of the archive. Any file without a `YYYYMMDD_HHMMSS` stamp in its filename — every Nikon `DSCN*`, DSLR `DSC_*`, old `IMG_####`, and scanned image — was treated as new on every ingest. Fixed with a size-narrowed content-hash fallback. Also deletes a dead function whose tests were the reason this went unnoticed.

<details>

### BUG-6: find_duplicate() bailed out before consulting the index

`DuplicateDetector.find_duplicate()` extracted a date pattern from the source filename and, finding none, returned `is_duplicate=False` immediately — without ever looking at the archive. Organized Nikon files are named `DSCN3089_S3500.JPG`. So re-ingesting the same SD card classified every photo as new, and `move_file()` then "resolved the collision" by appending `_1`, emitting a log line that reads like success.

Measured on the live archive before the fix:

```
Archive files reachable by date-pattern dedupe: 27,547 / 37,300
Invisible to it: 9,753 (26.1%)

EXIF-ONLY FILE (already in archive, re-ingest simulation)
  is_duplicate : False
  reason       : No date pattern in filename
CONTROL: DATE-STAMPED FILE
  is_duplicate : True     <- name-based path worked fine
```

This was armed directly in front of the Phase C backlog: ~5,000 Nikon `DSCN` files, plus DSLR and old-camera files, against the stated goal of not "doubling the file count of our new photo/video archive with duplicates everywhere."

### Fix: size-narrowed content hashing

`find_duplicate()` now falls back to content comparison at **both** points where name-based matching gives up:

1. No date pattern in the filename at all.
2. A date pattern that matches nothing in the index — which also catches a photo that was renamed at some point since it was first imported.

Content hashing was chosen over an EXIF-date-plus-size heuristic deliberately. A false positive means **silently discarding a genuinely new photo**, which is far worse than importing a duplicate. Byte equality carries no such risk. Re-encoded and resized near-duplicates remain out of scope — the perceptual-hash pass in `photo_triage.py` handles those during review.

Hashing 158 GB to answer one question is avoided by narrowing on size first: byte-identical files necessarily have identical length, so only archived files sharing the source's exact size are ever hashed.

New members:

- `DuplicateDetector._get_size_index()` — lazily built `{size: [paths]}`. Deferred because a batch whose filenames all carry date stamps never needs it.
- `DuplicateDetector._get_cached_md5()` — reads MD5 from the per-directory `.analysis_cache.json`, computing and storing it only on a miss. 46,475 MD5s were already cached by previous triage runs.
- `DuplicateDetector._find_identical_by_content()` — size narrowing, then hash comparison over the survivors, sorted for deterministic results so a dry-run matches the live run that follows.
- `ImageAnalysisCache.get_md5()` / `set_md5()` — `get_hashes()` only returns when *both* md5 and phash are cached, and `set_hashes()` demands both. The new pair reads and writes the md5 alone without clobbering a phash or blur score.
- `DuplicateDetector.save_caches()` — flushes the duration cache *and* the analysis caches. Nothing previously persisted the latter, so newly computed MD5s were discarded, forcing a re-hash on every run (twice for the usual dry-run-then-live sequence). `organize_archive.py` and `workflow_reprocess.py` now call this instead of `save_duration_cache()`.

### Also removed: dead code that was actively misleading

`organize_archive.find_existing_by_date()` had **no call sites** — the live archive import path is `DuplicateDetector.find_duplicate()`. It carried its own `paths[0]`-only bug and an O(index) scan per file, and 8 tests asserted its behavior under a docstring claiming it was "the primary deduplication mechanism for DSCN and other EXIF-only files."

That false confidence is precisely why BUG-6 survived this long: the suite looked like it covered EXIF-only dedupe. The function and its tests are deleted, and Section 9 now covers the path that actually runs.

### Verified after the fix

```
EXIF-ONLY FILE (already in archive, re-ingest simulation)
  is_duplicate : True
  confidence   : EXACT
  reason       : Byte-identical to DSCN9371.JPG (no date in filename)
```

Batch scale check — 250 already-archived EXIF-only photos copied out and re-offered to the importer:

| Measure | Result |
|---|---|
| Detected as duplicate | 250 / 250, no misses |
| Per-file lookup | 5.8 ms |
| Detector init (37,300-file index) | 2.46 s |
| Projected, 5,000 Nikon files | ~29 s |
| Projected, full 28,800 backlog | ~167 s (upper bound; first run warms the cache) |

### Tests — 94 → 99 (8 removed, 13 added)

- `TestAnalysisCacheMd5` (5): roundtrip, missing entry, cross-field preservation against phash and blur, invalidation after content change, and no-raise on a vanished path.
- `TestExifOnlyDuplicateDetection` (8): the re-ingest regression case; a genuinely new file still importing (the failure mode that must never occur); same size but different content rejected, proving the match is by hash and not by size; a renamed-but-identical file caught; the date-pattern fast path unchanged; empty archive; missing source; and a stale cached hash not producing a false match.

### Note on mtime

An `mtime`-based date index was evaluated and rejected. `process_file()` calls `stamp_filesystem_dates()` after every move, so mtime *should* equal capture date, but sampling 400 EXIF-only archived photos found only 88.0% agreement: 11.2% disagreed, some by years, clustered around a bulk-copy date of 2023-08-19 and around scanned images whose EXIF records the scan rather than the scene.

</details>

---

## v11 — 2026-07-30 — "BUG-5: event folder re-run safety"

Fixed cluster detection so that re-running after an import collects new photos into the event folders that already own their day, instead of stranding them or creating a competing sibling folder. Tests written before the fix; suite grew from 75 to 94.

<details>

### BUG-5: cluster detection ignored existing event folders

`_detect_photo_clusters()` evaluated the ≥35-photos-per-day threshold against *loose direct-child files only*. It never considered that a day might already own an `MM-DD Event` folder from a previous run. Two distinct failure modes:

1. **Stranding.** A batch adding fewer than `threshold` photos to an already-filed day left them loose in the month folder, beside the folder they belonged in.
2. **Competing folders** (the worse case, and the one a naive "count the loose files" audit misses entirely). A batch adding *more* than `threshold` photos to a day covered by a span folder created a brand-new folder for that day. On the live archive this would have created `2016/07 July/07-19 Event` holding 102 photos directly beside the existing `2016/07 July/07-18–07-19 Event` — splitting one event across two siblings.

**Fix:** `_detect_photo_clusters()` now runs two passes.

- **Pass 1 (adoption)** routes any loose photo whose day is already claimed into that existing folder, regardless of threshold. Adoption is a correctness repair rather than discovery, so it runs even when `--event-threshold 0` is passed — otherwise that flag would silently reintroduce the bug.
- **Pass 2 (discovery)** applies the original threshold logic to unclaimed days only. Adopted days are removed from the pool first, so a dense day adjacent to an existing folder forms its own folder rather than being absorbed into a renamed span. Renaming an existing folder would invalidate outside references to it, so that is deliberate.

**New:** `map_days_to_cluster_folders(month_folder, year)` reports which calendar days already own a cluster folder. It recognizes only the `MM-DD Event` and `MM-DD–MM-DD Event` names this script generates — named holiday folders (`2024 Christmas`) and hand-named folders (`Escape Room`) are deliberately excluded. Impossible dates (`02-30 Event`) and reversed spans are skipped rather than raising.

**Contract change:** `_detect_photo_clusters()` now returns `(destination_dir, files)` tuples instead of `(folder_label, files)`. The destination is fully resolved by the detector, so `process_year()` no longer infers it from `cluster_files[0].parent`. Dry-run output marks adoptions with `[into existing]`.

### Measured effect on the live archive

Re-running the dry-run against `Organized_Photos/` moved the total from 1,998 to 2,034 candidate photos:

| Year | Folder | Photos | Was |
|---|---|---|---|
| 2016 | `07-18–07-19 Event` | 102 | would have created a competing `07-19 Event` |
| 2016 | `10-29 Event` | 1 | stranded |
| 2018 | `06-14 Event` | 8 | stranded |
| 2022 | `04-16 Event` | 27 | stranded |

All other years' output is byte-identical to the pre-fix run.

### Tests — Section 8, 19 new cases (75 → 94)

Written before the implementation and confirmed failing first. Fully hermetic: filenames carry `YYYYMMDD_HHMMSS` stamps so `_get_file_date()` resolves them with zero I/O — no exiftool, no cache priming, no network.

- `TestClusterFolderDayMapping` (10): single-day and span claims, month-boundary and leap-day spans, rejection of holiday folders, hand-named folders, files masquerading as folders, malformed names, and reversed ranges.
- `TestClusterAdoption` (9): the sub-threshold regression case, unchanged behavior for unclaimed quiet days and fresh dense days, inclusive threshold boundary, adopted days excluded from new span formation, span-wide adoption, `exclude_paths` still honored, explicit destination resolution, and `--event-threshold 0` still adopting.

</details>

---

## v10 — 2026-07-30 — "Reproducible environment"

Restored the photo review workflow, which had been silently non-functional since a Homebrew Python upgrade, and pinned the toolchain so it cannot break that way again. No changes to media-processing logic.

<details>

### Environment regression diagnosed and fixed

A Homebrew bump to Python 3.14.6 orphaned the previously-installed `site-packages`, removing `numpy` and `cv2`. Because `photo_triage.py:4324` calls `sys.exit(1)` when `OPENCV_AVAILABLE` is false, **every** photo review entry point (`workflow_review.py`, `review-issues`, `browse`, `auto-triage`) failed immediately. Blur scoring, perceptual-hash duplicate detection, and SSIM comparison were all unavailable.

- **`requirements.txt`** — new, with pinned versions and an explanation of why they are pinned: `opencv-python==5.0.0.93`, `numpy==2.5.1`, `pillow==12.3.0`, `pillow_heif==1.5.0`. External tools (`exiftool`, `ffmpeg`) remain outside pip.
- **README "Setup" section** — new top-level section documenting the `.venv` workflow and the `WARNING: OpenCV not installed` symptom.
- **AGENTS.md** — instructs assistants to invoke `.venv/bin/python`, never bare `python3`, and explains the failure mode so the next session doesn't misread an environment problem as a code problem.
- **`.gitignore`** — added `.TMP_*` so ad-hoc analysis scripts stop showing as untracked, per the project's temp-script convention.

### OpenCV 4.x → 5.0 verified, no code changes required

The available wheel line has moved to OpenCV 5.0 while this code was written against 4.x. Every `cv2` symbol referenced anywhere in the project (`GaussianBlur`, `cvtColor`, `resize`, `Laplacian`, `imread`, `dct`, `Canny`, `COLOR_BGR2GRAY`, `COLOR_RGB2BGR`, `CV_64F`, `INTER_AREA`, `IMREAD_GRAYSCALE`) was confirmed present in 5.0.

Verified against live archive files rather than only unit tests, since the unit tests patch OpenCV out:

- `test_core.py`: 75/75 pass, no OpenCV warning
- `calculate_blur_score` and `compute_phash`: 9/9 real files across JPG, PNG, and HEIC returned non-null values
- `calculate_image_ssim`: returns exactly `1.0` for a file against itself
- `photo_triage.py review-issues` on a 63-photo subset: exit 0, HTML generated, 4 duplicate groups found

### Previously-uncommitted work committed

`test_core.py` (75 tests, documented in v6) and `workflow_review.py` (documented in v9) existed on disk but had never been committed.

</details>

---

## v9 — 2026-05-23 — "Review workflow + doc cleanup"

**workflow_review.py** — New orchestrator that chains the three steps needed to review organized photos: blur cache warm-up (`auto-triage --dry-run`), `review-issues` HTML report, and `browse` HTML report. Supports `--open`, `--no-duplicates`, and `--skip-cache` flags.

**README.md** — Fixed stale `review` subcommand references to match actual CLI (`review-issues` and `browse`). Trimmed the Photo Triage section to focus on the new `workflow_review.py` entry point instead of requiring users to remember three separate incantations.

**photo_triage.py** — Updated epilog/help text to reflect actual subcommand names and reference the new workflow script.

---

## v8 — 2026-05-22 — "Nikon AVI datetime-prefix rename on transcoding"

**convert_legacy.py** — Nikon AVI files (stems matching `DSC[N_]*`) now receive a `YYYYMMDD_HHMMSS_` datetime prefix when converted to H.265, mirroring the naming convention used for camcorder files (`YYYYMMDD_HHMMSS_CAM.h265.mp4`). The existing model-suffixed stem (`DSCN5075_S3500`) is preserved after the prefix, so the result is `20140916_143022_DSCN5075_S3500.h265.mp4`. Non-DSCN legacy files are unaffected and keep their original stem with `.h265.mp4` appended.

New helpers:
- `get_video_creation_date(file_path)` — exiftool → mtime fallback, returns `datetime`
- `DSCN_STEM_PATTERN` — constant matching `^DSC[N_]` (mirrors organize_archive.py)

---

## v6 — 2026-05-18 — "Tests + Nikon Reconcile"

Added the first test suite and a dedicated reconciliation tool for the Nikon NAS archive before any ingestion begins.

<details>

### test_core.py — 63 unit tests covering critical business logic

New test suite targeting the functions whose silent failures have caused the most historical data-quality bugs. Does NOT require any live files, NAS mounts, or exiftool calls for the pure-logic tests. Keeper-priority tests use real tempfiles so `Path.stat()` returns realistic data; EXIF and dimension lookups are patched.

Sections:
- **Date extraction** (both `organize_archive` and `check_nas_archive` variants): 14 tests covering known-good formats, DSCN/DSC no-date cases, invalid dates, and edge boundaries. Confirms the two modules agree on extractable substrings.
- **Duplicate detection** (`find_existing_by_date`): 8 tests including the ±5% size-tolerance gate, edited-variant exclusion, and empty-index behavior.
- **Project-folder classification** (`is_project_folder`): 9 tests including the DCIM-bucket guard regex (`^\d{3}[A-Z0-9]+$`) that was added in v4.
- **Keeper-priority sorting** (`_sort_paths_by_keeper_priority`): 7 tests covering review-area penalty, EXIF date wins, size fallback, filename-length tiebreaker, resolution for perceptual-similar groups, and the assertion that resolution is NOT used for exact duplicates.
- **AnalysisCache** get/set/invalidation: 9 tests including cross-field preservation (set_blur must not clobber existing hashes), dirty-flag lifecycle, and corrupted-file graceful degradation.
- **Shell-export escaping**: 8 tests verifying the `'\''` idiom correctly neutralizes `$`, backticks, semicolons, embedded single quotes, spaces, newlines, and backslashes.

### reconcile_nikon_archive.py — read-only NAS comparison tool

New tool for the Nikon NAS archive reconciliation problem: 13GB / ~5000 files whose date history is uncertain due to years of manual renaming and cross-camera use of the same DSCN sequence counters.

Classification categories (in priority order):
1. `EXACT_MATCH` — byte-identical MD5 match; safe to skip
2. `DATE_SIZE_MATCH` — EXIF date + file size within ±5%; high-confidence duplicate
3. `POSSIBLE_COLLISION` — same DSCN sequence number in archive but differing EXIF date or size; needs human review before skipping
4. `NEW_CONTENT` — no match by any strategy; candidate for ingestion
5. `NO_EXIF` — EXIF extraction failed; cannot classify reliably
6. `ERROR` — file could not be read

Features:
- EXIF extraction batched (500 files/call) for performance
- MD5 index built once over Organized_Photos/ and reused for all comparisons
- Per-file DSCN sequence number index detects numbering collisions
- Results cached to `.TMP_reconcile_cache.json` beside the NAS directory for fast re-runs without re-doing the full MD5+EXIF extraction
- `--cache-only` flag re-displays the summary from a previous run
- `--no-md5` flag for a quick first-pass (date+size only)
- `--verbose` prints each file's classification in real time
- Never touches Organized_Photos/, TO_PROCESS/, or the NAS files themselves

Rejected alternative: Running `workflow_archive.py --dry-run` against the NAS directly. That approach would produce a "what would be moved" list but gives no signal about files that are ALREADY present in the archive — which is exactly the information needed before deciding whether to ingest 13GB. The reconcile tool answers that question first.

### reconcile_nikon_archive.py — collision model corrected

Replaced DSCN-sequence-number collision detection (which flagged thousands of false positives from two cameras sharing the same counter range) with destination-path collision detection:

- **Old approach:** flagged any two files with the same `DSCN_XXXX` sequence number regardless of whether they would actually occupy the same folder. Result: ~thousands of `POSSIBLE_COLLISION` hits that weren't real problems.
- **New approach:** computes the exact `YYYY/MM MonthName/filename` destination path (mirroring `organize_archive.py` logic) and checks whether that specific path already exists in the archive. Only files that would cause a true filename+directory collision are flagged as `DEST_COLLISION`.
- **Model suffix** (`_S3100`, `_S3500`, `_D3000`, etc.): derived from the EXIF `Model` field and appended to the filename stem before the extension. This is the same pattern as person suffixes (`_Clif`, `_Nicole`). With the suffix applied, most sequence-counter overlaps between two cameras become non-colliding (`DSCN2542_S3100.JPG` vs `DSCN2542_S3500.JPG`), so fewer files land in `DEST_COLLISION`. `extract_camera_model_suffix()` and `compute_destination_filename()` are the new helpers.
- Added `build_archive_dest_index()` (replaces `build_archive_dscn_index()`).
- Cache forward-compatibility: `--cache-only` migrates old `POSSIBLE_COLLISION` entries to `DEST_COLLISION` automatically.
- 12 new tests in `test_core.py` (Section 7) cover model suffix extraction and destination filename assembly, bringing the total to 75.

NAS discovery: archive contains two cameras — CoolPix **S3100** (8MP, older folders) and CoolPix **S3500** (10MP, later folders). Both have full EXIF metadata comparable to the D3000 except `LensModel` (fixed-lens compacts write no lens model). macOS Finder Quick Info surfaces all other fields identically.

</details>

---

## v5 — 2026-05-17 — "Correctness Pass"

Bugfixes from analysis session: shell script injection, keeper selection reliability, and resolution-aware duplicate comparison. No regressions introduced; both modified modules import cleanly.

<details>

### BUG-1: Keeper selection replaced — mtime → EXIF date + tiebreakers

- **Root cause:** Both `auto_triage()` and `_render_duplicate_group()` sorted duplicate groups by `st_mtime` descending and treated index 0 as the keeper. Filesystem modification times are corrupted by card readers, file copies, and Takeout export dates — making them an unreliable proxy for "which copy is the original."
- **Fix:** New `_sort_paths_by_keeper_priority(paths, dup_type)` function in `photo_triage.py` applies a stable priority chain:
  1. Non-review-area paths preferred (`_TO_REVIEW_`, `Duplicates`, `Blurry` penalized)
  2. For perceptual-similar groups: higher pixel count (original > compressed copy)
  3. Earliest EXIF DateTimeOriginal (true capture date)
  4. Larger file size (less re-encoding history)
  5. Shorter filename (sequential camera names are shorter than collision copies)
  6. mtime descending (last resort only)
- Both `auto_triage()` and `_render_duplicate_group()` now delegate to this function.
- **Affected files:** `photo_triage.py`

### BUG-2: Resolution comparison for perceptual duplicates

- **Root cause:** pHash-similar groups had no mechanism to prefer the higher-resolution original over a texted/compressed thumbnail — both just sorted by mtime.
- **Fix (three-part):**
  1. `AnalysisCache` in `analyze_photo_quality.py` gains `get_dimensions()` / `set_dimensions()` methods, storing `image_width` and `image_height` per file.
  2. `batch_extract_exif_dates()` in `photo_triage.py` now fetches `-ImageWidth -ImageHeight` alongside date fields in the same exiftool call — zero extra subprocess cost.
  3. New `get_image_dimensions(file_path)` function in `photo_triage.py` (mirrors `get_exif_date()`) checks the cache first, falls back to a single exiftool call.
  4. Resolution is shown in the HTML duplicate card for transparency.
  5. `_sort_paths_by_keeper_priority` uses pixel count as criterion 2 for `similar` (pHash) groups; exact-duplicate groups skip it (all copies are the same image).
- **Affected files:** `analyze_photo_quality.py`, `photo_triage.py`

### BUG-3: Identical duplicate detection — root cause identified, no code change

- Diagnostic: `scan_for_duplicates(directory, recursive=True)` is correct. Cross- year duplicates are missed only when `directory` is scoped to a single year/month subfolder rather than the root `Organized_Photos/`. README note added to run auto-triage against the full root to catch cross-year identical pairs.

### BUG-4: Shell script injection fixed (both export functions)

- **Browse export** (`exportRemovals()`) and **review export** (`exportDecisions()`) both generated `rm "path"` shell lines. The browse export escaped `"` but not `$` or backticks; the review export did no escaping at all.
- **Fix:** Both functions now emit `rm 'path'` with embedded single quotes escaped via the `'\''` shell idiom. Single-quoting is the only portable, unconditionally safe approach for arbitrary POSIX paths.
- **Affected file:** `photo_triage.py`

### DSCN (Nikon compact) support — confirmed no code change needed

- Nikon compact cameras use `DSCNXXXX.JPG` filenames with no embedded date. These fall through `extract_date_from_filename()` (no match) to the EXIF path — same behavior as the DSLR `DSC_XXXX.JPG` files handled in v4. No new pattern needed.
- Nikon DCIM subdirectory names (`100NIKON`, `101NIKON`, etc.) match the `^\d{3}[A-Z0-9]+$` guard added in v4, so they are correctly treated as loose-file containers rather than project folders.

</details>

---

## v4 — 2026-02-23 — "DSLR Ingestion + Archive Performance"

Support for DSLR memory card contents (DSC_-prefixed files), archive workflow output improvements, and a significant performance improvement via batch EXIF extraction.

<details>

### DSLR memory card support

- `is_project_folder()` in `organize_archive.py` now excludes standard DCIM subdirectory names (e.g., `100D3000`, `101CANON`) via `^\d{3}[A-Z0-9]+$` regex. Previously these were misclassified as project folders and moved as a unit into a single month bucket; now their contents are scattered individually by EXIF date.
- Confirmed: DSLR EXIF (`DateTimeOriginal`) is solid and always present; the single-file fallback in `get_date_from_exif()` handles these correctly.

### Batch EXIF extraction for archive workflow

- New `batch_extract_dates(file_paths, chunk_size=1000)` in `organize_archive.py` collapses N per-file exiftool subprocess spawns into one (or a small number of chunked) invocations. For a typical DSLR card of ~500 files, this is ~500× faster than the old per-file path.
- `get_creation_date()` gains an `exif_cache` parameter; cache hits short-circuit before the single-file fallback is reached.
- `process_file()` accepts and passes through `exif_cache`.
- `main()` in `organize_archive.py` pre-fetches dates for all files lacking a filename date, then reports hit/miss count before processing begins.

### Archive workflow dry-run output improvements

- `move_file()` dry-run now shows `YYYY/MM MonthName/filename` instead of the full absolute path, reducing noise.
- Live run "Moved to:" line now includes year: `YYYY/MM MonthName/`.
- Summary block in dry-run mode appends the full output root paths for both photos and videos.

</details>

---

## v3 — 2026-01 — "Stabilization and Triage Tooling"

(Reconstructed from `_CONVERSATION.md` messages 83–147 and commit `f0bd5cd`)

Major stabilization pass after the initial processing run. Introduced photo triage and review tools, extensive refactoring to eliminate SRP violations, and a second processing run on 31,733 files.

<details>

### Script renaming for clarity

- `organize_photos.py` → `organize_media.py`
- `verify_remaining_files.py` → `check_leftover_files.py`
- `reunite_project_files.py` → `fix_fragmented_metadata.py`

### Shared code extraction

- `build_file_index.py` extracted from duplicated index-building logic across multiple scripts.
- `media_utils.py` introduced as shared constants and utility functions.

### New triage tooling

- `photo_triage.py` introduced: blur detection, duplicate scanning (MD5 + pHash), auto-triage file moves, HTML browse report, HTML review report.
- `analyze_photo_quality.py` introduced: `ImageAnalysisCache`, blur scoring, perceptual hashing, `scan_for_duplicates`.

### Metadata handling improvements

- `cleanup_orphaned_json.py` `--yes` / `-y` flag added for non-interactive batch processing.
- Enhanced date patterns: added `YYYY-MM-DD-HH-MM-SS`, `YYYY-MM-DD`, `YYYY-MM_` support.
- Wallpaper detection: files with resolution prefixes (`1920x1080`, `4k`, etc.) routed to `_TO_REVIEW_/Wallpapers/`.
- File extension auto-fix via magic byte detection (JPEG, PNG, GIF, WebP, HEIC, MP4); 127 mismatched extensions corrected across the 31,733-file run.
- EXIF write now retried after extension correction if the initial write failed due to format mismatch.

### HTML review enhancements (lightbox)

- Keep/Remove outline highlighting in lightbox.
- Spacebar toggles keep/remove.
- Up/Down arrow navigation between photos.
- Warning footer for edge cases.
- Blur score badges.

### Archive and camcorder workflows

- `organize_archive.py` introduced for NAS/phone exports without JSON metadata.
- `workflow_archive.py` orchestrator added.
- `workflow_camcorder.py` orchestrator added for AVCHD conversion.
- `duplicate_detector.py` introduced: date-pattern + duration + size multi-signal matching for import deduplication.

</details>

---

## v2 — 2025-12 to 2026-01 — "Google Takeout Processing"

(Reconstructed from `_CONVERSATION.md` messages 1–82 and commit `daa99f0`)

Initial implementation of the Google Takeout pipeline. Approximately 80 messages across two Sonnet sessions — 25.6% regression debugging, 17.1% new requirements.

<details>

### Core Takeout pipeline

- `organize_media.py` (initially `organize_photos.py`): two-phase organization (project folders, then individual files) with JSON metadata merging.
- `merge_metadata.py`: batch EXIF writer from Google Takeout JSON.
- `fix_truncated_extensions.py`: `.MP` → `.mp4` and similar truncation fixes.
- `workflow_takeout.py`: master orchestrator.

### Date handling

- `photoTakenTime` vs `creationTime` comparison; files where they differ by 3+ months routed to `_TO_REVIEW_/` for manual inspection.
- Filename-first date extraction (YYYYMMDD patterns checked before parsing JSON).
- In-memory file index for O(1) duplicate detection.

### Duplicate and project handling

- Project folder detection and merging across multiple Takeout archives.
- Trash directory routing to `_TO_REVIEW_/Trash_Archives/`.
- `cleanup_orphaned_json.py` for leftover metadata files.
- `fix_fragmented_metadata.py` for projects split across dated folders.

### Known regressions introduced and fixed within this period

- Multiple undefined-function errors from premature code submission (Sonnet pattern).
- Function signature mismatches during refactoring.
- `EOFError` in `cleanup_orphaned_json.py` stdin handling (fixed with `--yes` flag).

</details>

---

## v1 — 2025-12 — "Initial Vision"

(Commit `9da7a30`)

Project scaffolded. `organize_media.py`, README, basic directory structure (`TO_PROCESS/`, `Organized_Photos/`, `Organized_Videos/`).

<!--

The organize_media code was initially written by Claude Sonnet 4.5 in early 2026, and took a few combined prompts to get started:

i have run a google takeout task which has exported my family's personal photos for local storage. however, the files are split across five archive folders which organize photos only by year, and include supplemental-metadata files containing the very important creationTime, photoTakenTime, and geoData objects.

i would ike to combine all of the separate repeated directories into one, with directories for each full four-digit year, and subdirectories for each month in each year, in the format "01 January", "02 February", etc, and move the photo, video, and metadata files into their appropriate destination. delete the trash directories, as well as empty event folders (ones that may contain a metadata file, but no media). there are also a few folders that may or may not have specific names, may or may not be split across multiple takeout directories, and should be placed in their appropriate year directory and prefixed with the two-digit month code.

also, there are some photos that were created by myself manually and added that should have probably used the creationTime object, instead of the photoTakenTime object, as in the current first ride file. incorporate a comparison between these two dates, and if they would assign media to different locations, move the file and its corresponding metadata into a _TO_REVIEW_ directory.

(and then about 80 follow-on prompts and fixes for this initial processing, because I was not clear enough, as well as the AI being forgetful or making some odd assumptions at times)

Additional key features were added incrementally to provide:

- multithreaded processing, and both regular and helpful logging of progress and results
- naming, metadata management, deduplication, re-encoding, and sorting of camcorder video files
- metadata management, deduplication, and sorting of DSLR photos
- automatic event subfolder categorization (birthdays, holidays, highly-photographed days)
- photo analysis tools for identifying blur, duplication, and over-captured events, via an HTML review page, which generate scripts for deletion
- specialization of scripts for better adherence to engineering principles, better separation of concerns, and reusability

-->
