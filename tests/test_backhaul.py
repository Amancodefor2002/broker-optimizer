from app.backhaul import NULL_MATCH_PENALTY_MILES, match_backhauls
from app.models import Load


def _load(row_index, origin, dest, origin_ll, dest_ll):
    return Load(
        row_index=row_index,
        origin=origin,
        destination=dest,
        origin_lat=origin_ll[0],
        origin_lon=origin_ll[1],
        destination_lat=dest_ll[0],
        destination_lon=dest_ll[1],
    )


def test_finds_perfect_chain_with_zero_deadhead():
    # Three loads forming a closed loop: A->B, B->C, C->A
    loads = [
        _load(1, "A", "B", (0.0, 0.0), (1.0, 0.0)),
        _load(2, "B", "C", (1.0, 0.0), (2.0, 0.0)),
        _load(3, "C", "A", (2.0, 0.0), (0.0, 0.0)),
    ]
    result = match_backhauls(loads)
    assert result.total_deadhead_miles == 0.0
    assert len(result.unmatched_load_rows) == 0
    assert len(result.matches) == 3


def test_leaves_isolated_load_unmatched_when_no_reasonable_chain_exists():
    # Two loads geographically close, one far away (~1000+ miles)
    loads = [
        _load(1, "A", "B", (40.0, -87.0), (40.1, -87.0)),
        _load(2, "B", "A", (40.1, -87.0), (40.0, -87.0)),
        _load(3, "Far", "FarB", (10.0, 10.0), (10.1, 10.0)),
    ]
    result = match_backhauls(loads)
    assert 3 in result.unmatched_load_rows


def test_null_match_penalty_prevents_absurd_matches():
    # Only two loads, very far apart -- forcing a match would be worse
    # than leaving both idle
    loads = [
        _load(1, "A", "B", (0.0, 0.0), (0.0, 0.0)),
        _load(2, "C", "D", (80.0, 0.0), (80.0, 0.0)),
    ]
    result = match_backhauls(loads)
    assert len(result.matches) == 0
    assert set(result.unmatched_load_rows) == {1, 2}


def test_loads_without_geocoded_coordinates_are_excluded():
    loads = [
        Load(row_index=1, origin="A", destination="B"),  # no coords
        _load(2, "C", "D", (0.0, 0.0), (1.0, 0.0)),
    ]
    result = match_backhauls(loads)
    assert result.unmatched_load_rows == [2]
    assert result.matches == []


def test_fewer_than_two_matchable_loads_returns_empty_result():
    loads = [_load(1, "A", "B", (0.0, 0.0), (1.0, 0.0))]
    result = match_backhauls(loads)
    assert result.matches == []
    assert result.total_deadhead_miles == 0.0
