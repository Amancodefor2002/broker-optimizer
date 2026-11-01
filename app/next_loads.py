"""
Next-load options for one truck, ranked by what the truck earns.

The backhaul matcher (backhaul.py) answers a fleet-wide question: pair
loads so the total empty miles across all trucks is as small as
possible. A dispatcher looking at one truck asks something else: "this
truck just delivered; which load pays it best next?"

That is answered with the effective rate per mile:

    next load's rate / (empty miles to its pickup + its loaded miles)

Plain $/mile ignores the empty drive. A $1,000 load 250 empty miles
away pays $2.22 per mile actually driven (1000 / (250 + 200)), while a
$900 load 20 miles away pays $4.09 (900 / (20 + 200)). Every load that
could follow is scored this way and the best few are kept.
"""
from __future__ import annotations

from app.backhaul import NULL_MATCH_PENALTY_MILES, haversine_miles
from app.models import Load, NextLoadOption

# Same "too far to be worth it" line the matcher uses before it prefers
# leaving a truck free.
MAX_EMPTY_MILES = NULL_MATCH_PENALTY_MILES
OPTIONS_PER_LOAD = 3


def rank_next_loads(
    loads: list[Load],
    max_empty_miles: float = MAX_EMPTY_MILES,
    top_n: int = OPTIONS_PER_LOAD,
) -> dict[int, list[NextLoadOption]]:
    """For every load whose delivery city is on the map: the best-paying loads a truck could take next."""
    # A load can only be offered if it can be priced: pickup on the map, a rate, and loaded miles.
    candidates = [l for l in loads if l.origin_lat is not None and l.rate is not None and l.miles]

    options: dict[int, list[NextLoadOption]] = {}
    for current in loads:
        if current.destination_lat is None:
            continue
        scored: list[NextLoadOption] = []
        for nxt in candidates:
            if nxt.row_index == current.row_index:
                continue
            empty = haversine_miles(current.destination_lat, current.destination_lon, nxt.origin_lat, nxt.origin_lon)
            if empty > max_empty_miles:
                continue
            scored.append(
                NextLoadOption(
                    row_index=nxt.row_index,
                    empty_miles=round(empty, 1),
                    effective_rate_per_mile=round(nxt.rate / (empty + nxt.miles), 3),
                )
            )
        # Best pay per mile first; on a tie, the shorter empty drive wins.
        scored.sort(key=lambda o: (-o.effective_rate_per_mile, o.empty_miles))
        options[current.row_index] = scored[:top_n]
    return options
