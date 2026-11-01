import pytest

from app.models import Load
from app.next_loads import rank_next_loads

# Points on the equator, where one degree of longitude is about 69.1 miles,
# so empty-mile distances are easy to reason about.
DELIVERY = (0.0, 0.0)


def _just_delivered(row_index=1):
    return Load(row_index=row_index, origin="START, TX", destination="HERE, TX",
                origin_lat=0.0, origin_lon=-5.0, destination_lat=DELIVERY[0], destination_lon=DELIVERY[1])


def _option(row_index, pickup_lon, rate, miles):
    return Load(row_index=row_index, origin=f"P{row_index}, TX", destination=f"D{row_index}, TX",
                rate=rate, miles=miles, origin_lat=0.0, origin_lon=pickup_lon, destination_lat=1.0, destination_lon=pickup_lon)


def test_a_nearby_cheaper_load_beats_a_far_pricier_one():
    near = _option(2, pickup_lon=0.29, rate=900, miles=200)    # ~20 empty miles
    far = _option(3, pickup_lon=3.62, rate=1000, miles=200)    # ~250 empty miles
    ranked = rank_next_loads([_just_delivered(), near, far])[1]

    assert [o.row_index for o in ranked] == [2, 3]
    assert ranked[0].effective_rate_per_mile == pytest.approx(900 / (20 + 200), rel=0.01)
    assert ranked[1].effective_rate_per_mile == pytest.approx(1000 / (250 + 200), rel=0.01)


def test_loads_too_far_away_are_not_offered():
    too_far = _option(2, pickup_lon=6.0, rate=5000, miles=100)  # ~415 empty miles
    assert rank_next_loads([_just_delivered(), too_far])[1] == []


def test_loads_that_cannot_be_priced_or_placed_are_skipped():
    no_rate = _option(2, pickup_lon=0.1, rate=None, miles=200)
    no_miles = _option(3, pickup_lon=0.1, rate=900, miles=None)
    off_map = Load(row_index=4, origin="NOWHERE, TX", rate=900, miles=200)
    ranked = rank_next_loads([_just_delivered(), no_rate, no_miles, off_map])[1]
    assert ranked == []


def test_a_load_is_never_its_own_next_load_and_only_the_best_few_are_kept():
    current = _just_delivered()
    current.rate, current.miles = 800, 100
    current.origin_lon = 0.0  # it even starts where it ends
    others = [_option(i, pickup_lon=0.1 * i, rate=1000, miles=200) for i in range(2, 8)]
    ranked = rank_next_loads([current, *others], top_n=3)[1]
    assert len(ranked) == 3
    assert 1 not in [o.row_index for o in ranked]
