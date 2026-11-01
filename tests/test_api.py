"""End-to-end checks through the HTTP API, the way the dashboard uses it."""
from pathlib import Path

from fastapi.testclient import TestClient

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
    assert "matches" in res.json()["backhaul_result"]


def test_rejects_a_file_that_is_not_excel():
    res = client.post("/api/parse", files={"file": ("notes.txt", b"hello")})
    assert res.status_code == 422
