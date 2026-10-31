"""
Parser for real-world broker "Available Loads" exports.

Why pattern-based, not position-based:
A first attempt at this assumed a clean header row followed by data
rows -- the normal spreadsheet shape. Real broker exports don't look
like that. They're built by hand in Excel over time: dispatcher
contact blocks, load-count summaries ("GREENS-5 BLUE-1"), driver
instructions, and actual load rows are all interleaved, and rows that
start with "TYPE" appear repeatedly throughout the file without being
real column headers -- they're section markers with completely
different content each time.

Trying to detect "where does the real table start" and read
positionally from there breaks immediately on this kind of file.
Instead, this parser scans every row and classifies it by what the
row's *content* looks like: a load row has an origin that matches
"City, ST", and numeric-or-empty miles/rate columns. Anything that
doesn't match that shape -- contact info, notes, summaries -- is
skipped and counted, not guessed at.

This trade-off is deliberate: recall is capped by how well the
pattern matches an unfamiliar broker's export layout, but precision
is high -- a row is only ever kept when it genuinely looks like a
load, so accuracy for what does come out the other end doesn't
suffer for the sake of catching every possible row.
"""
from __future__ import annotations

import io
import re

import pandas as pd

from app.models import Load, ParseResult

CITY_STATE_PATTERN = re.compile(r"^[A-Za-z .'\-]+,\s*[A-Za-z]{2}\s*$")

# Column positions match this file format's layout. A different
# broker's export would need these adjusted -- see README for how
# to adapt the parser to a new column layout.
COL_TYPE = 0
COL_ORIGIN = 1
COL_DESTINATION = 2
COL_PICKUP_INFO = 3
COL_MILES = 5
COL_RATE = 6
COL_COLOR = 8


def _looks_like_city(value) -> bool:
    return isinstance(value, str) and bool(CITY_STATE_PATTERN.match(value.strip()))


def _is_numeric(value) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return True  # missing is fine; a row isn't disqualified for a blank number
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _clean_str(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def _clean_float(value) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pickup_info_to_str(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if hasattr(value, "isoformat"):  # datetime/date/Timestamp
        return value.isoformat()
    return str(value).strip() or None


def _row_is_load(row: list) -> bool:
    origin = row[COL_ORIGIN] if len(row) > COL_ORIGIN else None
    if not _looks_like_city(origin):
        return False

    destination = row[COL_DESTINATION] if len(row) > COL_DESTINATION else None
    dest_ok = destination is None or (isinstance(destination, float) and pd.isna(destination)) or _looks_like_city(destination)
    if not dest_ok:
        return False

    miles = row[COL_MILES] if len(row) > COL_MILES else None
    rate = row[COL_RATE] if len(row) > COL_RATE else None
    return _is_numeric(miles) and _is_numeric(rate)


def parse_workbook(file_bytes: bytes) -> ParseResult:
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=0, header=None)
    except Exception as exc:
        raise ValueError(f"Could not read this Excel file: {exc}") from exc

    rows = df.values.tolist()
    loads: list[Load] = []
    skipped = 0

    for raw_row in rows:
        if not _row_is_load(raw_row):
            skipped += 1
            continue

        color = _clean_str(raw_row[COL_COLOR] if len(raw_row) > COL_COLOR else None)

        loads.append(
            Load(
                row_index=len(loads) + 1,
                origin=_clean_str(raw_row[COL_ORIGIN]),
                destination=_clean_str(raw_row[COL_DESTINATION]) if len(raw_row) > COL_DESTINATION else None,
                pickup_info=_pickup_info_to_str(raw_row[COL_PICKUP_INFO]) if len(raw_row) > COL_PICKUP_INFO else None,
                miles=_clean_float(raw_row[COL_MILES]) if len(raw_row) > COL_MILES else None,
                rate=_clean_float(raw_row[COL_RATE]) if len(raw_row) > COL_RATE else None,
                color_status=color.upper() if color else None,
            )
        )

    return ParseResult(loads=loads, skipped_rows=skipped, total_rows_scanned=len(rows))
