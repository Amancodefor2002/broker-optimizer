import pytest

from app import geocode
from app.geocode import attach_coordinates, city_key, lookup_city
from app.models import Load


def test_spelling_variants_share_one_key():
    assert city_key("ST. LOUIS") == city_key("Saint Louis") == city_key("st louis")
    assert city_key("LA PORTE") == city_key("LAPORTE")
    assert city_key("FT WORTH") == city_key("Fort Worth")
    assert city_key("Cañon City") == city_key("CANON CITY")


def test_finds_a_known_city():
    place, corrected = lookup_city("CHICAGO, IL")
    assert not corrected
    assert place.lat == pytest.approx(41.85, abs=0.2)
    assert place.lon == pytest.approx(-87.65, abs=0.2)


def test_same_name_in_different_states_are_different_places():
    illinois, _ = lookup_city("SPRINGFIELD, IL")
    missouri, _ = lookup_city("SPRINGFIELD, MO")
    assert abs(illinois.lon - missouri.lon) > 1


@pytest.mark.parametrize(
    "typo, expected",
    [
        ("ABLIENE,TX", "Abilene, TX"),
        ("ZANSVILLE, OH", "Zanesville, OH"),
        # Nashville is just as close by spelling, but a typo rarely changes the first letter
        ("ASHVILLE, NC", "Asheville, NC"),
    ],
)
def test_fixes_typos_seen_in_real_exports(typo, expected):
    place, corrected = lookup_city(typo)
    assert corrected
    assert place.name == expected


def test_does_not_guess_unknown_or_malformed_cities():
    assert lookup_city("NOWHEREVILLE, TX") is None
    assert lookup_city("CHICAGO") is None  # no state


def test_attach_coordinates_reports_corrections_and_failures():
    loads = [
        Load(row_index=1, origin="CHICAGO, IL", destination="ABLIENE,TX"),
        Load(row_index=2, origin="NOWHEREVILLE, TX"),
    ]
    report = attach_coordinates(loads)

    assert loads[0].origin_lat is not None and loads[0].destination_lat is not None
    assert loads[0].destination_place == "Abilene, TX"  # the matched name, for display
    assert loads[1].origin_lat is None and loads[1].origin_place is None
    assert [c.matched for c in report.corrected] == ["Abilene, TX"]
    assert report.unresolved == ["NOWHEREVILLE, TX"]


def _nominatim_reply(state_code):
    return [{"name": "Spofford", "lat": "29.17", "lon": "-100.41", "address": {"ISO3166-2-lvl4": state_code}}]


def test_tiny_town_missing_from_table_is_found_online_then_cached(monkeypatch):
    queries = []

    def fake_nominatim(query):
        queries.append(query)
        return _nominatim_reply("US-TX")

    monkeypatch.setattr(geocode, "_query_nominatim", fake_nominatim)
    loads = [Load(row_index=1, origin="SPOFFORD, TX", destination="CHICAGO, IL")]
    report = attach_coordinates(loads)
    assert loads[0].origin_lat == pytest.approx(29.17)
    assert report.unresolved == []

    attach_coordinates([Load(row_index=2, origin="SPOFFORD, TX")])  # second upload
    assert queries == ["SPOFFORD, TX"]  # answered from the cache, no second request


def test_online_result_in_another_state_is_rejected(monkeypatch):
    monkeypatch.setattr(geocode, "_query_nominatim", lambda query: _nominatim_reply("US-NH"))
    assert geocode.lookup_city_online("SPOFFORD, TX") is None


def test_unreachable_online_service_leaves_city_unresolved():
    # conftest.py makes every network call fail
    report = attach_coordinates([Load(row_index=1, origin="SPOFFORD, TX")])
    assert report.unresolved == ["SPOFFORD, TX"]


def test_cache_entries_from_the_first_version_are_looked_up_again(monkeypatch):
    geocode.ONLINE_CACHE_PATH.write_text('{"SPOFFORD, TX": [29.17, -100.41]}')  # old [lat, lon] shape
    monkeypatch.setattr(geocode, "_query_nominatim", lambda query: _nominatim_reply("US-TX"))
    loads = [Load(row_index=1, origin="SPOFFORD, TX")]
    report = attach_coordinates(loads)
    assert report.unresolved == []
    assert loads[0].origin_place == "Spofford, TX"
