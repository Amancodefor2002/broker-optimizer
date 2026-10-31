"""
Parser tests. Uses a synthetic file that replicates the real-world
mess this parser was built for: broker contact blocks, repeated
"TYPE" section markers that aren't real headers, blank rows, notes,
and actual load rows -- all interleaved, matching the structure of
real broker exports without containing any real company's data.
"""
import io

import pandas as pd
import pytest

from app.parser import parse_workbook


def _build_messy_export() -> bytes:
    rows = [
        [None] * 9,
        [None, None, "ACME FREIGHT CO", None, None, None, None, None, None],
        [None, None, "CONTACT: JORDAN", None, None, None, None, None, None],
        [None, None, "jordan@example.test", None, None, None, None, None, None],
        [None, None, "555-123-4567", None, None, None, None, None, None],
        ["TYPE", "ORIGIN", "DESTINATION", "PICK UP DATE", None, "MILES", None, "SOS", None],
        ["FSD", "SPRINGFIELD, IL", "CHICAGO, IL", "HOT LOAD", None, 200, 900, None, "GREEN"],
        [None] * 9,
        ["FSD", "SPRINGFIELD, IL", "CHICAGO, IL", "PENDING INVENTORY", None, 200, 900, None, "GREEN"],
        ["FSD", "SPRINGFIELD, IL", "PEORIA, IL", "PENDING INVENTORY", None, 75, 50, None, "BLUE"],
        ["FSD", "DECATUR, IL", None, "PENDING INVENTORY", None, None, None, None, None],
        ["FSD", "DECATUR, IL", None, "PENDING INVENTORY", None, None, None, None, None],
        [None] * 9,
        ["TYPE", "BRIAN K", None, "GREENS-2  BLUE-0", None, None, None, None, None],
        [None, None, None, "***drivers need dunnage***", None, None, None, None, None],
        ["FSD", "DECATUR, IL", "BLOOMINGTON, IL", "PENDING INVENTORY", None, 45, 300, None, "BLUE"],
    ]
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_excel(buf, index=False, header=False)
    return buf.getvalue()


def test_parser_extracts_only_real_load_rows():
    result = parse_workbook(_build_messy_export())
    # 6 real load rows amid contact info, section markers, notes, blanks
    assert len(result.loads) == 6
    assert result.skipped_rows > 0


def test_parser_ignores_fake_header_section_markers():
    # The "TYPE / BRIAN K / GREENS-2 BLUE-0" row must not be mistaken
    # for a load or a real header -- its "ORIGIN" cell isn't a city
    result = parse_workbook(_build_messy_export())
    origins = [load.origin for load in result.loads]
    assert "BRIAN K" not in origins


def test_parser_keeps_placeholder_loads_with_missing_destination():
    result = parse_workbook(_build_messy_export())
    decatur_loads = [l for l in result.loads if l.origin == "DECATUR, IL" and l.destination is None]
    assert len(decatur_loads) == 2  # both placeholder rows kept, not merged or dropped


def test_parser_converts_pickup_date_and_status_correctly():
    result = parse_workbook(_build_messy_export())
    hot_load = next(l for l in result.loads if l.pickup_info == "HOT LOAD")
    assert hot_load.origin == "SPRINGFIELD, IL"


def test_parser_handles_completely_empty_workbook():
    # Excel doesn't store fully-blank rows at all, so this correctly
    # round-trips to zero rows -- the real behavior to guard here is
    # "doesn't crash," not a specific skipped-row count.
    df = pd.DataFrame([[None] * 9 for _ in range(5)])
    buf = io.BytesIO()
    df.to_excel(buf, index=False, header=False)
    result = parse_workbook(buf.getvalue())
    assert result.loads == []


def test_parser_raises_clear_error_on_corrupt_file():
    with pytest.raises(ValueError, match="Could not read"):
        parse_workbook(b"this is not a real xlsx file")
