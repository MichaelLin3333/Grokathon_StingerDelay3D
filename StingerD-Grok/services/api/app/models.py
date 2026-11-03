from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class LegKind(str, Enum):
    walk = "walk"
    wait = "wait"
    ride = "ride"
    transfer_walk = "transfer_walk"


class LatLon(BaseModel):
    lat: float
    lon: float


class PlanPrefs(BaseModel):
    avoid_stairs: bool = False
    walk_speed_mps: float = Field(default=1.35, ge=0.5, le=2.5)
    on_time_target: float = Field(default=0.85, ge=0.5, le=0.99)


class PlanConstraints(BaseModel):
    origin: LatLon
    destination: LatLon
    depart_at: Optional[str] = Field(
        default=None, description="ISO-8601; defaults to now (UTC)"
    )
    arrive_by: Optional[str] = Field(
        default=None, description="ISO-8601 arrive-by constraint"
    )
    prefs: PlanPrefs = Field(default_factory=PlanPrefs)


class Quantiles(BaseModel):
    p10_s: float
    p50_s: float
    p90_s: float


class TripLeg(BaseModel):
    kind: LegKind
    label: str
    duration_s: Quantiles
    from_name: Optional[str] = None
    to_name: Optional[str] = None
    route_id: Optional[str] = None
    route_name: Optional[str] = None
    stop_ids: list[Any] = Field(default_factory=list)
    geometry: list[list[float]] = Field(
        default_factory=list, description="[[lat, lon], ...]"
    )
    explanation: Optional[str] = None


class ConfidenceBand(BaseModel):
    horizon_s: float
    width_s: float
    label: Literal["near", "mid", "far"]
    note: str


class PlanExplanation(BaseModel):
    summary: str
    why_chosen: list[str] = Field(default_factory=list)
    quantile_source: str
    walk_method: str
    compared_to_alts: list[str] = Field(default_factory=list)
    highlight: dict[str, Any] = Field(
        default_factory=dict,
        description="Hints for 3D twin: route_ids, route_names, stop_names, stop_ids",
    )


class TripPlan(BaseModel):
    plan_id: str
    total_duration_s: Quantiles
    p_on_time: float
    p_catch: float
    leave_by: Optional[str] = None
    arrive_by_est: Optional[str] = None
    legs: list[TripLeg]
    confidence: ConfidenceBand
    explanation_facts: list[str] = Field(default_factory=list)
    explain: Optional[PlanExplanation] = None


class TripTrace(BaseModel):
    """Deterministic planner output — sole source of numeric values."""

    request_id: str
    mode: Literal["live", "replay", "heuristic"] = "heuristic"
    constraints: PlanConstraints
    chosen: TripPlan
    alternatives: list[TripPlan] = Field(default_factory=list)
    allowed_numbers: list[float] = Field(
        default_factory=list,
        description="Numbers Grok may speak; verification set",
    )
    meta: dict[str, Any] = Field(default_factory=dict)
    explain: Optional[PlanExplanation] = None


class HealthResponse(BaseModel):
    status: str
    service: str
    routes_loaded: int
    data_root: str


class VerifyRequest(BaseModel):
    """Check that spoken/displayed numbers come from a TripTrace."""

    allowed_numbers: list[float]
    claimed_numbers: list[float]
    tolerance: float = Field(default=0.05, ge=0.0, le=1.0)


class VerifyResponse(BaseModel):
    ok: bool
    matched: list[float]
    rejected: list[float]
    note: str
