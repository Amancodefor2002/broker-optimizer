"""
City-level geocoding with a persistent cache.

A real broker export like this one has hundreds of load rows but far
fewer *unique* cities (this dataset: 328 loads, ~220 unique cities).
Geocoding is done once per unique city name, cached to disk as JSON,
and reused on every subsequent run -- without this, re-running the
matcher would re-geocode the same "CHICAGO, IL" dozens of times
against a rate-limited free API for no reason.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "broker-load-optimizer-demo/1.0"
CACHE_PATH = Path(__file__).parent.parent / "geocode_cache.json"


def _load_cache() -> dict[str, list[float] | None]:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text())
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache, indent=2))


def geocode_city(city: str, cache: dict | None = None) -> tuple[float, float] | None:
    """
    Geocodes a "City, ST" string. Pass a shared cache dict across many
    calls (see geocode_cities) to avoid a disk read/write per city.
    """
    owns_cache = cache is None
    if cache is None:
        cache = _load_cache()

    if city in cache:
        cached = cache[city]
        return tuple(cached) if cached is not None else None

    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": city, "format": "json", "limit": 1, "countrycodes": "us"},
            headers={"User-Agent": NOMINATIM_USER_AGENT},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
        coords = (float(results[0]["lat"]), float(results[0]["lon"])) if results else None
    except (requests.RequestException, KeyError, ValueError, IndexError):
        coords = None
    finally:
        time.sleep(1.0)  # Nominatim's free-tier rate limit is ~1 req/sec

    cache[city] = list(coords) if coords else None
    if owns_cache:
        _save_cache(cache)

    return coords


def geocode_cities(cities: set[str]) -> dict[str, tuple[float, float] | None]:
    """Geocodes many cities at once, sharing one cache load/save."""
    cache = _load_cache()
    results = {}
    for city in cities:
        results[city] = geocode_city(city, cache=cache)
    _save_cache(cache)
    return results
