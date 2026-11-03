from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .data_loader import load_routes
from .delays import apply_delay, headway_wait_quantiles, predictor_meta
from .models import (
    ConfidenceBand,
    LatLon,
    LegKind,
    PlanConstraints,
    PlanExplanation,
    Quantiles,
    TripLeg,
    TripPlan,
    TripTrace,
)
from .walk_graph import walk_between, walk_graph_meta

TRANSFER_MAX_M = 280.0
TOP_STOPS = 3


def _haversine_m(a: LatLon, b: LatLon) -> float:
    r = 6371000.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dphi = math.radians(b.lat - a.lat)
    dlmb = math.radians(b.lon - a.lon)
    h = (
        math.sin(dphi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(h))


def _stop_ll(stop: dict[str, Any]) -> LatLon:
    return LatLon(lat=float(stop["lat"]), lon=float(stop["lon"]))


def _parse_time(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _walk_q(seconds: float) -> Quantiles:
    return Quantiles(p10_s=seconds * 0.9, p50_s=seconds, p90_s=seconds * 1.15)


def _confidence(horizon_s: float) -> ConfidenceBand:
    if horizon_s < 180:
        return ConfidenceBand(
            horizon_s=horizon_s,
            width_s=max(30.0, horizon_s * 0.25),
            label="near",
            note="Near-term: tight p10–p90 (live bus would tighten further).",
        )
    if horizon_s < 3600:
        return ConfidenceBand(
            horizon_s=horizon_s,
            width_s=horizon_s * 0.35,
            label="mid",
            note="Mid horizon: bands from empirical ETA-bin delay quantiles.",
        )
    return ConfidenceBand(
        horizon_s=horizon_s,
        width_s=horizon_s * 0.55,
        label="far",
        note="Far-term (≥60–90 min): check again closer to departure.",
    )


def _sum_q(*parts: Quantiles) -> Quantiles:
    return Quantiles(
        p10_s=sum(p.p10_s for p in parts),
        p50_s=sum(p.p50_s for p in parts),
        p90_s=sum(p.p90_s for p in parts),
    )


def _p_on_time(total: Quantiles, constraints: PlanConstraints, depart: datetime) -> float:
    if constraints.arrive_by:
        arrive_by = _parse_time(constraints.arrive_by)
        budget = (arrive_by - depart).total_seconds()
        if budget <= total.p10_s:
            return 0.12
        if budget >= total.p90_s:
            return 0.94
        span = max(1.0, total.p90_s - total.p10_s)
        return 0.12 + 0.82 * ((budget - total.p10_s) / span)
    return min(0.95, max(0.55, constraints.prefs.on_time_target - 0.05))


def _leave_by_search(
    total: Quantiles, constraints: PlanConstraints, depart: datetime
) -> tuple[datetime, datetime]:
    arrive_est = depart + timedelta(seconds=total.p50_s)
    if not constraints.arrive_by:
        return depart, arrive_est
    target = constraints.prefs.on_time_target
    arrive_by = _parse_time(constraints.arrive_by)
    lo, hi = arrive_by - timedelta(seconds=total.p90_s + 1800), arrive_by
    best = depart
    for _ in range(16):
        mid = lo + (hi - lo) / 2
        budget = (arrive_by - mid).total_seconds()
        span = max(1.0, total.p90_s - total.p10_s)
        if budget <= total.p10_s:
            p = 0.12
        elif budget >= total.p90_s:
            p = 0.94
        else:
            p = 0.12 + 0.82 * ((budget - total.p10_s) / span)
        if p >= target:
            best = mid
            lo = mid
        else:
            hi = mid
    return best, best + timedelta(seconds=total.p50_s)


def _stop_index(route: dict[str, Any], stop_id: Any) -> int:
    for i, s in enumerate(route.get("stops") or []):
        if s.get("id") == stop_id:
            return i
    return -1


def _ride_segment(
    route: dict[str, Any], board_idx: int, alight_idx: int
) -> tuple[float, list[Any], list[list[float]]]:
    stops = route["stops"]
    n = len(stops)
    if board_idx < 0 or alight_idx < 0 or board_idx == alight_idx or n == 0:
        return 0.0, [], []

    total = 0.0
    ids: list[Any] = []
    geom: list[list[float]] = []
    i = board_idx
    for step in range(n + 1):
        s = stops[i]
        ids.append(s["id"])
        geom.append([float(s["lat"]), float(s["lon"])])
        if i == alight_idx and step > 0:
            return total, ids, geom
        total += float(s.get("to_next") or 60)
        i = (i + 1) % n
    return 0.0, [], []


def _nearest_stops(
    point: LatLon, route: dict[str, Any], k: int = TOP_STOPS
) -> list[tuple[dict[str, Any], float]]:
    ranked = []
    for stop in route.get("stops") or []:
        ranked.append((stop, _haversine_m(point, _stop_ll(stop))))
    ranked.sort(key=lambda x: x[1])
    return ranked[:k]


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _finalize_plan(
    constraints: PlanConstraints,
    depart: datetime,
    legs: list[TripLeg],
    plan_id: str,
    facts: list[str],
    walk_to_s: float,
    wait_p50: float,
) -> TripPlan:
    total = _sum_q(*(leg.duration_s for leg in legs))
    p_on = _p_on_time(total, constraints, depart)
    p_catch = max(0.35, min(0.97, 0.92 - (walk_to_s / 900.0) - (wait_p50 / 2000.0)))
    leave_by, arrive_est = _leave_by_search(total, constraints, depart)
    return TripPlan(
        plan_id=plan_id,
        total_duration_s=total,
        p_on_time=round(p_on, 3),
        p_catch=round(p_catch, 3),
        leave_by=_iso(leave_by),
        arrive_by_est=_iso(arrive_est),
        legs=legs,
        confidence=_confidence(total.p50_s),
        explanation_facts=facts
        + [
            f"total_p50_min={total.p50_s / 60:.1f}",
            f"total_p10_min={total.p10_s / 60:.1f}",
            f"total_p90_min={total.p90_s / 60:.1f}",
            f"p_on_time={p_on:.2f}",
            f"p_catch={p_catch:.2f}",
            "delay_source=data/derived/delay_quantiles.json",
        ],
    )


def _direct_plan(
    constraints: PlanConstraints,
    route: dict[str, Any],
    board: dict[str, Any],
    alight: dict[str, Any],
    depart: datetime,
) -> Optional[tuple[float, TripPlan]]:
    board_idx = _stop_index(route, board["id"])
    alight_idx = _stop_index(route, alight["id"])
    ride_base, stop_ids, geom = _ride_segment(route, board_idx, alight_idx)
    if ride_base <= 0:
        return None

    walk_speed = constraints.prefs.walk_speed_mps
    walk_to = walk_between(constraints.origin, _stop_ll(board), walk_speed)
    walk_from = walk_between(_stop_ll(alight), constraints.destination, walk_speed)
    wait_q = headway_wait_quantiles()
    ride_q = apply_delay(ride_base)
    walk_to_q = _walk_q(walk_to.duration_s)
    walk_from_q = _walk_q(walk_from.duration_s)

    legs = [
        TripLeg(
            kind=LegKind.walk,
            label="Walk to stop",
            duration_s=walk_to_q,
            from_name="Origin",
            to_name=str(board.get("name")),
            geometry=walk_to.geometry,
            explanation=(
                f"~{walk_to.distance_m:.0f} m via {walk_to.method}"
                f"{' (on campus)' if walk_to.on_campus else ''}"
            ),
        ),
        TripLeg(
            kind=LegKind.wait,
            label=f"Wait for {route.get('name')}",
            duration_s=wait_q,
            from_name=str(board.get("name")),
            to_name=str(board.get("name")),
            route_id=str(route.get("id")),
            route_name=str(route.get("name")),
            explanation="Headway prior; live ETA will replace",
        ),
        TripLeg(
            kind=LegKind.ride,
            label=f"Ride {route.get('name')}",
            duration_s=ride_q,
            from_name=str(board.get("name")),
            to_name=str(alight.get("name")),
            route_id=str(route.get("id")),
            route_name=str(route.get("name")),
            stop_ids=stop_ids,
            geometry=geom,
            explanation="Stop-to-stop schedule + ETA-bin delay quantiles",
        ),
        TripLeg(
            kind=LegKind.walk,
            label="Walk to destination",
            duration_s=walk_from_q,
            from_name=str(alight.get("name")),
            to_name="Destination",
            geometry=walk_from.geometry,
            explanation=f"~{walk_from.distance_m:.0f} m via {walk_from.method}",
        ),
    ]
    score = walk_to.duration_s + wait_q.p50_s + ride_q.p50_s + walk_from.duration_s
    plan = _finalize_plan(
        constraints,
        depart,
        legs,
        plan_id=f"plan-direct-{route.get('id')}-{uuid.uuid4().hex[:6]}",
        facts=[
            "mode=direct",
            f"route={route.get('name')}",
            f"board={board.get('name')}",
            f"alight={alight.get('name')}",
            f"walk_method={walk_to.method}",
        ],
        walk_to_s=walk_to.duration_s,
        wait_p50=wait_q.p50_s,
    )
    return score, plan


def _transfer_plan(
    constraints: PlanConstraints,
    route_a: dict[str, Any],
    board: dict[str, Any],
    xfer_off: dict[str, Any],
    route_b: dict[str, Any],
    xfer_on: dict[str, Any],
    alight: dict[str, Any],
    depart: datetime,
) -> Optional[tuple[float, TripPlan]]:
    a_board_i = _stop_index(route_a, board["id"])
    a_off_i = _stop_index(route_a, xfer_off["id"])
    b_on_i = _stop_index(route_b, xfer_on["id"])
    b_alight_i = _stop_index(route_b, alight["id"])
    ride_a, ids_a, geom_a = _ride_segment(route_a, a_board_i, a_off_i)
    ride_b, ids_b, geom_b = _ride_segment(route_b, b_on_i, b_alight_i)
    if ride_a <= 0 or ride_b <= 0:
        return None

    walk_speed = constraints.prefs.walk_speed_mps
    walk_to = walk_between(constraints.origin, _stop_ll(board), walk_speed)
    xfer = walk_between(_stop_ll(xfer_off), _stop_ll(xfer_on), walk_speed)
    walk_from = walk_between(_stop_ll(alight), constraints.destination, walk_speed)
    wait1 = headway_wait_quantiles()
    wait2 = headway_wait_quantiles()
    ride_aq = apply_delay(ride_a)
    ride_bq = apply_delay(ride_b)
    walk_to_q = _walk_q(walk_to.duration_s)
    xfer_q = _walk_q(xfer.duration_s)
    walk_from_q = _walk_q(walk_from.duration_s)

    legs = [
        TripLeg(
            kind=LegKind.walk,
            label="Walk to stop",
            duration_s=walk_to_q,
            from_name="Origin",
            to_name=str(board.get("name")),
            geometry=walk_to.geometry,
            explanation=f"~{walk_to.distance_m:.0f} m via {walk_to.method}",
        ),
        TripLeg(
            kind=LegKind.wait,
            label=f"Wait for {route_a.get('name')}",
            duration_s=wait1,
            from_name=str(board.get("name")),
            route_id=str(route_a.get("id")),
            route_name=str(route_a.get("name")),
        ),
        TripLeg(
            kind=LegKind.ride,
            label=f"Ride {route_a.get('name')}",
            duration_s=ride_aq,
            from_name=str(board.get("name")),
            to_name=str(xfer_off.get("name")),
            route_id=str(route_a.get("id")),
            route_name=str(route_a.get("name")),
            stop_ids=ids_a,
            geometry=geom_a,
        ),
        TripLeg(
            kind=LegKind.transfer_walk,
            label="Transfer walk",
            duration_s=xfer_q,
            from_name=str(xfer_off.get("name")),
            to_name=str(xfer_on.get("name")),
            geometry=xfer.geometry,
            explanation=f"~{xfer.distance_m:.0f} m via {xfer.method}",
        ),
        TripLeg(
            kind=LegKind.wait,
            label=f"Wait for {route_b.get('name')}",
            duration_s=wait2,
            from_name=str(xfer_on.get("name")),
            route_id=str(route_b.get("id")),
            route_name=str(route_b.get("name")),
        ),
        TripLeg(
            kind=LegKind.ride,
            label=f"Ride {route_b.get('name')}",
            duration_s=ride_bq,
            from_name=str(xfer_on.get("name")),
            to_name=str(alight.get("name")),
            route_id=str(route_b.get("id")),
            route_name=str(route_b.get("name")),
            stop_ids=ids_b,
            geometry=geom_b,
        ),
        TripLeg(
            kind=LegKind.walk,
            label="Walk to destination",
            duration_s=walk_from_q,
            from_name=str(alight.get("name")),
            to_name="Destination",
            geometry=walk_from.geometry,
            explanation=f"~{walk_from.distance_m:.0f} m via {walk_from.method}",
        ),
    ]
    score = (
        walk_to.duration_s
        + wait1.p50_s
        + ride_aq.p50_s
        + xfer.duration_s
        + wait2.p50_s
        + ride_bq.p50_s
        + walk_from.duration_s
        + 90.0
    )
    plan = _finalize_plan(
        constraints,
        depart,
        legs,
        plan_id=f"plan-xfer-{route_a.get('id')}-{route_b.get('id')}-{uuid.uuid4().hex[:6]}",
        facts=[
            "mode=transfer",
            f"route_a={route_a.get('name')}",
            f"route_b={route_b.get('name')}",
            f"board={board.get('name')}",
            f"transfer={xfer_off.get('name')}→{xfer_on.get('name')}",
            f"alight={alight.get('name')}",
            f"transfer_m={xfer.distance_m:.0f}",
            f"walk_method={walk_to.method}",
        ],
        walk_to_s=walk_to.duration_s,
        wait_p50=wait1.p50_s,
    )
    return score, plan


def plan_trip(constraints: PlanConstraints) -> TripTrace:
    routes = load_routes()
    depart = _parse_time(constraints.depart_at)
    candidates: list[tuple[float, TripPlan]] = []

    # Direct single-route options (top boarding / alighting stops per route)
    for route in routes:
        for board, d_board in _nearest_stops(constraints.origin, route):
            for alight, d_alight in _nearest_stops(constraints.destination, route):
                if board["id"] == alight["id"]:
                    continue
                built = _direct_plan(constraints, route, board, alight, depart)
                if built:
                    candidates.append(built)

    # One-transfer options between distinct routes (best nearby hubs only)
    for route_a in routes:
        boards = _nearest_stops(constraints.origin, route_a, k=2)
        for route_b in routes:
            if route_a.get("id") == route_b.get("id"):
                continue
            alights = _nearest_stops(constraints.destination, route_b, k=2)
            hubs: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
            for xfer_off in route_a.get("stops") or []:
                for xfer_on in route_b.get("stops") or []:
                    xfer_m = _haversine_m(_stop_ll(xfer_off), _stop_ll(xfer_on))
                    if xfer_m <= TRANSFER_MAX_M:
                        hubs.append((xfer_m, xfer_off, xfer_on))
            hubs.sort(key=lambda x: x[0])
            # Keep transfer fan-out small — walk Dijkstra is the hot path
            for xfer_m, xfer_off, xfer_on in hubs[:2]:
                for board, d_board in boards[:1]:
                    if board["id"] == xfer_off["id"]:
                        continue
                    for alight, d_alight in alights[:1]:
                        if alight["id"] == xfer_on["id"]:
                            continue
                        built = _transfer_plan(
                            constraints,
                            route_a,
                            board,
                            xfer_off,
                            route_b,
                            xfer_on,
                            alight,
                            depart,
                        )
                        if built:
                            candidates.append(built)

    # Keep best unique-ish plans; reserve room for both direct and transfer
    candidates.sort(key=lambda x: x[0])
    deduped: list[tuple[float, TripPlan]] = []
    seen: set[str] = set()
    direct_n = 0
    transfer_n = 0

    def _try_add(score: float, plan: TripPlan, *, mode: str, limit: int, counter_name: str) -> None:
        nonlocal direct_n, transfer_n
        count = direct_n if counter_name == "direct" else transfer_n
        if count >= limit:
            return
        if not plan.explanation_facts or plan.explanation_facts[0] != mode:
            return
        key = "|".join(plan.explanation_facts[:4])
        if key in seen:
            return
        seen.add(key)
        deduped.append((score, plan))
        if counter_name == "direct":
            direct_n += 1
        else:
            transfer_n += 1

    for score, plan in candidates:
        _try_add(score, plan, mode="mode=direct", limit=5, counter_name="direct")
        _try_add(score, plan, mode="mode=transfer", limit=4, counter_name="transfer")
        if direct_n >= 5 and transfer_n >= 4:
            break
    deduped.sort(key=lambda x: x[0])

    if not deduped:
        walk = walk_between(
            constraints.origin,
            constraints.destination,
            constraints.prefs.walk_speed_mps,
        )
        q = _walk_q(walk.duration_s)
        walk_plan = TripPlan(
            plan_id=f"plan-walk-{uuid.uuid4().hex[:8]}",
            total_duration_s=q,
            p_on_time=0.9,
            p_catch=1.0,
            leave_by=_iso(depart),
            arrive_by_est=_iso(depart + timedelta(seconds=walk.duration_s)),
            legs=[
                TripLeg(
                    kind=LegKind.walk,
                    label="Walk only",
                    duration_s=q,
                    from_name="Origin",
                    to_name="Destination",
                    geometry=walk.geometry,
                    explanation=f"No useful shuttle segment; {walk.distance_m:.0f} m via {walk.method}",
                )
            ],
            confidence=_confidence(walk.duration_s),
            explanation_facts=[
                "mode=walk_only",
                f"distance_m={walk.distance_m:.0f}",
                f"walk_method={walk.method}",
                f"total_p50_min={walk.duration_s / 60:.1f}",
            ],
        )
        deduped = [(walk.duration_s, walk_plan)]

    chosen = deduped[0][1]
    # Mix alternatives: up to 2 direct + at least 1 transfer when available
    rest = [p for _, p in deduped[1:] if p.plan_id != chosen.plan_id]
    directs = [p for p in rest if p.explanation_facts[:1] == ["mode=direct"]]
    transfers = [p for p in rest if p.explanation_facts[:1] == ["mode=transfer"]]
    alts: list[TripPlan] = []
    alts.extend(directs[:2])
    if transfers:
        alts.append(transfers[0])
    for p in rest:
        if len(alts) >= 3:
            break
        if p.plan_id in {a.plan_id for a in alts}:
            continue
        alts.append(p)
    alts = alts[:3]

    pred = predictor_meta()
    quantile_source = (
        f"{pred.get('predictor')} · {pred.get('delay_table')} "
        "(ETA-bin empirical delays blended with stinger-delay summary)"
    )
    walk_method = next(
        (f.split("=", 1)[1] for f in chosen.explanation_facts if f.startswith("walk_method=")),
        "stop_corridor_dijkstra",
    )

    def _attach_explain(plan: TripPlan, *, chosen_flag: bool, alts_for_cmp: list[TripPlan]) -> TripPlan:
        route_ids = sorted(
            {str(leg.route_id) for leg in plan.legs if leg.route_id is not None}
        )
        route_names = sorted(
            {str(leg.route_name) for leg in plan.legs if leg.route_name is not None}
        )
        stop_names = []
        stop_ids: list[Any] = []
        for leg in plan.legs:
            if leg.kind in (LegKind.ride, LegKind.wait) and leg.from_name:
                stop_names.append(str(leg.from_name))
            if leg.kind == LegKind.ride and leg.to_name:
                stop_names.append(str(leg.to_name))
            stop_ids.extend(leg.stop_ids or [])
        # unique preserve order
        seen_n: set[str] = set()
        stop_names_u = []
        for n in stop_names:
            if n not in seen_n:
                seen_n.add(n)
                stop_names_u.append(n)

        mode = plan.explanation_facts[0] if plan.explanation_facts else "unknown"
        why = [
            f"Selected {mode} with p50 {plan.total_duration_s.p50_s / 60:.1f} min",
            f"Confidence band={plan.confidence.label} (width {plan.confidence.width_s / 60:.1f} min)",
            f"Walk legs use {walk_method} over stop+corridor graph",
            f"Ride delays from {quantile_source}",
        ]
        if mode == "mode=direct":
            why.append("Beat transfer options on expected time (includes transfer wait penalty)")
        elif mode == "mode=transfer":
            why.append("No competitive single-route path for this OD; transfer hubs within 280 m")

        compared = []
        for alt in alts_for_cmp[:3]:
            delta = (alt.total_duration_s.p50_s - plan.total_duration_s.p50_s) / 60
            amode = alt.explanation_facts[0] if alt.explanation_facts else "alt"
            compared.append(
                f"{amode}: +{delta:.1f} min p50 vs chosen (p_on_time={alt.p_on_time:.2f})"
            )

        polylines: list[dict[str, Any]] = []
        for leg in plan.legs:
            if not leg.geometry or len(leg.geometry) < 2:
                continue
            if leg.kind in (LegKind.walk, LegKind.transfer_walk):
                polylines.append(
                    {
                        "kind": leg.kind.value,
                        "label": leg.label,
                        "coords": leg.geometry,  # [[lat, lon], ...]
                        "color": "#f0c75e" if leg.kind == LegKind.walk else "#e8a87c",
                    }
                )
            elif leg.kind == LegKind.ride:
                polylines.append(
                    {
                        "kind": "ride",
                        "label": leg.label,
                        "coords": leg.geometry,
                        "color": None,  # twin uses route color
                        "route_id": leg.route_id,
                        "route_name": leg.route_name,
                    }
                )

        plan.explain = PlanExplanation(
            summary=(
                f"{'Chosen' if chosen_flag else 'Alternative'} plan rides "
                f"{', '.join(route_names) or 'walk'} in "
                f"{plan.total_duration_s.p50_s / 60:.1f} min (p50)."
            ),
            why_chosen=why if chosen_flag else why[:2],
            quantile_source=quantile_source,
            walk_method=walk_method,
            compared_to_alts=compared if chosen_flag else [],
            highlight={
                "route_ids": route_ids,
                "route_names": route_names,
                "stop_names": stop_names_u,
                "stop_ids": stop_ids,
                "polylines": polylines,
            },
        )
        return plan

    chosen = _attach_explain(chosen, chosen_flag=True, alts_for_cmp=alts)
    alts = [_attach_explain(a, chosen_flag=False, alts_for_cmp=[]) for a in alts]

    allowed: list[float] = []
    for plan in [chosen, *alts]:
        allowed.extend(
            [
                round(plan.total_duration_s.p10_s / 60, 1),
                round(plan.total_duration_s.p50_s / 60, 1),
                round(plan.total_duration_s.p90_s / 60, 1),
                round(plan.p_on_time, 2),
                round(plan.p_catch, 2),
            ]
        )
        for leg in plan.legs:
            allowed.extend(
                [
                    round(leg.duration_s.p10_s / 60, 1),
                    round(leg.duration_s.p50_s / 60, 1),
                    round(leg.duration_s.p90_s / 60, 1),
                ]
            )

    meta = {
        "routes_considered": len(routes),
        "candidates_scored": len(candidates),
        "transfer_max_m": TRANSFER_MAX_M,
        **predictor_meta(),
        **walk_graph_meta(),
        # Cheap stubs until API keys exist
        "integrations_todo": [
            "Grok Voice Agent — needs xAI key",
            "Google Calendar next-event — needs OAuth",
            "X social uncertainty — needs bearer token",
        ],
    }

    return TripTrace(
        request_id=str(uuid.uuid4()),
        mode="heuristic",
        constraints=constraints,
        chosen=chosen,
        alternatives=alts,
        allowed_numbers=sorted(set(allowed)),
        meta=meta,
        explain=chosen.explain,
    )
