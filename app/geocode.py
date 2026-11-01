"""
City -> coordinates lookup.

Every load needs a position on the map, and backhaul matching needs real
distances. The first version asked the free Nominatim API about every
unique city, one request per second, so a 300-load board took minutes.

Now there are three layers, fastest first:
1. An offline table of ~36,000 US places (app/data/us_cities.csv, built
   by scripts/build_city_table.py), with forgiving spelling: "ST LOUIS",
   "St. Louis" and "SAINT LOUIS" are one key, as are "LA PORTE" and
   "LAPORTE".
2. Typo matching against the same table, within the same state
   ("ABLIENE,TX" -> Abilene, TX). Corrections are reported back so the
   broker can check them.
3. Nominatim (OpenStreetMap) for the few names still unknown, usually
   tiny places such as quarry or plant towns. Capped per upload,
   rate-limited, cached, and a result in the wrong state is rejected.
Anything still unknown is reported as unresolved, never guessed.
"""
from __future__ import annotations

import csv
import difflib
import json
import re
import time
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import requests

from app.models import CityCorrection, GeocodeReport, Load

CITY_TABLE_PATH = Path(__file__).parent / "data" / "us_cities.csv"
ONLINE_CACHE_PATH = Path(__file__).parent.parent / "geocode_cache.json"

# How similar (0 to 1) a misspelt name must be to a real town before we
# accept the match. Measured on the real load boards: at 0.85 all 22
# typos were fixed. In a simulation where a real town is missing from
# the table, 0.85 wrongly matched it to another town ~3% of the time
# (0.80 did so ~11% of the time), so 0.85 is the trade-off chosen.
TYPO_MATCH_CUTOFF = 0.85

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "broker-load-optimizer/1.0 (+https://github.com/Amancodefor2002/broker-optimizer)"
MAX_ONLINE_LOOKUPS = 10  # new names per upload; Nominatim's free tier allows ~1 request per second

_ABBREVIATIONS = {
    "ST": "SAINT", "STE": "SAINTE", "FT": "FORT", "MT": "MOUNT", "PT": "POINT",
    "N": "NORTH", "S": "SOUTH", "E": "EAST", "W": "WEST",
}


def city_key(city: str) -> str:
    """'St. Louis', 'ST LOUIS' and 'Saint Louis' all become 'SAINTLOUIS'."""
    ascii_text = unicodedata.normalize("NFKD", city).encode("ascii", "ignore").decode()  # Cañon -> Canon
    words = re.sub(r"[^A-Z ]", " ", ascii_text.upper()).split()  # drop dots, apostrophes, hyphens
    return "".join(_ABBREVIATIONS.get(word, word) for word in words)  # no spaces: LA PORTE == LAPORTE


@dataclass(frozen=True)
class Place:
    name: str  # "Abilene, TX"
    lat: float
    lon: float


# ---------- layers 1 and 2: offline table ----------

@lru_cache(maxsize=1)
def _load_table() -> tuple[dict[tuple[str, str], Place], dict[str, list[str]]]:
    """Reads the city table once, on first use."""
    places: dict[tuple[str, str], Place] = {}
    keys_by_state: dict[str, list[str]] = {}
    with CITY_TABLE_PATH.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            key, state = city_key(row["city"]), row["state"]
            places[(key, state)] = Place(f"{row['city']}, {state}", float(row["lat"]), float(row["lon"]))
            keys_by_state.setdefault(state, []).append(key)
    return places, keys_by_state


@lru_cache(maxsize=4096)
def lookup_city(text: str) -> tuple[Place, bool] | None:
    """
    Finds a "City, ST" string in the offline table. Returns
    (place, was_corrected), or None when it can't be identified with confidence.
    """
    city, _, state = text.rpartition(",")
    state = state.strip().upper()
    key = city_key(city)
    if not key or len(state) != 2:
        return None

    places, keys_by_state = _load_table()
    if (key, state) in places:
        return places[(key, state)], False

    # Typo fallback: only towns in the same state that start with the same letter.
    candidates = [k for k in keys_by_state.get(state, []) if k[0] == key[0]]
    best = difflib.get_close_matches(key, candidates, n=1, cutoff=TYPO_MATCH_CUTOFF)
    if best:
        return places[(best[0], state)], True
    return None


# ---------- layer 3: online fallback ----------

def _query_nominatim(query: str) -> list[dict]:
    resp = requests.get(
        NOMINATIM_URL,
        params={
            "q": query, "format": "jsonv2", "limit": 1, "countrycodes": "us",
            "addressdetails": 1, "featureType": "settlement",  # towns and villages only, not streets
        },
        headers={"User-Agent": NOMINATIM_USER_AGENT},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def lookup_city_online(text: str) -> Place | None:
    """
    Asks Nominatim about a "City, ST" string. Returns None when nothing is
    found in that state. Raises requests.RequestException if it can't be reached.
    """
    state = text.rpartition(",")[2].strip().upper()
    results = _query_nominatim(text)
    if not results:
        return None
    top = results[0]
    if top.get("address", {}).get("ISO3166-2-lvl4") != f"US-{state}":
        return None  # found a place, but in another state: don't guess
    return Place(f"{top.get('name') or text}, {state}", float(top["lat"]), float(top["lon"]))


def _read_online_cache() -> dict:
    try:
        return json.loads(ONLINE_CACHE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _write_online_cache(cache: dict) -> None:
    try:
        ONLINE_CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True))
    except OSError:
        pass  # the cache only saves time; losing it is harmless


def _lookup_unknown_online(names: list[str]) -> dict[str, Place]:
    """Tries Nominatim for names the table doesn't know. Answers (including 'not found') are cached."""
    cache = _read_online_cache()
    found: dict[str, Place] = {}
    calls = 0
    for name in names:
        if name not in cache:
            if calls >= MAX_ONLINE_LOOKUPS:
                continue  # the rest get tried on a later upload
            if calls:
                time.sleep(1.0)  # Nominatim's usage policy: at most 1 request per second
            calls += 1
            try:
                place = lookup_city_online(name)
            except (requests.RequestException, ValueError, KeyError):
                break  # service unreachable or odd reply: don't make the broker wait on every city
            cache[name] = [place.name, place.lat, place.lon] if place else None
        if cache[name]:
            found[name] = Place(*cache[name])
    if calls:
        _write_online_cache(cache)
    return found


# ---------- used by the API ----------

def attach_coordinates(loads: list[Load]) -> GeocodeReport:
    """Sets lat/lon on every load (in place) and reports what was corrected or not found."""
    names = {load.origin for load in loads} | {load.destination for load in loads if load.destination}
    found: dict[str, Place] = {}
    corrections: list[CityCorrection] = []
    unknown: list[str] = []

    for name in sorted(names):
        hit = lookup_city(name)
        if hit is None:
            unknown.append(name)
            continue
        place, corrected = hit
        found[name] = place
        if corrected:
            corrections.append(CityCorrection(original=name, matched=place.name))

    if unknown:
        found.update(_lookup_unknown_online(unknown))

    for load in loads:
        if load.origin in found:
            load.origin_lat, load.origin_lon = found[load.origin].lat, found[load.origin].lon
        if load.destination in found:
            load.destination_lat, load.destination_lon = found[load.destination].lat, found[load.destination].lon

    return GeocodeReport(corrected=corrections, unresolved=[n for n in unknown if n not in found])
