from app.models import Load
from app.rate_analysis import analyze_rates


def test_computes_rate_per_mile_correctly():
    loads = [Load(row_index=1, origin="A, IL", destination="B, IL", miles=100, rate=400)]
    analysis = analyze_rates(loads)
    assert analysis.stats[0].rate_per_mile == 4.0


def test_flags_statistical_outliers():
    # 9 loads clustered around $2/mi, one wildly different
    loads = [
        Load(row_index=i, origin="A, IL", destination="B, IL", miles=100, rate=200)
        for i in range(1, 10)
    ]
    loads.append(Load(row_index=10, origin="A, IL", destination="B, IL", miles=100, rate=5000))
    analysis = analyze_rates(loads)
    outliers = [s for s in analysis.stats if s.is_outlier]
    assert len(outliers) == 1
    assert outliers[0].row_index == 10


def test_missing_rate_or_miles_excluded_from_stats_not_crashed():
    loads = [
        Load(row_index=1, origin="A, IL", destination="B, IL", miles=100, rate=400),
        Load(row_index=2, origin="A, IL", destination=None, miles=None, rate=None),
    ]
    analysis = analyze_rates(loads)
    assert analysis.stats[1].rate_per_mile is None
    assert analysis.stats[1].is_outlier is False


def test_empty_loads_list_does_not_crash():
    analysis = analyze_rates([])
    assert analysis.stats == []
    assert analysis.average_rate_per_mile == 0.0


def test_zero_miles_does_not_cause_division_error():
    loads = [Load(row_index=1, origin="A, IL", destination="B, IL", miles=0, rate=400)]
    analysis = analyze_rates(loads)
    assert analysis.stats[0].rate_per_mile is None
