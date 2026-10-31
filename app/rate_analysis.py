"""
Rate analysis: computes $/mile per load and flags outliers.

Outlier method: flag a load if its rate-per-mile falls outside
mean +/- 1.5 standard deviations of all loads that have both rate
and miles. This is a simple, explainable statistical method (not a
fixed dollar threshold), so it self-adjusts to whatever a given
broker's actual rate distribution looks like, rather than hardcoding
a "good" or "bad" rate that would be wrong for a different lane
length or market.

Loads missing rate or miles are excluded from the average/median and
get is_outlier=False (there's nothing to flag -- validation.py
already surfaces missing-field loads separately).
"""
from __future__ import annotations

import statistics

from app.models import Load, RateAnalysis, RateStat

OUTLIER_STD_MULTIPLIER = 1.5


def analyze_rates(loads: list[Load]) -> RateAnalysis:
    per_mile: dict[int, float] = {}
    for load in loads:
        if load.rate is not None and load.miles is not None and load.miles > 0:
            per_mile[load.row_index] = load.rate / load.miles

    if not per_mile:
        # No load has usable rate+miles data -- still emit one
        # (empty) stat per load rather than an empty list, so callers
        # can align stats to loads 1:1 regardless of data quality.
        stats = [RateStat(row_index=load.row_index, rate_per_mile=None, is_outlier=False) for load in loads]
        return RateAnalysis(stats=stats, average_rate_per_mile=0.0, median_rate_per_mile=0.0, outlier_count=0)

    stats: list[RateStat] = []

    values = list(per_mile.values())
    mean = statistics.mean(values)
    median = statistics.median(values)
    stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
    lower_bound = mean - OUTLIER_STD_MULTIPLIER * stdev
    upper_bound = mean + OUTLIER_STD_MULTIPLIER * stdev

    outlier_count = 0
    for load in loads:
        rpm = per_mile.get(load.row_index)
        if rpm is None:
            stats.append(RateStat(row_index=load.row_index, rate_per_mile=None, is_outlier=False))
            continue

        is_outlier = rpm < lower_bound or rpm > upper_bound
        reason = None
        if is_outlier:
            outlier_count += 1
            reason = (
                f"${rpm:.2f}/mi is {'below' if rpm < lower_bound else 'above'} "
                f"the normal range (${lower_bound:.2f}-${upper_bound:.2f}/mi)"
            )

        stats.append(RateStat(row_index=load.row_index, rate_per_mile=round(rpm, 3), is_outlier=is_outlier, outlier_reason=reason))

    return RateAnalysis(
        stats=stats,
        average_rate_per_mile=round(mean, 3),
        median_rate_per_mile=round(median, 3),
        outlier_count=outlier_count,
    )
