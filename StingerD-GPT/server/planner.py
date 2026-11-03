"""Deterministic replay-first travel planner.

Geometry and vehicle passage times are from the upstream campus twin. Walking is
an explicitly approximate great-circle estimate with a detour multiplier, not an
accessibility graph. Uncertainty is a seeded demo model, NOT calibrated ML.
"""
from __future__ import annotations

import bisect
import copy
import hashlib
import json
import math
import random
import threading
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from server import walking

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("America/New_York")
VERSION = "v0"
SAMPLES = 192
_TRACE_CACHE = OrderedDict()
_CACHE_LOCK = threading.Lock()

PLACES = json.loads((ROOT / "data/places.json").read_text())


def places():
    return copy.deepcopy(PLACES)


def search_places(query, limit=8):
    import difflib
    query = str(query or '').strip().lower()
    if not query:
        return PLACES[:limit]
    def score(place):
        name = place['name'].lower()
        if query in [name, place['id']]:
            return 1.0
        if query in name:
            return .9 + (.05 if place.get('kind') == 'landmark' else 0)
        return difflib.SequenceMatcher(None, query, name).ratio()
    results = sorted(((score(p), p) for p in PLACES), key=lambda pair: -pair[0])
    return [{**p, 'score': round(s, 3)} for s, p in results[:limit] if s >= .45]


def haversine(a, b):
    la, lo, lb, lob = map(math.radians, [a[0], a[1], b[0], b[1]])
    q = math.sin((lb - la) / 2) ** 2 + math.cos(la) * math.cos(lb) * math.sin((lob - lo) / 2) ** 2
    return 6371000 * 2 * math.atan2(math.sqrt(q), math.sqrt(max(0.0, 1 - q)))


def distance(points):
    return sum(haversine(a, b) for a, b in zip(points, points[1:]))


def coords(place):
    return [place["lat"], place["lon"]]


def iso(dt):
    return dt.astimezone(TZ).isoformat(timespec="seconds")


def parse_time(value, name):
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError(f"{name} must be an ISO 8601 timestamp")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        raise ValueError(f"{name} must be an ISO 8601 timestamp") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def seconds_of_day(dt):
    local = dt.astimezone(TZ)
    return local.hour * 3600 + local.minute * 60 + local.second


def numeric(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be a finite number between {low} and {high}")
    return float(value)


def resolve_place(value):
    if isinstance(value, str):
        normalized = value.strip().lower()
        aliases = {"klaus computing": "klaus", "student center": "student-center", "kendeda building": "kendeda", "midtown marta": "midtown-marta", "clough commons": "clough"}
        normalized = aliases.get(normalized, normalized)
        for place in PLACES:
            if place["id"] == normalized or place["name"].lower() == normalized:
                return dict(place)
        raise ValueError("Unknown place. Choose a campus location from /places.")
    if isinstance(value, dict):
        lat = numeric(value.get("lat"), "latitude", 33.76, 33.80)
        lon = numeric(value.get("lon", value.get("lng")), "longitude", -84.42, -84.37)
        name = value.get("name", "Current location")
        if not isinstance(name, str) or len(name) > 120:
            raise ValueError("Place name must be a string of at most 120 characters")
        return {"id": str(value.get("id", "current-location"))[:80], "name": name, "lat": lat, "lon": lon}
    raise ValueError("origin and destination must be place ids or campus coordinates")


def _prepare():
    raw = json.loads((ROOT / "data/routes.json").read_text())
    twin = json.loads((ROOT / "web/assets/campus.json").read_text())
    twins = {r["id"]: r for r in twin["routes"]}
    routes = []
    for source in raw:
        route = copy.deepcopy(source)
        sim = twins[route["id"]]
        route["synthetic"] = bool(sim.get("synthetic"))
        line = route["line"]
        lengths = [0.0]
        for a, b in zip(line, line[1:]):
            lengths.append(lengths[-1] + haversine(a, b))
        route["_lengths"] = lengths
        route["_length"] = lengths[-1]
        route["_sim_length"] = sim["L"]
        route["_headway"] = sim["loop_s"] / max(1, sim["n_bus"])
        # Joint monotone map matching avoids snapping a stop to the wrong pass
        # through a shared road (Red retraces several campus intersections).
        # Prefix-min dynamic programming preserves the official stop order.
        previous_cost = [haversine(coords(route["stops"][0]), point) ** 2 + i * .001
                         for i, point in enumerate(line)]
        backpointers = []
        for stop in route["stops"][1:]:
            best_cost, best_index = float("inf"), 0
            current_cost, previous_indices = [], []
            for i, point in enumerate(line):
                if previous_cost[i] < best_cost:
                    best_cost, best_index = previous_cost[i], i
                current_cost.append(best_cost + haversine(coords(stop), point) ** 2)
                previous_indices.append(best_index)
            backpointers.append(previous_indices)
            previous_cost = current_cost
        index = min(range(len(line)), key=previous_cost.__getitem__)
        matched = [index]
        for previous_indices in reversed(backpointers):
            index = previous_indices[index]
            matched.append(index)
        matched.reverse()
        for stop, index in zip(route["stops"], matched):
            stop["_index"] = index
            stop["_d"] = lengths[index] / max(1, lengths[-1]) * sim["L"]
        route["_arrivals"] = _replay_arrivals(route, sim)
        routes.append(route)
    return routes


def _replay_arrivals(route, sim):
    """Record actual forward stop crossings; never bridge missing GPS samples."""
    result = {stop["id"]: [] for stop in route["stops"]}
    replay = sim.get("replay")
    if not replay:
        return result
    length = sim["L"]
    dt = replay["dt"]
    for vehicle in replay["veh"]:
        values = vehicle["D"]
        for index in range(1, len(values)):
            before, after = values[index - 1], values[index]
            if before is None or after is None or after <= before or after - before > 500:
                continue
            time = (vehicle["i0"] + index - 1) * dt
            for stop in route["stops"]:
                target = stop["_d"]
                cycle = math.floor((before - target) / length) + 1
                crossing = target + cycle * length
                if before < crossing <= after:
                    result[stop["id"]].append(time + dt * (crossing - before) / (after - before))
    for values in result.values():
        values.sort()
    return result


ROUTES = _prepare()


def routes():
    return [{"id": r["id"], "name": r["name"], "color": r["color"], "synthetic": r["synthetic"], "line": r["line"],
             "stops": [{k: s[k] for k in ["id", "name", "lat", "lon"]} for s in r["stops"]]} for r in ROUTES]


def _walk(a, b, speed, title=None):
    network = walking.route(coords(a), coords(b))
    meters = network['distance_m']
    return {"id": "walk", "kind": "walk", "from_name": a["name"], "to_name": b["name"], "duration_minutes": round(meters / speed / 60, 2),
            "distance_m": round(meters), "route_id": None, "route_name": None, "color": "#65d6b0", "geometry": network['geometry'],
            "instruction": title or f"Walk to {b['name']}", "approximate": True,
            "geometry_source": network['source'], "timing_source": "distance_divided_by_walking_speed"}


def _ride(route, start_index, end_index):
    """Traverse only the listed forward direction, wrapping at a loop boundary."""
    stops = route["stops"]
    indices = []
    index = start_index
    while index != end_index and len(indices) <= len(stops):
        indices.append(index)
        index = (index + 1) % len(stops)
    if not indices:
        return None
    start, end = stops[start_index], stops[end_index]
    a, b = start["_index"], end["_index"]
    line = route["line"]
    path = line[a:b + 1] if b > a else line[a:] + line[:b + 1]
    path = [coords(start)] + path + [coords(end)]
    # Data's to_next is reference segment travel time, dwell at intermediate stops.
    travel_seconds = sum(float(stops[i].get("to_next", 60)) for i in indices)
    travel_seconds += sum(float(stops[i].get("dwell", 0)) for i in indices[1:])
    return {"id": "ride", "kind": "ride", "from_name": start["name"], "to_name": end["name"],
            "duration_minutes": round(max(30, travel_seconds) / 60, 2), "distance_m": round(distance(path)),
            "route_id": route["id"], "route_name": route["name"], "color": route["color"], "geometry": path,
            "instruction": f"Ride {route['name']} to {end['name']}", "timing_source": "reference_segment_and_dwell_times",
            "_stops": len(indices), "_synthetic": route["synthetic"]}


def _next_bus(route, stop, earliest_seconds, delay_minutes):
    """Replay crossings at time-of-day; synthetic/fallback schedule is labelled."""
    arrivals = route["_arrivals"][stop["id"]]
    delayed = earliest_seconds - delay_minutes * 60
    index = bisect.bisect_left(arrivals, delayed + 15)  # boarding buffer
    if index < len(arrivals) and arrivals[index] - delayed <= 40 * 60:
        return arrivals[index] + delay_minutes * 60, "gps_replay"
    # Keep the app usable outside recorded windows, with explicit source labels.
    headway = max(150, route["_headway"])
    offset = stop["_d"] / max(1, route["_sim_length"]) * (headway * max(1, 3))
    scheduled = math.ceil((delayed + 15 - offset) / headway) * headway + offset
    return scheduled + delay_minutes * 60, "synthetic_schedule" if route["synthetic"] else "schedule_fallback"


def _wait(route, stop, at_time, delay):
    bus, source = _next_bus(route, stop, at_time, delay)
    return {"id": "wait", "kind": "wait", "from_name": stop["name"], "to_name": stop["name"], "duration_minutes": round(max(0, bus - at_time) / 60, 2),
            "distance_m": 0, "route_id": route["id"], "route_name": route["name"], "color": route["color"], "geometry": [coords(stop)],
            "instruction": f"Wait for {route['name']}", "arrival_source": source,
            "timing_source": source, "_headway": route["_headway"] / 60}


def _near(route, place, limit=2):
    stops = sorted(enumerate(route["stops"]), key=lambda pair: haversine(coords(place), coords(pair[1])))
    return [(i, s) for i, s in stops[:limit] if haversine(coords(place), coords(s)) < 800]


TRANSFER_OPTIONS = []
for _first in ROUTES:
    for _second in ROUTES:
        if _first["id"] == _second["id"]:
            continue
        _pairs = sorted([(haversine(coords(a), coords(b)), i, j) for i, a in enumerate(_first["stops"]) for j, b in enumerate(_second["stops"]) if haversine(coords(a), coords(b)) < 75])
        TRANSFER_OPTIONS.append((_first, _second, _pairs[:3]))


def _candidates(origin, destination, departure, speed, delay):
    start_seconds = seconds_of_day(departure)
    result = [{"label": "Walk all the way", "legs": [_walk(origin, destination, speed)]}]
    for route in ROUTES:
        for i, board in _near(route, origin):
            for j, alight in _near(route, destination):
                ride = _ride(route, i, j)
                if ride is None:
                    continue
                first = _walk(origin, board, speed)
                wait = _wait(route, board, start_seconds + first["duration_minutes"] * 60, delay)
                result.append({"label": f"{route['name']} + walk", "legs": [first, wait, ride, _walk(alight, destination, speed)]})
    # One transfer, walking between physically adjacent stops on different routes.
    for first_route, second_route, pairs in TRANSFER_OPTIONS:
        starts, ends = _near(first_route, origin, 1), _near(second_route, destination, 1)
        if not starts or not ends:
            continue
        i, board = starts[0]
        j, alight = ends[0]
        for _, ti, tj in pairs:
            ride_a, ride_b = _ride(first_route, i, ti), _ride(second_route, tj, j)
            if ride_a is None or ride_b is None:
                continue
            walk_a = _walk(origin, board, speed)
            wait_a = _wait(first_route, board, start_seconds + walk_a["duration_minutes"] * 60, delay)
            transfer = _walk(first_route["stops"][ti], second_route["stops"][tj], speed, f"Transfer to {second_route['name']}")
            elapsed = sum(leg["duration_minutes"] * 60 for leg in [walk_a, wait_a, ride_a, transfer])
            wait_b = _wait(second_route, second_route["stops"][tj], start_seconds + elapsed, delay)
            result.append({"label": f"{first_route['name']} → {second_route['name']}", "legs": [walk_a, wait_a, ride_a, transfer, wait_b, ride_b, _walk(alight, destination, speed)]})
    result.sort(key=lambda p: sum(leg["duration_minutes"] for leg in p["legs"]))
    return result


def _percentile(samples, q):
    return samples[min(len(samples) - 1, int(q * (len(samples) - 1)))]


def _evaluate(candidate, departure, deadline, horizon, social, seed):
    legs = copy.deepcopy(candidate["legs"])
    expected = sum(l["duration_minutes"] for l in legs)
    # The seed is shared between social scenarios so widening can be compared.
    rng = random.Random(seed)
    walks = sum(l["duration_minutes"] for l in legs if l["kind"] == "walk")
    rides = sum(l["duration_minutes"] for l in legs if l["kind"] == "ride")
    waits = [l for l in legs if l["kind"] == "wait"]
    spread = max(0.35, walks * .10 + rides * .14 + len(waits) * .65) * (1 + max(0, horizon) / 90)
    residuals = [rng.gauss(0, 1) for _ in range(SAMPLES)]
    catch = None
    miss_penalties = [0.0] * SAMPLES
    if waits:
        # Uncalibrated boarding model: uncertain walking/vehicle arrival can miss
        # a connection. A missed vehicle incurs a route-specific headway, not a
        # zero-cost continuation. Fixed seeds keep scenario comparisons stable.
        catch_probability = 1.0
        for wait in waits:
            buffer = wait["duration_minutes"]
            sigma = max(.3, .10 * walks + .45) * (1 + horizon / 120)
            probability = .5 * (1 + math.erf(buffer / sigma / math.sqrt(2)))
            catch_probability *= probability
            for i in range(SAMPLES):
                if rng.random() > probability:
                    miss_penalties[i] += max(1, wait["_headway"])
        catch = catch_probability
    samples = sorted(max(min(.05, expected * .5), expected + noise * spread + penalty)
                     for noise, penalty in zip(residuals, miss_penalties))
    median = _percentile(samples, .5)
    # Present internally consistent median segment and total durations. The wait
    # leg absorbs the median boarding-risk correction; alternatives share it.
    correction = median - expected
    adjustment_leg = next((leg for leg in legs if leg["kind"] == "wait"), legs[0])
    if adjustment_leg["duration_minutes"] + correction >= 0:
        adjustment_leg["duration_minutes"] = round(adjustment_leg["duration_minutes"] + correction, 2)
    expected = sum(leg["duration_minutes"] for leg in legs)
    shift = expected - median
    samples = [max(0, value + shift) for value in samples]
    q10, q90 = _percentile(samples, .1), _percentile(samples, .9)
    if social and rides:
        q10 = max(0, expected - (expected - q10) * 1.45)
        q90 = expected + (q90 - expected) * 1.45
        samples = [max(0, expected + (value - expected) * 1.45) for value in samples]
    on_time = None
    if deadline:
        budget = (deadline - departure).total_seconds() / 60
        on_time = sum(s <= budget for s in samples) / SAMPLES
    quantiles = {"p10": round(q10, 1), "p50": round(expected, 1), "p90": round(q90, 1)}
    clean_legs = []
    for index, leg in enumerate(legs):
        clean_legs.append({k: v for k, v in leg.items() if not k.startswith("_")})
        clean_legs[-1]["id"] = f"leg-{index}"
    geometry = []
    for leg in clean_legs:
        for point in leg["geometry"]:
            if not geometry or point != geometry[-1]:
                geometry.append(point)
    fingerprint = hashlib.sha256((candidate["label"] + json.dumps([(l["kind"], l["from_name"], l["to_name"]) for l in legs])).encode()).hexdigest()[:10]
    return {"id": fingerprint, "label": candidate["label"], "legs": clean_legs, "departure_time": iso(departure), "arrival_time": iso(departure + timedelta(minutes=expected)),
            "leave_by": iso(departure), "duration_minutes": round(expected, 2), "quantiles": quantiles,
            "p_on_time": None if on_time is None else round(on_time, 3), "p_catch": None if catch is None else round(catch, 3), "geometry": geometry,
            "synthetic": any(l.get("_synthetic") for l in legs), "social_applied": bool(social and rides),
            "confidence_label": "Demo uncertainty · check closer to departure" if horizon >= 60 else "Demo uncertainty · replay estimate",
            "prediction_source": "replay_baseline_v0", "uncertainty_calibrated": False}


def _plans(origin, destination, departure, deadline, speed, delay, social, horizon, preferred):
    candidates = _candidates(origin, destination, departure, speed, delay)
    selected = []
    signatures = set()
    # Keep the first walking candidate and shortest distinct transit topologies.
    for candidate in candidates:
        signature = tuple((l["kind"], l["route_id"]) for l in candidate["legs"] if l["kind"] != "walk")
        if signature in signatures:
            continue
        signatures.add(signature)
        seed = int(hashlib.sha256(json.dumps([origin["id"], destination["id"], signature]).encode()).hexdigest()[:12], 16)
        selected.append(_evaluate(candidate, departure, deadline, horizon, social, seed))
        if len(selected) >= 9:
            break
    if not any(not any(l["kind"] == "ride" for l in p["legs"]) for p in selected):
        candidate = {"label": "Walk all the way", "legs": [_walk(origin, destination, speed)]}
        selected.append(_evaluate(candidate, departure, deadline, horizon, social, 42))
    # Filter only chosen rank, preserve alternate modes for comparison.
    def rank(p):
        has_bus = any(l["kind"] == "ride" for l in p["legs"])
        mismatch = preferred == "bus" and not has_bus or preferred == "walk" and has_bus
        return (bool(mismatch), p["quantiles"]["p90"])
    selected.sort(key=rank)
    return selected


def _arrive_by(origin, destination, deadline, speed, delay, social, preferred, reference):
    # Feasibility is time-dependent at discrete replay crossings. Scan backwards
    # before refining; a global binary search can skip a feasible boarding window.
    lower, upper, found = deadline - timedelta(hours=3), deadline, None
    for step in range(181):
        test = deadline - timedelta(minutes=step)
        horizon = max(0, (test - reference).total_seconds() / 60)
        plans = _plans(origin, destination, test, deadline, speed, delay, social, horizon, preferred)
        chosen = plans[0]
        if chosen["p_on_time"] is not None and chosen["p_on_time"] >= .90:
            found = test
            upper = test + timedelta(minutes=1)
            break
    if found is None:
        raise ValueError("No route meets the arrive-by target inside the demo planning window")
    lower = found
    for _ in range(6):
        test = lower + (upper - lower) / 2
        plans = _plans(origin, destination, test, deadline, speed, delay, social, max(0, (test - reference).total_seconds() / 60), preferred)
        if plans[0]["p_on_time"] >= .90:
            lower = test
        else:
            upper = test
    return lower.replace(microsecond=0)


def _numbers(trace):
    values = set()
    def visit(value, key=""):
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)) and math.isfinite(value):
            values.add(str(value)); values.add(f"{value:g}"); values.add(str(round(value)))
            if key in ["p_on_time", "p_catch"]:
                values.add(str(round(value * 100))); values.add(f"{value * 100:.1f}")
        elif isinstance(value, dict):
            for k, v in value.items():
                if k not in ["geometry", "allowed_numbers"]:
                    visit(v, k)
        elif isinstance(value, list):
            for item in value:
                visit(item, key)
        elif isinstance(value, str) and key in ["departure_time", "arrival_time", "leave_by"]:
            dt = parse_time(value, key)
            values.update([str(dt.hour), str(dt.hour % 12 or 12), f"{dt.minute:02}", str(dt.minute), dt.strftime("%H:%M"), dt.strftime("%I:%M").lstrip("0")])
    visit(trace)
    return sorted(values)


def verify_trace(trace):
    try:
        if trace.get("version") != VERSION or not trace.get("chosen"):
            return False
        for plan in [trace["chosen"]] + trace.get("alternatives", []):
            q = plan["quantiles"]
            if not 0 <= q["p10"] <= q["p50"] <= q["p90"]:
                return False
            if abs(sum(l["duration_minutes"] for l in plan["legs"]) - plan["duration_minutes"]) > .011:
                return False
            for field in ["p_on_time", "p_catch"]:
                if plan[field] is not None and not 0 <= plan[field] <= 1:
                    return False
            if not all(math.isfinite(l["duration_minutes"]) and l["duration_minutes"] >= 0 for l in plan["legs"]):
                return False
            dt = parse_time(plan["arrival_time"], "arrival") - parse_time(plan["departure_time"], "departure")
            if abs(dt.total_seconds() / 60 - plan["duration_minutes"]) > .02:
                return False
        return trace.get("allowed_numbers") == _numbers(trace)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def plan_trip(body):
    if not isinstance(body, dict):
        raise ValueError("Request body must be an object")
    if "origin" not in body or "destination" not in body:
        raise ValueError("origin and destination are required")
    origin, destination = resolve_place(body["origin"]), resolve_place(body["destination"])
    if haversine(coords(origin), coords(destination)) < 1:
        raise ValueError("Choose different origin and destination locations")
    speed = numeric(body.get("walk_speed", 1.35), "walk_speed", .5, 2.5)
    delay = numeric(body.get("delay_minutes", 0), "delay_minutes", 0, 30)
    horizon_extra = numeric(body.get("horizon_minutes", 0), "horizon_minutes", 0, 360)
    for name in ["avoid_stairs", "social_factor"]:
        if not isinstance(body.get(name, False), bool):
            raise ValueError(f"{name} must be a boolean")
    preferred = body.get("preferred_mode", "best")
    if preferred not in ["best", "bus", "walk"]:
        raise ValueError("preferred_mode must be best, bus, or walk")
    if body.get("mode", "replay") not in ["replay", "demo"]:
        raise ValueError("Only historical replay mode is configured; live data is unavailable")
    if body.get("depart_at") and body.get("arrive_by"):
        raise ValueError("Set either depart_at or arrive_by, not both")
    if body.get("evaluate_at") and not body.get("arrive_by"):
        raise ValueError("evaluate_at requires an arrive_by deadline")
    if body.get("evaluate_at") and body.get("depart_at"):
        raise ValueError("Set either depart_at or evaluate_at, not both")
    now = datetime.now(TZ)
    reference = now.replace(hour=9, minute=30, second=0, microsecond=0)
    deadline = parse_time(body["arrive_by"], "arrive_by") if body.get("arrive_by") else None
    depart = parse_time(body["depart_at"], "depart_at") if body.get("depart_at") else reference
    evaluate_at = parse_time(body["evaluate_at"], "evaluate_at") if body.get("evaluate_at") else None
    if evaluate_at:
        depart = evaluate_at
    social = body.get("social_factor", False)
    # Replay horizon is relative to the selected replay day, not wall-clock date.
    reference = (deadline or depart).replace(hour=9, minute=30, second=0, microsecond=0)
    if deadline and evaluate_at is None:
        depart = _arrive_by(origin, destination, deadline, speed, delay, social, preferred, reference)
    horizon = max(horizon_extra, max(0, (depart - reference).total_seconds() / 60))
    plans = _plans(origin, destination, depart, deadline, speed, delay, social, horizon, preferred)
    chosen = plans[0]
    warnings = ["Historical GPS replay, not live service. Routes replay different recorded March weekdays.",
                "Walking follows the mapped network where connected, with approximate endpoint connectors and explicit straight-line fallback. Access, closures and stairs are unverified.",
                "Arrival intervals and probabilities use an uncalibrated seeded demo baseline, not deployed Stinger Delay model weights."]
    if body.get("avoid_stairs"):
        warnings.append("Avoid-stairs requested but cannot be guaranteed without an accessibility graph.")
    if chosen["synthetic"]:
        warnings.append("Blue route vehicle positions and departures are synthetic.")
    if any(l.get("arrival_source") == "schedule_fallback" for l in chosen["legs"]):
        warnings.append("No usable GPS crossing at this time: waiting estimate uses a schedule fallback.")
    if social:
        warnings.append("Demo social signal enabled: transit uncertainty widens; median travel time is unchanged.")
    facts = [f"Recommended: {chosen['label']}.", "Wait estimates use the next recorded stop crossing where coverage exists.", "Transit geometry follows each route's listed forward direction."]
    if evaluate_at:
        facts.append("This assessment evaluates the selected departure against the arrival deadline; it does not search for a new leave-by time.")
    if horizon >= 60:
        facts.append("Long-horizon uncertainty is wider. Check again closer to departure.")
    fingerprint = hashlib.sha256(json.dumps([origin, destination, iso(depart), iso(deadline) if deadline else None, speed, delay, social, horizon, preferred, bool(evaluate_at)], sort_keys=True).encode()).hexdigest()[:16]
    trace = {"id": fingerprint, "version": VERSION, "generated_at": iso(now), "mode": "replay", "origin": origin, "destination": destination,
             "constraints": {"depart_at": iso(depart), "arrive_by": iso(deadline) if deadline else None, "evaluate_at": iso(evaluate_at) if evaluate_at else None, "walk_speed": speed, "avoid_stairs": body.get("avoid_stairs", False), "social_factor": social, "delay_minutes": delay, "horizon_minutes": round(horizon, 1), "preferred_mode": preferred, "on_time_target": .9 if deadline else None},
             "chosen": chosen, "alternatives": plans[1:5], "explanation_facts": facts, "warnings": warnings, "verified": True}
    trace["allowed_numbers"] = _numbers(trace)
    trace["verified"] = verify_trace(trace)
    if not trace["verified"]:
        raise RuntimeError("Planner trace verification failed")
    with _CACHE_LOCK:
        _TRACE_CACHE[trace["id"]] = copy.deepcopy(trace)
        _TRACE_CACHE.move_to_end(trace["id"])
        while len(_TRACE_CACHE) > 128:
            _TRACE_CACHE.popitem(last=False)
    return trace


def get_trace(trace_id):
    with _CACHE_LOCK:
        trace = _TRACE_CACHE.get(trace_id)
        return copy.deepcopy(trace) if trace else None


def day_schedule(body, events):
    if not isinstance(events, list) or len(events) > 30:
        raise ValueError("events must be an array with at most 30 entries")
    current = body.get("origin", "student-center")
    items, unresolved = [], []
    ordered = sorted(events, key=lambda e: e.get("start", ""))
    for event in ordered:
        target = event.get("place_id")
        if not target:
            unresolved.append(event)
            continue
        try:
            trace = plan_trip({"origin": current, "destination": target, "arrive_by": event["start"], "social_factor": body.get("social_factor", False)})
            if items:
                previous_end = parse_time(items[-1]["event"]["end"], "event end")
                if parse_time(trace["chosen"]["leave_by"], "leave_by") < previous_end:
                    trace["warnings"].append("Previous class ends after the recommended leave-by; schedule conflict requires attention.")
            items.append({"event": event, "trace": trace})
            current = target
        except ValueError as exc:
            if isinstance(current, str) and current == target:
                # Same building: no route is needed, but don't invent a zero trace.
                unresolved.append({**event, "reason": "Already at this location; no travel needed"})
            else:
                unresolved.append({**event, "reason": str(exc)})
    return {"mode": "demo", "items": items, "unresolved": unresolved}
