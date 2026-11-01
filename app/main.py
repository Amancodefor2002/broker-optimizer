"""
FastAPI entrypoint for the broker load board tool.

Endpoints:
  POST /api/parse             -- upload a broker export, get back clean loads (with map coordinates) + flags + rate stats
  POST /api/backhaul-match     -- given already-parsed loads, compute fleet-wide matches + best next loads per truck
  GET  /                       -- serves the demo frontend

Run locally with:
  uvicorn app.main:app --reload --reload-dir app
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.backhaul import match_backhauls
from app.geocode import attach_coordinates
from app.models import Load
from app.next_loads import rank_next_loads
from app.parser import parse_workbook
from app.rate_analysis import analyze_rates
from app.validation import validate_loads

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"  # works whichever folder the server starts from

app = FastAPI(
    title="Broker Load Board Optimizer",
    description="Parses, validates, and optimizes freight broker load boards",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Plain `def`, not `async def`: FastAPI then runs each request in a worker thread,
# so slow work (online city lookups, the solver) can't freeze the server for other users.
@app.post("/api/parse")
def parse_endpoint(file: UploadFile = File(...)) -> dict:
    file_bytes = file.file.read()
    try:
        result = parse_workbook(file_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    geocoding = attach_coordinates(result.loads)  # every load gets lat/lon now, so the map can draw right away
    validation = validate_loads(result.loads)
    rates = analyze_rates(result.loads)

    return {
        "loads": [load.model_dump() for load in result.loads],
        "skipped_rows": result.skipped_rows,
        "total_rows_scanned": result.total_rows_scanned,
        "geocoding": geocoding.model_dump(),
        "validation": validation.model_dump(),
        "rate_analysis": rates.model_dump(),
    }


class BackhaulRequest(BaseModel):
    loads: list[Load]


@app.post("/api/backhaul-match")
def backhaul_endpoint(req: BackhaulRequest) -> dict:
    # Look coordinates up again on the server rather than trusting what the client sent back.
    geocoding = attach_coordinates(req.loads)
    result = match_backhauls(req.loads)  # fleet-wide: fewest empty miles across all trucks
    options = rank_next_loads(req.loads)  # per truck: best pay per mile driven

    return {
        "backhaul_result": result.model_dump(),
        # JSON object keys are strings, so row numbers arrive as "6", "7", ...
        "next_load_options": {str(row): [o.model_dump() for o in opts] for row, opts in options.items()},
        "geocode_failures": geocoding.unresolved,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    # "no-cache" = the browser must check for a newer page every time (it still
    # gets a quick "not modified" when nothing changed). Without it, browsers
    # can keep showing an old version of the dashboard after an update.
    return FileResponse(FRONTEND_DIR / "index.html", headers={"Cache-Control": "no-cache"})
