#!/usr/bin/env python3
"""Extract OSM road centerlines from campus-3d data.js into data/derived/campus_roads.json.

campus.json is boundary-only; this is an incremental walk-graph enrichment, not true footways.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "apps" / "web" / "public" / "campus-3d" / "data.js"
OUT = ROOT / "data" / "derived" / "campus_roads.json"
CAMPUS = ROOT / "data" / "base" / "campus.json"


def main() -> None:
    text = SRC.read_text()
    assert text.startswith("window.TWIN = ")
    payload = text[len("window.TWIN = ") :].strip().rstrip(";")
    twin = json.loads(payload)
    origin_lat, origin_lon = twin["meta"]["origin"]
    m_lat = 111320.0
    m_lon = 111320.0 * math.cos(math.radians(origin_lat))

    def to_ll(x: float, y: float) -> list[float]:
        return [
            round(origin_lat + y / m_lat, 6),
            round(origin_lon + x / m_lon, 6),
        ]

    campus = json.loads(CAMPUS.read_text())
    lats, lons = [], []
    for el in campus.get("elements") or []:
        for p in el.get("geometry") or []:
            lats.append(p["lat"])
            lons.append(p["lon"])
    pad = 0.004
    min_lat, max_lat = min(lats) - pad, max(lats) + pad
    min_lon, max_lon = min(lons) - pad, max(lons) + pad

    kept = []
    for r in twin.get("roads") or []:
        p = r.get("p") or []
        coords = [to_ll(p[i], p[i + 1]) for i in range(0, len(p) - 1, 2)]
        coords = [
            c
            for c in coords
            if min_lat - 0.002 <= c[0] <= max_lat + 0.002
            and min_lon - 0.002 <= c[1] <= max_lon + 0.002
        ]
        if len(coords) < 2:
            continue
        if not any(min_lat <= c[0] <= max_lat and min_lon <= c[1] <= max_lon for c in coords):
            continue
        if len(coords) > 8:
            step = max(1, len(coords) // 6)
            coords = coords[::step]
        kept.append({"kind": r.get("k") or "road", "coords": coords})

    prefer_kinds = {
        "residential",
        "footway",
        "path",
        "living_street",
        "pedestrian",
        "service",
        "cycleway",
        "unclassified",
    }
    prefer = [r for r in kept if r["kind"] in prefer_kinds]
    other = [r for r in kept if r["kind"] not in prefer_kinds]
    kept = (prefer + other)[:900]

    out = {
        "source": "apps/web/public/campus-3d/data.js T.roads",
        "origin": [origin_lat, origin_lon],
        "bbox": [min_lat, max_lat, min_lon, max_lon],
        "road_count": len(kept),
        "note": "Road centerlines clipped to campus bbox, capped at 900 segs — not dedicated footways.",
        "todos": ["Prefer OSM highway=footway/path/steps extract"],
        "roads": kept,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out) + "\n")
    print(f"wrote {OUT} roads={len(kept)}")


if __name__ == "__main__":
    main()
