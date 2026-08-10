# _records — irreplaceable evidence

Small machine-readable artifacts that cannot be regenerated once their subject is gone. Everything else this project produces is derived and reproducible; these are not.

## `damage_findings_home-movies.json`

`detect_splices.py` output for `/Volumes/home-movies`, 2026-08-06. Records which of the 1,463 files held content belonging to other files, where each splice begins, and what the foreign data was identified as.

Regenerating it takes 123 seconds **while the share exists**. Once the damaged sources are deleted it cannot be reproduced at all, and it is the only per-file record of what was wrong with each one. Feeds `attribute_splices.py`.

The prose summary lives in CHANGELOG v19; this is the detail behind it.
