# SDD ledger — plan: docs/superpowers/plans/2026-10-21-family-history-import-and-backup.md

> Note (2026-10-23): the commit hashes below refer to the local `current-effort` history, which was squashed into a single commit on `master` when the effort landed. The hashes are historical identifiers for the ledger's own narrative, not live references.

Pre-flight:
- Branch: current-effort (not master) — executing on the existing working branch. Ruling: no isolated worktree — Tasks 2/4/6/9/10/12 operate on the live media tree (Organized_*, TO_PROCESS, /Volumes) that no worktree can isolate; code commits land on current-effort as all prior work here does — cost if wrong: code churn visible on the working branch, recoverable via git.
- T7 consumes organize_media.get_date_from_filename(Path) — verified exists (organize_media.py:277), takes a Path-like with .stem, returns datetime|None. OK.
- T8 consumes media_utils parse_json_metadata/get_metadata_path/MEDIA_EXTENSIONS/MONTH_NAMES — verified exported (media_utils.py; MONTH_NAMES format "NN Name"). OK.
- T8 consumes merge_metadata.py CLI `<dir> --recursive --remove-json` — matches workflow_takeout.py:174 usage. OK.
- T5 consumes removal_history.RemovalHistory.from_directory/.was_removed + parse_removal_script — verified (removal_history.py:167-248). OK.
- T4/T12 consume backup_archive.py CLI (T3 Produces: sync|verify, --dest, --dry-run). Internally consistent.
- T10 consumes router CLI from T8 (flags match) and workflow_takeout.py interactive prompts (person → empty, confirm → Y). OK.
- Spec readable at docs/superpowers/specs/2026-10-21-family-history-import-and-backup-design.md. OK.
Task 1: complete (commits 5a13dc2..9bbeca2, ops task: 12/12 files rescued and committed)
Task 2: complete (ops: disk4 erased to APFS MEDIA_BACKUP, mounted at /Volumes/MEDIA_BACKUP as disk5s1; snapshot feasibility test: tmutil localsnapshot landed on boot volume only, listSnapshots on MEDIA_BACKUP empty → versioning decision: link-dest; test snapshot deleted)
Task 3: complete (commits 9bbeca2..c8c556e, tests: .venv/bin/python test_backup_tools.py → 7/7 OK; test_core.py → 256 OK)
Task 5: complete (commits c8c556e..c88665d, tests: test_backup_tools.py → 11/11 OK; test_core.py → 256 OK). Note: executed while Task 4's sync runs in background; Task 4's verify steps resume on sync completion.
Task 7: complete (commits c88665d..4cb5b20, tests: test_family_import.py → 16/16 OK; test_backup_tools.py OK; test_core.py → 256 OK). Executed ahead of Tasks 4/6 while the backup sync runs.
Task 8: complete (commits 4cb5b20..4920d24, tests: test_family_import.py → 26/26 OK incl. dedupe/dry-run/tag-failure; test_backup_tools OK; test_core 256 OK)
Task 9 (in progress): Ruling: real takeout media names carry '(N)' dedupe counters and '-edited' variants not in the plan's pinned examples — extract_batch_prefix strips both before sequence stripping (TDD RED→GREEN) — cost if wrong: over-grouped holding batches, recoverable by re-foldering
Task 9: complete (commits 4920d24..e71ce25, live subset: 7 files routed to predicted buckets; circa=1990:01:01+date-estimated, unknown keeps scan date, backdated tagged in place, 1963 negative epoch parses; subset + scratch output cleaned up)
Task 6 (steps 1-2): reconcile plant-proof passed (planted file surfaced as unexplained, exit 1); real run: 37300 present / 0 removed / 0 modified / 0 unexplained, exit 0; report committed. Deletion HELD pending Task 4 verify + owner approval.
Task 10 (in progress): Ruling: year-album twins of project-folder photos get bucket 'project-owned' (untouched) — wedding singles carry real 2023 dates but stripped camera EXIF, and organize_media's project dedupe owns them; measured: 206/208 project names have year-album twins, 0 wedding names escape the guard — cost if wrong: duplicates in holding, recoverable.
Task 10 (in progress): Ruling: extract_filename_year accepts optional '~' and space separator ("~1960 Eugen Bergmann") — real scan names in the takeout — cost if wrong: a mis-dated circa file, correctable in review.
Task 10 (in progress): Ruling: Desktop-copy deletion (Task 6 step 4) re-sequenced AFTER the import — it is user-gated and the import depends only on the verified backup; one approval request at wrap-up instead of a mid-plan stall — cost if wrong: none (deletion gate unchanged, just later).
Task 4: complete (ops: initial 205 GiB sync exit 0; plant-proof verify caught appended-byte README tamper + 6 post-sync drift files, exit 1; after restore + incremental link-dest re-sync, full manifest verify exit 0 "destination matches source exactly"; snapshots 2026-10-22-0743 and -0828 on drive, manifests written)
Task 10 (in progress): Ruling: fixed pre-existing organize_media.py:557 crash (eager ['_'+PERSON_NAME] on personless runs) via lazy iterable, TDD RED→GREEN, person-run semantics preserved exactly; NOTE deferred: the '-edited_{suffix}' check matches '-edited__Name' (double underscore) and likely never fires on person runs — pre-existing, not touched — cost if wrong: none new, behavior identical to before
Task 10: Ruling: find_google_photos_dirs only checks direct children of TO_PROCESS, so the nested takeout's project folders were never album-processed — wedding singles swept loose by date. Repaired post-hoc via .TMP_restore_wedding_albums.py (166 files into six 2023/06 Carina + Charlie album folders, prefix map verified against surviving sidecars, 0 strays after). Core discovery fix deferred to NEXT.md — cost if wrong: none remaining for this import.
Task 10: Ruling: Google year-view duplication gave every backdated album file a scan-dated twin in 2013/2014 albums; router moved twins first and organize's name dedupe deleted the backdated originals (580 skips, 0 placed). Repaired via .TMP_restore_backdated_dates.py using the PRE-ROUTING backup snapshot's sidecars: 133 real dates recovered, 127 surviving copies re-placed into true YYYY/MM with real EXIF dates, date-estimated markers removed, 0 names unrecoverable — cost if wrong: dates/placement, all verified by spot-check.
Task 10: Ruling: Friends and Failed Videos album files left in date-placed locations (camera-dated moderns; album membership mapping mostly consumed) — noted for optional future event-foldering — cost if wrong: missing album grouping on ~11 files.
Task 10: complete (commits ef6f4ea..HEAD pending docs, tests: all 3 suites OK; scatter check 0 scanner names in 2013/2014 after plant-proof; holding 2573 files, circa 954, wedding 166 in six album folders, backdated 127 re-placed with real dates; takeout residue: orphan JSONs + Trash video, in backup)
Task 11: complete (commits ..a101e95, docs: README takeout pre-pass + Backup sections, SCRIPTS entries for 3 new tools, CHANGELOG v22, NEXT.md decision-1 resolved + backup record + 3 deferred findings; _PRODUCED/_README.md created — gitignored with the media tree, travels via backup; all referenced paths verified; suite 257 OK)
Final review: REQUEST CHANGES, 3 Important + 5 Minor. Fix pass (one pass, each RED→GREEN):
Final: fixed date-estimated conditional on --person — test_apply_estimated_dates_writes_marker_and_dates RED→GREEN, suite 33/33+257/257
Final: fixed silent exiftool exit-code success — test_exit_code_failure_without_error_lines_is_reported RED→GREEN, suite green
Final: fixed live backdated-twin hazard — test_identical_twin_of_backdated_file_is_deleted_not_routed RED→GREEN, suite green; NEXT.md finding 2 marked fixed, README trap noted
Final: minor (deferred): exiftool += appends duplicate tag values on re-runs (use -= then +=)
Final: minor (deferred): merge_sidecars ignores merge_metadata exit codes (silent partial merge)
Final: minor (deferred): no snapshot retention policy recorded for backup_archive (unbounded, manual pruning)
Final: minor (deferred): project-twin guard matches basename only; content-different collisions silently withheld from routing
Final: minor (deferred): style — unused loop var cleaned incidentally; RouteAction annotations say Path/int/str but hold None
Final: Ruling: reviewer's declined-to-judge list reviewed — each line either pre-existing machinery recorded in NEXT.md, an owner-gated operational step, or a platform non-issue (macOS-only); all stand as set aside — cost if wrong: a future session re-derives them from NEXT.md
Task 12: complete (ops: final sync + full manifest verify exit 0 on the finished state; drive holds dated link-dest snapshots + manifests)
