"""
Validation of parsed loads.

Two kinds of problems get flagged, and deliberately not auto-fixed:
1. Duplicates -- the same origin/destination/rate/miles combination
   posted more than once. Real load boards accumulate these when a
   dispatcher copy-pastes a block or re-posts an unfilled load.
2. Missing fields -- destination, rate, or miles absent. These aren't
   necessarily errors (a load can legitimately be posted before a
   destination is assigned), but a broker needs to see them to know
   which loads aren't ready to quote yet.

Flagging instead of silently dropping or filling in a guess matters
here specifically: a dropped duplicate might have been an
intentional re-post at a different rate, and a filled-in destination
would just be wrong.
"""
from __future__ import annotations

from app.models import Load, ValidationFlag, ValidationReport


def validate_loads(loads: list[Load]) -> ValidationReport:
    flags: list[ValidationFlag] = []
    seen: dict[tuple, int] = {}  # (origin, destination, rate, miles) -> first row_index

    for load in loads:
        # Duplicate detection only makes sense once a load has enough
        # identifying detail to distinguish it from another. Multiple
        # loads posted from the same origin with no destination/rate
        # yet are separate available loads, not copy-paste duplicates
        # -- flagging those as "duplicate" would just be noise.
        if load.destination is not None and load.rate is not None:
            key = (load.origin, load.destination, load.rate, load.miles)
            if key in seen:
                flags.append(
                    ValidationFlag(
                        row_index=load.row_index,
                        flag_type="duplicate",
                        detail=f"Same as row {seen[key]}: {load.origin} -> {load.destination}, ${load.rate}",
                    )
                )
            else:
                seen[key] = load.row_index

        if load.destination is None:
            flags.append(
                ValidationFlag(
                    row_index=load.row_index,
                    flag_type="missing_destination",
                    detail=f"Load from {load.origin} has no destination assigned yet",
                )
            )
        if load.rate is None:
            flags.append(
                ValidationFlag(
                    row_index=load.row_index,
                    flag_type="missing_rate",
                    detail=f"Load {load.origin} -> {load.destination or '?'} has no rate",
                )
            )
        if load.miles is None:
            flags.append(
                ValidationFlag(
                    row_index=load.row_index,
                    flag_type="missing_miles",
                    detail=f"Load {load.origin} -> {load.destination or '?'} has no mileage",
                )
            )

    duplicate_count = sum(1 for f in flags if f.flag_type == "duplicate")
    missing_field_count = sum(1 for f in flags if f.flag_type != "duplicate")

    return ValidationReport(flags=flags, duplicate_count=duplicate_count, missing_field_count=missing_field_count)
