# _records — irreplaceable evidence

Small machine-readable artifacts that cannot be regenerated once their subject is gone. Everything else this project produces is derived and reproducible; these are not.

## `damage_findings_home-movies.json`

`detect_splices.py` output for `/Volumes/home-movies`, 2026-08-06. Records which of the 1,463 files held content belonging to other files, where each splice begins, and what the foreign data was identified as.

Regenerating it takes 123 seconds **while the share exists**. Once the damaged sources are deleted it cannot be reproduced at all, and it is the only per-file record of what was wrong with each one. Feeds `attribute_splices.py`.

The prose summary lives in CHANGELOG v19; this is the detail behind it.

## `video-recovery-history.md`

The complete findings record of the August 2026 video effort — conversion verification, foreign-content discovery, and rescue — extracted verbatim from NEXT.md on 2026-10-23 when that file was returned to forward-looking-only. Holds the tables and measurements; its still-live warnings are mirrored in NEXT.md.

## `removal-scripts/`

The dated `remove_photos.sh` exports rescued from the Desktop quick-save before its deletion (2026-10-22). `removal_history.py` reads these alongside the exports in `Organized_Photos/`.

## `2026-10-22-family-import/`

The evidence bundle for the family-history import: per-file routing provenance (`route-live.log`), the workflow run that filed the remainder (`workflow-run2.log`), the execution ledger with every ruling made, and the two one-off repair scripts exactly as run (`restore_wedding_albums.py`, `restore_backdated_dates.py`). The takeout is consumed, so none of this can be regenerated.

## `reconcile-quicksave-2026-10-22.txt`

The reconciliation report that cleared the Desktop quick-save for deletion: every file classified present, removed, modified, or unexplained against the live archive plus removal history.
