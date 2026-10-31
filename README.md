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
  geocode.py            City geocoding with a persistent disk cache
  backhaul.py            Deadhead-minimizing assignment via OR-Tools
  main.py                 FastAPI routes wiring it together
frontend/
  index.html    Dashboard — upload, parsed table with flags, backhaul results
tests/
  test_parser.py           Extraction correctness on a realistic messy fixture
  test_validation.py       Duplicate/missing-field logic, including edge cases
  test_rate_analysis.py    Outlier detection, division-by-zero safety
  test_backhaul.py         Assignment correctness on synthetic geometric cases
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

**Why cache geocoding results to disk?**
This dataset has 328 loads but only ~220 unique cities. Without
caching, re-running the matcher would re-geocode "CHICAGO, IL" dozens
of times against a rate-limited free API (~1 req/sec) for no reason.
The cache (`geocode_cache.json`) persists across runs.

## Known limitations

- **The parser's column layout is tuned to one broker's export
  format.** A different broker's spreadsheet with columns in a
  different order would need the column indices in `parser.py`
  adjusted. This is a genuine limitation, not a "works on anything"
  claim — 
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
- **Geocoding uses free Nominatim, rate-limited to ~1 req/sec.** A
  broker running this on a large board for the first time (before
  the cache warms up) will see a real wait — a paid geocoding API
  would remove this bottleneck.

## Running it

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
# open http://127.0.0.1:8000
```

Test immediately with the bundled synthetic sample:
`samples/sample_load_board.xlsx` — click "Parse loads" and pick it.

To adapt this to your own broker's export format, check `parser.py`'s
`COL_*` constants against your actual column layout first.

Run tests:

```bash
pytest tests/ -v
```

## API

- `POST /api/parse` — multipart upload, field name `file`. Accepts
  `.xlsx`/`.xls`. Returns `{loads, skipped_rows, total_rows_scanned,
  validation, rate_analysis}`.
- `POST /api/backhaul-match` — body: `{loads: [...]}` (the exact
  `loads` array from `/api/parse`). Geocodes and returns
  `{backhaul_result: {matches, unmatched_load_rows,
  total_deadhead_miles}, geocode_failures}`.
- `GET /health`
