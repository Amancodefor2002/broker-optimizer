"""End-to-end checks through the HTTP API, the way the dashboard uses it."""
from pathlib import Path

from fastapi.testclient import TestClient

from app import main
from app.main import app

client = TestClient(app)
SAMPLE = Path(__file__).parent.parent / "samples" / "sample_load_board.xlsx"


def _parse_sample() -> dict:
    with SAMPLE.open("rb") as f:
        res = client.post("/api/parse", files={"file": ("sample.xlsx", f)})
    assert res.status_code == 200
    return res.json()


def test_upload_returns_loads_with_map_coordinates():
    body = _parse_sample()
    assert body["loads"]
    assert all(load["origin_lat"] is not None for load in body["loads"])
    assert body["geocoding"]["unresolved"] == []


def test_backhaul_matching_runs_on_parsed_loads():
    loads = _parse_sample()["loads"]
    res = client.post("/api/backhaul-match", json={"loads": loads})
    assert res.status_code == 200
    body = res.json()
    assert "matches" in body["backhaul_result"]
    options = body["next_load_options"]
    assert options, "loads with a delivery city should get next-load options"
    for opts in options.values():
        rates = [o["effective_rate_per_mile"] for o in opts]
        assert rates == sorted(rates, reverse=True)  # best pay per mile first


def test_rejects_a_file_that_is_not_excel():
    res = client.post("/api/parse", files={"file": ("notes.txt", b"hello")})
    assert res.status_code == 422


def test_rejects_a_file_over_the_size_limit(monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 10)
    res = client.post("/api/parse", files={"file": ("huge.xlsx", b"x" * 11)})
    assert res.status_code == 413
    assert "5 MB" in res.json()["detail"]


def test_dashboard_and_its_map_library_are_served():
    page = client.get("/")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-cache"  # browsers always fetch the latest dashboard
    assert "/static/vendor/leaflet/leaflet.js" in page.text
    assert client.get("/static/vendor/leaflet/leaflet.js").status_code == 200
    assert client.get("/static/vendor/leaflet/leaflet.css").status_code == 200
