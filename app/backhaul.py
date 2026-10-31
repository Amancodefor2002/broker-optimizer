"""
Backhaul (deadhead) matching.

The problem: after a truck delivers Load A to its destination, it's
empty until it picks up its next load. If the next load's origin is
far from where the truck just was, those are wasted, unpaid miles
("deadhead"). A dispatcher wants to chain loads so trucks stay full
as much as possible.

This is a minimum-cost bipartite assignment problem: match each
load's destination (a "drop-off point") to another load's origin （a
"pick-up point"), minimizing total distance across all matches. It's
the same category of problem as the CVRP solver in the original
routing project (both are handed to a combinatorial optimizer rather
than solved by hand), but a genuinely different shape -- CVRP builds
routes visiting many stops with one vehicle; this matches pairs of
independent loads to each other.

Why a "null match" trick instead of leaving loads unmatched directly:
OR-Tools' SimpleLinearSumAssignment solves *complete* bipartite
matching -- every left node must map to some right node. Real data
means not every load has a good next match nearby. The fix: allow
each load to "match to itself" at a fixed penalty cost representing
"stay idle, no backhaul." The solver then only proposes a real match
when it's cheaper than idling, and self-matches show up as
legitimately unmatched loads in the result.
"""
from __future__ import annotations

import math

from app.models import BackhaulMatch, BackhaulResult, Load

EARTH_RADIUS_KM = 6371.0
KM_TO_MILES = 0.621371

# Cost (in scaled integer units) representing "don't chain this load to
# anything -- leave the truck idle instead." Any real match cheaper
# than this gets proposed instead. Tune this to how much deadhead a
# broker considers acceptable before an empty truck is preferable.
NULL_MATCH_PENALTY_MILES = 300.0
DISTANCE_SCALE = 100  # integer cost units per mile, for solver precision


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1, rlon1, rlat2, rlon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    h = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    km = 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))
    return km * KM_TO_MILES


def match_backhauls(loads: list[Load]) -> BackhaulResult:
    # Only loads with both endpoints geocoded can be matched.
    matchable = [
        load
        for load in loads
        if load.destination_lat is not None
        and load.destination_lon is not None
        and load.origin_lat is not None
        and load.origin_lon is not None
    ]

    if len(matchable) < 2:
        return BackhaulResult(matches=[], unmatched_load_rows=[l.row_index for l in matchable], total_deadhead_miles=0.0)

    try:
        from ortools.graph.python import linear_sum_assignment
    except ImportError as exc:
        raise RuntimeError("OR-Tools is required for backhaul matching") from exc

    n = len(matchable)
    assignment = linear_sum_assignment.SimpleLinearSumAssignment()

    for i in range(n):
        for j in range(n):
            if i == j:
                cost_miles = NULL_MATCH_PENALTY_MILES
            else:
                cost_miles = haversine_miles(
                    matchable[i].destination_lat,
                    matchable[i].destination_lon,
                    matchable[j].origin_lat,
                    matchable[j].origin_lon,
                )
            assignment.add_arc_with_cost(i, j, round(cost_miles * DISTANCE_SCALE))

    status = assignment.solve()
    if status != assignment.OPTIMAL:
        raise RuntimeError(f"Backhaul assignment solver did not find an optimal solution (status={status})")

    matches: list[BackhaulMatch] = []
    unmatched: list[int] = []
    total_deadhead = 0.0

    for i in range(n):
        j = assignment.right_mate(i)
        deadhead_miles = assignment.assignment_cost(i) / DISTANCE_SCALE
        if i == j:
            unmatched.append(matchable[i].row_index)
        else:
            matches.append(
                BackhaulMatch(
                    from_load_row=matchable[i].row_index,
                    to_load_row=matchable[j].row_index,
                    deadhead_miles=round(deadhead_miles, 1),
                )
            )
            total_deadhead += deadhead_miles

    return BackhaulResult(matches=matches, unmatched_load_rows=unmatched, total_deadhead_miles=round(total_deadhead, 1))
