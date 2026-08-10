# process-media

Tools for consolidating a family's photos and videos from Google Takeout exports, NAS archives, phone backups and camcorders into one organized library, deduplicated and sorted by date.

Everything reads from `TO_PROCESS/` and writes to `Organized_Photos/` and `Organized_Videos/`, in `YYYY/MM MonthName/` folders with named event subfolders.

**This file documents the five workflows, which are the intended way to use the repo.** For the individual scripts behind them, including the engines the workflows drive and the tools for when something has gone wrong — see **[SCRIPTS.md](SCRIPTS.md)**.

---

## Two rules that matter more than anything else here

**1. Run everything as `.venv/bin/python`, never bare `python3`.**

Bare `python3` has no OpenCV, and `photo_triage.py` exits immediately without it. That combination silently disabled the entire photo review workflow for months after a Homebrew upgrade orphaned the global packages. If you ever see `WARNING: OpenCV not installed`, you are running the wrong interpreter and quality analysis is quietly unavailable.

**2. Stage a copy before importing from an archive.**

`organize_archive.py` **moves** files. `camcorder_convert.py` **deletes** sources after converting. Both defaults are correct for a disposable `TO_PROCESS/` copy and destructive against a NAS share or a memory card. Guards now refuse the worst cases, but copying first is still the habit that protects you.

---

## Setup

```bash
brew install exiftool ffmpeg          # external tools, not pip-managed
python3 -m venv .venv                 # system python, only for this step
.venv/bin/python -m pip install -r requirements.txt

# Should report "Ran 196 tests ... OK" with no OpenCV warning
.venv/bin/python test_core.py
```

Dependencies are pinned in a project-local `.venv/` on purpose, so a system Python upgrade cannot orphan them again.

---

## Which workflow do I want?

| I want to… | Workflow |
|---|---|
| Import a Google Takeout export | [Takeout import](#1-takeout-import) |
| Import a NAS folder, phone dump, or memory card | [Archive import](#2-archive-import) |
| Convert camcorders or legacy video to H.265 | [Video conversion](#3-video-conversion) |
| Find blurry photos and duplicates to prune | [Review and prune](#4-review-and-prune) |
| Maintain media that is already organized | [Reprocessing](#5-reprocessing) |

Before importing from anywhere new, two read-only surveys are worth the minutes:

```bash
# How much of this do I already have?
.venv/bin/python reconcile_nikon_archive.py /Volumes/share/SomeFolder --no-md5

# Is any of it damaged?
.venv/bin/python check_media_health.py /Volumes/share/SomeFolder

# Does any of it contain data belonging to other files?
.venv/bin/python detect_splices.py /Volumes/share/SomeFolder
```

That third survey exists because the second one is not sufficient on old media. A file can be perfectly intact and still be the wrong content: eight `.MTS` files on the home-movies share hold no footage at all, and ffprobe reports one of them as a valid 2,959-second MP3 stream. "Does this decode" answers yes.

---

## 1. Takeout import

For Google Takeout exports, which arrive as dated folders plus JSON sidecars holding the metadata that actually matters.

```bash
# Extract each Takeout archive into TO_PROCESS/ as its own folder, then:
.venv/bin/python workflow_takeout.py
```

<details>

Prompts for the person's name, then in order: repairs truncated extensions (`.MP` → `.mp4`), merges JSON metadata into EXIF, organizes by date with a person suffix, and rebuilds the file index between Takeout folders so duplicate detection stays accurate across 50+ directories.

**Multiple family members:** run it once per export, replacing the `TO_PROCESS/` contents between runs and answering with a different name. Filename collisions resolve by appending the person suffix.

**Where things land:** photos and videos into their year/month folders; anything where `photoTakenTime` and `creationTime` disagree by three months or more goes to `Organized_Photos/_TO_REVIEW_/` rather than being filed on a guess.

**Afterwards, if the export was fragmented:**

```bash
.venv/bin/python fix_fragmented_metadata.py --dry-run   # reunite split project folders
.venv/bin/python cleanup_orphaned_json.py --yes         # drop sidecars whose media is gone
```

</details>

---

## 2. Archive import

For anything without JSON sidecars — a NAS folder, a phone dump, a memory card.

```bash
# Stage a copy first if the source is an archive rather than scratch space
.venv/bin/python workflow_archive.py TO_PROCESS/SomeBatch --dry-run
.venv/bin/python workflow_archive.py TO_PROCESS/SomeBatch
```

| Flag | Effect |
|---|---|
| `--dry-run` | Report without moving anything. Always do this first. |
| `--person-suffix NAME` | Append an owner suffix to every filename |
| `--model-suffix SUFFIX` | Override the EXIF-derived camera model suffix for the whole batch |

<details>

**How it decides what is already present**, in order: filename date pattern, sub-second frame discriminators, video duration, file size within tolerance, content hash, and structural similarity for same-dimension recompressions. Camera model suffixes (`_S3500`, `_D3000`) are derived from EXIF per file, so two cameras sharing a filename counter do not collide.

**Two gates run before anything is imported.** A file deliberately deleted in an earlier review is not re-imported — that history comes from the removal scripts the review pages export. A file that fails an integrity check is held back rather than allowed into the archive, where a later review could pick it over a healthy copy. Override with `--ignore-removal-history` or `--import-damaged` on `organize_archive.py` if you genuinely want either.

**If files have no usable EXIF date:**

```bash
.venv/bin/python apply_date_from_neighbor.py TO_PROCESS/SomeBatch --dry-run
```

</details>

---

## 3. Video conversion

Converts H.264, MPEG-2 and AVCHD to H.265 for archival. Files already in an efficient codec are skipped.

```bash
.venv/bin/python workflow_camcorder.py TO_PROCESS/CAMCORDER --dry-run
.venv/bin/python workflow_camcorder.py TO_PROCESS/CAMCORDER
```

| Flag | Effect |
|---|---|
| `--dry-run` | Analyze, estimate time, encode nothing |
| `--avchd-only` | **Restrict to `.MTS`/`.M2TS`** |
| `--keep-originals` | Do not delete sources |
| `--crf N` | Quality factor, default 26 |
| `--preset NAME` | x265 preset, default `slow` |
| `--force-software` | Force `libx265` rather than letting VideoToolbox take clean footage |

<details>

**`--avchd-only` matters when the source is an archive.** Without it the scan takes every video extension, including MP4s that `organize_archive.py` already imported. It cannot recognize those, because that import path does not write to the conversion index — so it would cheerfully write H.265 duplicates alongside copies you already have. Pointed at the home-movies share, that was the difference between 1,368 files and the correct 669.

**Encoding settings:** CRF 26, preset `slow`, AAC 192k audio. CRF started at 20 and was raised because 20 produced bloated files for no visible benefit. Encoder selection is automatic — VideoToolbox for clean footage, `libx265` for noisy, since hardware encoding handles grain poorly.

> **Note:** `convert_legacy.py` still uses CRF 20, and the two have diverged. The camcorder reasoning probably applies there too, but changing it would alter quality and size for every future legacy conversion, so it is left alone pending a decision.

**Deduplication survives across sources.** The conversion index keys on the original's recording date and byte size rather than its filename, because camcorder filenames restart at `00000.MTS` on every card and mean nothing across them. It is written per conversion, so an interrupted batch loses one file rather than the run.

**Time:** roughly 4–7 GB of source per hour depending on how much lands on software encoding. `--dry-run` gives an estimate up front.

</details>

---

## 4. Review and prune

Finds blurry photos and duplicates, and produces two HTML pages for making decisions.

```bash
.venv/bin/python workflow_review.py --open
```

| Flag | Effect |
|---|---|
| `--open` | Open the reports in a browser |
| `--no-duplicates` | Skip duplicate scanning (faster) |
| `--skip-cache` | Skip cache warm-up when it is already populated |

<details>

Three steps: warm the blur and hash caches, build `_review_issues.html` (problems only), build `_browse_all.html` (everything, by folder). Both land at the root of `Organized_Photos/`.

**The review page groups by problem** — blurry photos with a sharp alternative nearby, exact duplicates, and perceptually similar sets. Keeper selection prefers a file outside the review areas, then higher pixel count for perceptually similar groups, then the earliest EXIF date, then larger size, then the shorter filename. Spacebar toggles keep/remove in the lightbox; arrow keys move between photos.

**Export produces a shell script of `rm` lines.** Keep those. They are parsed on later imports so that anything you deliberately deleted is not silently restored.

```bash
# Stage removals as symlinks in _TO_REVIEW_/ instead of deleting outright
.venv/bin/python photo_triage.py auto-triage --symlinks

# Undo a triage run
.venv/bin/python photo_triage.py undo --dry-run
```

> **Known limitation.** Keep/remove decisions live in browser `localStorage`, keyed by path, so importing files or re-running event folders orphans them. Removal decisions are durable via the exported scripts; **keep** decisions are not. Finish importing and cataloguing before investing hours in review.

</details>

---

## 5. Reprocessing

Maintenance for media that is already organized. Menu-driven.

```bash
.venv/bin/python workflow_reprocess.py
```

| Action | What it does |
|---|---|
| Convert legacy formats | Re-encodes AVI, MTS and MPEG-2 already in `Organized_Videos/` in place |
| Duplicate check | Scans the organized archive rather than an incoming batch |
| Deep codec scan | Finds files whose container disagrees with their codec |
| Fix motion photos | Pixel dual-stream files QuickLook cannot play — extract the still, drop the video, or make it playable |
| Create event folders | Groups photos into named holiday, birthday and dense-day event folders |

<details>

### Event folders

Worth understanding, since it moves a lot of files.

```bash
.venv/bin/python create_event_folders.py                    # dry-run, all years
.venv/bin/python create_event_folders.py --year 2024        # dry-run, one year
.venv/bin/python create_event_folders.py --execute
```

Two passes. **Named events** first — configured birthdays, Fourth of July, Halloween, Thanksgiving, Christmas — producing `2024 Christmas` or `2024 J Birthday - 14` inside the month folder. Then **dense-day detection** for untagged events: any day with 35+ photos becomes `MM-DD Event`, and consecutive dense days merge into a span.

Only direct children of month folders are candidates, so anything already filed is left alone. Loose photos belonging to a day that already has an event folder are adopted into it regardless of the threshold, which is what stops a later import stranding a handful of photos beside the folder they belong in. Cache entries travel with moved files, so no re-analysis is needed.

`--event-threshold N` tunes cluster detection; `0` disables discovery but not adoption.

</details>

---

## Roadmap and known issues

Live work — in flight, queued, decisions needed, open concerns — is in **[NEXT.md](NEXT.md)**.

**[CHANGELOG.md](CHANGELOG.md)** is the permanent record of what changed and why, including the measurements behind each decision and the approaches that were tried and rejected. Worth reading before re-deriving anything: perceptual hashing cannot verify a duplicate match, duration alone cannot match videos, and mtime is 88% reliable as a date source.

**[SCRIPTS.md](SCRIPTS.md)** itemizes purpose and usage of all worker scripts.
