import pytest

from app import geocode


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch, tmp_path):
    """Tests never call the real Nominatim API and never touch the real cache file."""

    def offline(_query):
        raise geocode.requests.ConnectionError("network is disabled in tests")

    monkeypatch.setattr(geocode, "_query_nominatim", offline)
    monkeypatch.setattr(geocode, "ONLINE_CACHE_PATH", tmp_path / "geocode_cache.json")
