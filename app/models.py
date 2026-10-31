"""
Data models for the broker load board tool.

Kept close to what actually appears in real broker exports (see
parser.py for why): a Load doesn't assume a clean depot/stop
structure -- it's a standalone point-to-point shipment, which is
what a load board actually posts.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class Load(BaseModel):
    row_index: int  # 1-based position among parsed loads, for referencing in flags/matches
    origin: str
    destination: str | None = None  # None when a load is posted with no destination yet
    pickup_info: str | None = None  # either a real date (as ISO string) or a status like "HOT LOAD"
    miles: float | None = None
    rate: float | None = None
    color_status: str | None = None  # broker's own priority tag, e.g. GREEN / BLUE

    origin_lat: float | None = None
    origin_lon: float | None = None
    destination_lat: float | None = None
    destination_lon: float | None = None


class ParseResult(BaseModel):
    loads: list[Load]
    skipped_rows: int = Field(description="Rows that looked like notes/headers/contact info, not loads")
    total_rows_scanned: int


class ValidationFlag(BaseModel):
    row_index: int
    flag_type: str  # "duplicate" | "missing_destination" | "missing_rate" | "missing_miles"
    detail: str


class ValidationReport(BaseModel):
    flags: list[ValidationFlag]
    duplicate_count: int
    missing_field_count: int


class RateStat(BaseModel):
    row_index: int
    rate_per_mile: float | None
    is_outlier: bool
    outlier_reason: str | None = None


class RateAnalysis(BaseModel):
    stats: list[RateStat]
    average_rate_per_mile: float
    median_rate_per_mile: float
    outlier_count: int


class BackhaulMatch(BaseModel):
    from_load_row: int
    to_load_row: int
    deadhead_miles: float


class BackhaulResult(BaseModel):
    matches: list[BackhaulMatch]
    unmatched_load_rows: list[int]
    total_deadhead_miles: float
