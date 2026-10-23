#!/usr/bin/env python3
"""
Classify family-takeout media by how recoverable its real date is.

The 2013-2014 scanning effort uploaded decades of physical photos whose
sidecar photoTakenTime is the SCAN date, not the depicted era. organize_media
trusts filename dates first and JSON second, so without this layer every scan
would file into the real 2013-2014 archive — the scattering the design spec
forbids. This module is pure decision logic; route_family_scans.py applies it.

Buckets (spec §1, priority order pinned there):
    modern    - carries a real full date (filename pattern or camera EXIF)
    backdated - sidecar photoTakenTime is pre-2013, i.e. a real depicted date
    circa     - filename names a year 1900-2012 (e.g. 1980-youth-065.jpg)
    unknown   - no recoverable date; fails safe to the holding folder
"""

import re
from pathlib import Path

from organize_media import get_date_from_filename

# First year of the scanning effort: photoTakenTime at or after this is a scan
# date, not a depicted date (spec's scan-era boundary).
SCAN_ERA_START = 2013

# A circa year must be plausible for physical photos: 1900 up to the scan era.
CIRCA_YEAR_MIN = 1900

# Leading 4-digit year followed by -, _, or space, with an optional circa
# tilde (1980-youth-065, 1990_13, 1997_8, "~1960 Eugen Bergmann").
_LEADING_YEAR = re.compile(r"^~?(\d{4})[-_ ]")

# One trailing frame/sequence group: optional separator, digits, optional
# single letter (045, -040, -18A, 000011). Applied at most twice so batch
# names like 0NBergm-R1-040-18A keep their roll identity (0NBergm-R1).
_TRAILING_SEQUENCE = re.compile(r"(?:[-_]?\d+[A-Za-z]?)$")
_MAX_SEQUENCE_STRIPS = 2

# Noise Takeout and editors append AFTER the sequence number, stripped before
# sequence stripping: Google's own dedupe counter "(13)" and "-edited".
_TAKEOUT_COUNTER = re.compile(r"\(\d+\)$")
_EDITED_SUFFIX = re.compile(r"-edited$", re.IGNORECASE)


def extract_filename_year(filename):
    """
    Pull a circa year from a scan-batch filename, or None.

    Only a LEADING year counts — a year mid-filename is usually part of a full
    camera timestamp, which get_date_from_filename already handles — and full
    date patterns are rejected here so this never shadows a real date.
    """
    stem = Path(filename).stem

    if get_date_from_filename(Path(filename)):
        return None

    match = _LEADING_YEAR.match(stem)
    if not match:
        return None

    year = int(match.group(1))
    if CIRCA_YEAR_MIN <= year < SCAN_ERA_START:
        return year
    return None


def extract_batch_prefix(filename):
    """
    Reduce a scan filename to its batch name for the holding subfolder.

    Strips at most two trailing sequence groups, refusing a strip that would
    empty the stem; stems that were nothing but digits become 'misc'.
    """
    stem = Path(filename).stem
    stem = _TAKEOUT_COUNTER.sub("", stem)
    stem = _EDITED_SUFFIX.sub("", stem)

    for _ in range(_MAX_SEQUENCE_STRIPS):
        stripped = _TRAILING_SEQUENCE.sub("", stem)
        if not stripped or stripped == stem:
            break
        stem = stripped

    if not stem or stem.isdigit() or not re.search(r"[A-Za-z]", stem):
        return "misc"
    return stem


def classify_file(album_name, filename, taken_year, camera_model):
    """
    Place one takeout media file into its routing bucket.

    Priority order is pinned in the spec: a real full date beats everything
    (rule 1), a pre-scan-era sidecar date is real (rule 2), a filename year is
    an estimate (rule 3), camera EXIF rescues ambiguous digital photos
    (rule 4), and everything else fails safe toward the holding folder.
    album_name rides along for report context; it carries no classification
    signal on its own (the sidecar already encodes the album's year).
    """
    if get_date_from_filename(Path(filename)):
        return "modern"

    if taken_year is not None and taken_year < SCAN_ERA_START:
        return "backdated"

    if extract_filename_year(filename) is not None:
        return "circa"

    if camera_model:
        return "modern"

    return "unknown"
