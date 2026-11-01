"""
FastAPI entrypoint for the broker load board tool.

Endpoints:
  POST /api/parse             -- upload a broker export, get back clean loads (with map coordinates) + flags + rate stats
  POST /api/backhaul-match     -- given already-parsed loads, compute backhaul matches
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
    result = match_backhauls(req.loads)

    return {
        "backhaul_result": result.model_dump(),
        "geocode_failures": geocoding.unresolved,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")
