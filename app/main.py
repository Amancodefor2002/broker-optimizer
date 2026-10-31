"""
FastAPI entrypoint for the broker load board tool.

Endpoints:
  POST /api/parse             -- upload a broker export, get back clean loads + flags + rate stats
  POST /api/backhaul-match     -- given already-parsed loads, geocode and compute backhaul matches
  GET  /                       -- serves the demo frontend

Run locally with:
  uvicorn app.main:app --reload
"""
from __future__ import annotations

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.backhaul import match_backhauls
from app.geocode import geocode_cities
from app.models import Load
from app.parser import parse_workbook
from app.rate_analysis import analyze_rates
from app.validation import validate_loads

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


@app.post("/api/parse")
async def parse_endpoint(file: UploadFile = File(...)) -> dict:
    file_bytes = await file.read()
    try:
        result = parse_workbook(file_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    validation = validate_loads(result.loads)
    rates = analyze_rates(result.loads)

    return {
        "loads": [load.model_dump() for load in result.loads],
        "skipped_rows": result.skipped_rows,
        "total_rows_scanned": result.total_rows_scanned,
        "validation": validation.model_dump(),
        "rate_analysis": rates.model_dump(),
    }


class BackhaulRequest(BaseModel):
    loads: list[Load]


@app.post("/api/backhaul-match")
async def backhaul_endpoint(req: BackhaulRequest) -> dict:
    loads = req.loads

    cities = set()
    for load in loads:
        cities.add(load.origin)
        if load.destination:
            cities.add(load.destination)

    geocoded = geocode_cities(cities)

    for load in loads:
        origin_coords = geocoded.get(load.origin)
        if origin_coords:
            load.origin_lat, load.origin_lon = origin_coords
        if load.destination:
            dest_coords = geocoded.get(load.destination)
            if dest_coords:
                load.destination_lat, load.destination_lon = dest_coords

    result = match_backhauls(loads)
    geocode_failures = [
        city for city in cities if geocoded.get(city) is None
    ]

    return {
        "backhaul_result": result.model_dump(),
        "geocode_failures": geocode_failures,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse("frontend/index.html")
