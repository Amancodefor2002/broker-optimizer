"""
Builds app/data/us_cities.csv, the offline city table used by app/geocode.py.

Run from the repo root (needs internet and `pip install geonamescache`):
    python -m scripts.build_city_table

Two sources, merged on the same key the app uses at runtime
(app.geocode.city_key), so "St. Louis" and "SAINT LOUIS" can't end up
as two different rows:
1. GeoNames US places with population >= 500: city-centre coordinates.
   When a state has two places with the same name, the bigger one wins.
2. kelvins/US-Cities-Database: USPS-style names ("Mc Calla",
   "Ft Mitchell") that fill in places GeoNames doesn't have.
Licences for both are in app/data/SOURCES.md.
"""
from __future__ import annotations

import csv
import io
import urllib.request

import geonamescache

from app.geocode import CITY_TABLE_PATH, city_key

KELVINS_CSV_URL = "https://raw.githubusercontent.com/kelvins/US-Cities-Database/main/csv/us_cities.csv"


def build() -> list[tuple[str, str, float, float]]:
    best: dict[tuple[str, str], tuple[str, float, float, int]] = {}

    for c in geonamescache.GeonamesCache(min_city_population=500).get_cities().values():
        if c["countrycode"] != "US":
            continue
        key = (city_key(c["name"]), c["admin1code"])
        if key not in best or c["population"] > best[key][3]:
            best[key] = (c["name"], c["latitude"], c["longitude"], c["population"])

    with urllib.request.urlopen(KELVINS_CSV_URL, timeout=60) as resp:
        text = resp.read().decode("utf-8")
    for row in csv.DictReader(io.StringIO(text)):
        key = (city_key(row["CITY"]), row["STATE_CODE"])
        if key not in best:  # GeoNames wins when both sources have the place
            best[key] = (row["CITY"], float(row["LATITUDE"]), float(row["LONGITUDE"]), 0)

    rows = [(name, state, round(lat, 4), round(lon, 4)) for (_, state), (name, lat, lon, _) in best.items()]
    rows.sort(key=lambda r: (r[1], r[0]))
    return rows


def main() -> None:
    rows = build()
    CITY_TABLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CITY_TABLE_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["city", "state", "lat", "lon"])
        writer.writerows(rows)
    print(f"Wrote {len(rows)} places to {CITY_TABLE_PATH}")


if __name__ == "__main__":
    main()
