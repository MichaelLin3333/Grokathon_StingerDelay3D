from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .data_loader import data_root, load_routes
from .models import (
    HealthResponse,
    PlanConstraints,
    TripTrace,
    VerifyRequest,
    VerifyResponse,
)
from .planner import plan_trip

app = FastAPI(
    title="StingerD-Grok Planner API",
    version="0.1.0",
    description="Deterministic TripTrace planner backbone for Stinger Delay + Grok.",
)

app.add_middleware(
    CORSMiddleware,
    # Vite proxies /api same-origin in normal use; keep CORS open for direct :8000 hits.
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    routes = load_routes()
    return HealthResponse(
        status="ok",
        service="stingerd-grok-api",
        routes_loaded=len(routes),
        data_root=str(data_root()),
    )


@app.get("/routes")
def list_routes():
    routes = load_routes()
    return [
        {
            "id": r.get("id"),
            "name": r.get("name"),
            "color": r.get("color"),
            "stop_count": len(r.get("stops") or []),
        }
        for r in routes
    ]


@app.post("/trips/plan", response_model=TripTrace)
def trips_plan(constraints: PlanConstraints) -> TripTrace:
    """Return a TripTrace — sole numeric source for UI / Grok."""
    return plan_trip(constraints)


@app.post("/trips/verify", response_model=VerifyResponse)
def trips_verify(body: VerifyRequest) -> VerifyResponse:
    """Reject numbers that are not in the TripTrace allowed set (within tolerance)."""
    matched: list[float] = []
    rejected: list[float] = []
    for claimed in body.claimed_numbers:
        ok = any(
            abs(claimed - allowed) <= body.tolerance
            or abs(claimed - allowed) <= max(body.tolerance, abs(allowed) * 0.01)
            for allowed in body.allowed_numbers
        )
        (matched if ok else rejected).append(claimed)
    return VerifyResponse(
        ok=len(rejected) == 0,
        matched=matched,
        rejected=rejected,
        note="Grok may only speak matched numbers; use template fallback if rejected.",
    )
