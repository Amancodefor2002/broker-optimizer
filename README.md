# Broker load board optimizer

A tool for freight brokers that takes a real (messy) "Available Loads"
Excel export, cleans it, flags data problems, analyzes pricing, and
suggests backhaul matches to cut empty (deadhead) miles between loads.

## Why this project

This started as a generic vehicle-routing (CVRP) demo, then pivoted
after looking at a real broker load board export. That file didn't
fit the CVRP model at all — no depot, no delivery stops, just
independent point-to-point loads a broker is trying to fill and route
efficiently. This project targets that actual problem instead.

## The core problem, precisely

Freight brokers manually export load boards from their dispatch
software into Excel. These exports are not clean tables — they're
built by hand over time and mix:
- Actual load rows (origin, destination, pickup info, miles, rate)
- Dispatcher/broker contact blocks
- Load-count summaries ("GREENS-5 BLUE-1")
- Free-text driver instructions
- Blank rows, inconsistent formatting

A broker doing this by eye misses duplicate postings, underpriced
loads, and backhaul opportunities simply because there's too much
noise to scan manually across hundreds of rows.

## Architecture

```
app/
  models.py          Pydantic schemas for Load, validation flags, rate stats, matches
  parser.py           Pattern-based extraction of load rows from messy exports
  validation.py        Duplicate detection + missing-field flagging
  rate_analysis.py     $/mile computation and statistical outlier detection
  geocode.py            "City, ST" -> coordinates: offline table, typo matching, online fallback
  backhaul.py            Deadhead-minimizing assignment via OR-Tools
  next_loads.py          Best next loads for one truck, ranked by effective $/mile
  main.py                 FastAPI routes wiring it together
  data/us_cities.csv      ~36,000 US places for offline lookups (sources: data/SOURCES.md)
frontend/
  index.html               Dashboard: upload, map of every lane, flagged table, next-load suggestion
  vendor/leaflet/          Leaflet 1.9.4 map library (BSD-2), bundled so the page needs no CDN
scripts/
  build_city_table.py      Rebuilds data/us_cities.csv from its two sources
tests/
  test_parser.py           Extraction correctness on a realistic messy fixture
  test_validation.py       Duplicate/missing-field logic, including edge cases
  test_rate_analysis.py    Outlier detection, division-by-zero safety
  test_backhaul.py         Assignment correctness on synthetic geometric cases
  test_next_loads.py       Ranking by effective $/mile, distance cut-off, unpriceable loads
  test_geocode.py          Spelling variants, typo correction, online fallback (network faked)
  test_api.py              Upload -> parse -> match through the HTTP API
samples/
  sample_load_board.xlsx   Synthetic file replicating the real messy structure
```

## Key design decisions (and why)

**Why pattern-based row detection instead of reading from a header row?**
The real export this was built against has "TYPE" appearing at the
start of many rows throughout the file, but only one of those is an
actual column header — the rest are section markers with completely
different content each time (broker names, load-count summaries).
Position-based parsing ("read from wherever the header is") breaks
immediately here. Instead, every row is classified by what its
content looks like — an origin matching "City, ST" plus
numeric-or-empty miles/rate — regardless of where it sits in the
file. This trades recall (it will miss a load row shaped unlike
anything it recognizes) for precision (what it does extract is
reliably a real load, not noise).

**Why does duplicate detection ignore loads with no destination/rate?**
A first version flagged every row sharing an origin as a duplicate —
which incorrectly flagged legitimate separate loads (a broker often
posts several available loads from the same origin before a
destination or rate is assigned yet). Duplicate detection only
compares loads that have enough identifying detail (destination AND
rate) to actually mean something. This was caught by testing against
the real data, not assumed correct from the start.

**Why statistical outlier detection (mean ± 1.5 std) instead of a fixed
$/mile threshold?**
A fixed threshold (e.g. "flag anything under $2/mi") would be wrong
for a different broker's typical rates or a different mix of lane
lengths. Computing the threshold from the data itself adapts to
whatever this particular load board's actual distribution looks like.

**Why OR-Tools' linear sum assignment for backhaul matching, not a
greedy nearest-neighbor?**
This is a genuinely different optimization shape from the original
CVRP work (a single vehicle visiting many stops) — here it's matching
pairs of independent loads to minimize *total* deadhead across all of
them simultaneously. A greedy "match each load to its nearest
available option" can lock in a bad global outcome by claiming the
best match for an early load that a later load needed more. A global
assignment solver avoids that.

**Why can a load "match to itself" in the assignment?**
OR-Tools' `SimpleLinearSumAssignment` requires every left node to map
to some right node — it doesn't have a native "leave this one
unmatched" option. The fix: each load can match to itself at a fixed
penalty cost (`NULL_MATCH_PENALTY_MILES`, currently 300mi) representing
"stay idle instead of chaining." The solver only proposes a real match
when it beats that penalty, and self-matches in the result mean
"legitimately left unmatched," not a bug.

**Why rank next loads per truck when the matcher already pairs loads?**
The two answer different questions. The matcher minimises empty miles
for the whole fleet at once. A dispatcher looking at one truck asks
which load pays *that truck* best after its delivery, which is
measured by effective rate per mile:

    next load's rate / (empty miles to its pickup + its loaded miles)

Plain $/mile hides the empty drive: a $1,000 load 250 empty miles away
pays $2.22 per mile driven, while a $900 load 20 miles away pays $4.09.
On the real board, the best-paying next load and the fleet-wide pick
were the same load for only 6 of 185 loads, so the dashboard shows the
top three options and says when the fleet-wide plan would choose
differently, rather than hiding either view.

**How do city names become map coordinates?**
The first version sent every unique city to the free Nominatim API,
one request per second, so a 300-load board took minutes. Now there
are three layers, fastest first:
1. An offline table of ~36,000 US places, looked up in memory.
   Spelling variants share one key: "ST LOUIS", "St. Louis" and
   "SAINT LOUIS" are the same city, and so are "LA PORTE" and "LAPORTE".
2. Typo matching within the same state ("ABLIENE,TX" → Abilene, TX).
   Every correction is returned so the broker can check it.
3. Nominatim, only for the few names still unknown (usually tiny
   quarry or plant towns): at most 10 new names per upload, 1 request
   a second, cached, and rejected if the result is in another state.

On the two real load boards (510 loads, 347 distinct city strings),
319 matched the table exactly, 22 typos were corrected and 6 were left
for the online layer. Parsing plus city lookup now takes under a second.

**Why a 0.85 similarity cutoff for typo matching?**
It was measured, not picked. At 0.85 all 22 typos in the real files
were fixed. To estimate the risk, real towns were hidden from the table
to see how often the matcher would map them to a *different* town:
about 3% of the time at 0.85, against about 11% at 0.80. Candidates
must also start with the same letter, because a typo rarely changes
the first letter: "ASHVILLE, NC" is as close to Nashville as to
Asheville by spelling alone.

## Known limitations

- **The parser's column layout is tuned to one broker's export
  format.** A different broker's spreadsheet with columns in a
  different order would need the column indices in `parser.py`
  adjusted. This is a genuine limitation, not a "works on anything"
  claim.
- **Rate outlier detection doesn't account for lane length.**
  Short-haul loads naturally have higher $/mile than long-haul loads
  because of fixed costs — a single global mean/stdev across all
  loads will flag some legitimately-priced short hauls as "outliers."
  A better version would bucket loads by distance range before
  computing outlier bounds. This was observed directly when testing
  against real data, not theoretical.
- **Deadhead matching only considers geography, not timing.** Two
  loads might be geographically perfect for chaining but have pickup
  dates that make it physically impossible. A production version
  would need to factor in pickup/delivery windows.
- **City lookup is US-only and can still miss tiny places.** Names the
  offline table doesn't know depend on the online layer, which is
  capped at 10 new names per upload. Anything it can't confirm is
  reported as unresolved rather than guessed, so those loads don't
  appear on the map or in matching.
- **Distances are straight-line, not road miles.** Empty miles between
  loads are measured "as the crow flies", so real driving distance is
  longer. A routing API would fix this at the cost of speed and an
  external dependency.
- **On a board from only a few shippers, most "next loads" are return
  trips.** The real board this was tested on has 328 loads from just 14
  pickup cities, so the best next load is usually another load from
  the same plant, reached by driving back empty. True backhauls need
  loads that start near where trucks deliver.
- **The map's background needs internet.** Lanes and cities are drawn
  locally; the street map behind them comes from OpenStreetMap's tile
  servers.

## Running it

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --reload-dir app
# open http://127.0.0.1:8000
```

Test immediately with the bundled synthetic sample: click
**Upload load board** and pick `samples/sample_load_board.xlsx`. Click
any load to see its route, the empty drive to its next load, and that
next load on the map.

To adapt this to your own broker's export format, check `parser.py`'s
`COL_*` constants against your actual column layout first.

Run tests:

```bash
pytest tests/ -v
```

## API

- `POST /api/parse` — multipart upload, field name `file`. Accepts
  `.xlsx`/`.xls`. Returns `{loads, skipped_rows, total_rows_scanned,
  geocoding: {corrected, unresolved}, validation, rate_analysis}`.
  Each load comes back with `origin_lat/lon` and `destination_lat/lon`
  filled in wherever the city was found.
- `POST /api/backhaul-match` — body: `{loads: [...]}` (the exact
  `loads` array from `/api/parse`). Returns
  `{backhaul_result: {matches, unmatched_load_rows,
  total_deadhead_miles}, next_load_options, geocode_failures}`.
  `next_load_options` maps each load's row number (as a string) to up
  to three `{row_index, empty_miles, effective_rate_per_mile}` options,
  best first.
- `GET /health`
