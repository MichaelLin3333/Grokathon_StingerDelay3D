from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional

from .data_loader import load_campus, load_routes, repo_root
from .models import LatLon

# Connect nearby corridor/stop/road nodes into a walk mesh.
CONNECT_M = 85.0
POLYLINE_STEP = 4  # keep every Nth bus-route polyline vertex
CAMPUS_DETOUR = 1.12  # on-campus paths hug corridors
OFF_CAMPUS_DETOUR = 1.28
# campus.json is mostly boundary polygons — not a foot network.
# We incrementally enrich with twin OSM road centerlines (data/derived/campus_roads.json).
# TODO: replace with true OSM footway/path/steps extract when available.


def _hav(a: LatLon, b: LatLon) -> float:
    r = 6371000.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dphi = math.radians(b.lat - a.lat)
    dlmb = math.radians(b.lon - a.lon)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def _point_in_ring(lat: float, lon: float, ring: list[tuple[float, float]]) -> bool:
    """Ray-cast; ring is [(lat, lon), ...]."""
    inside = False
    n = len(ring)
    if n < 3:
        return False
    for i in range(n):
        lat1, lon1 = ring[i]
        lat2, lon2 = ring[(i + 1) % n]
        if ((lon1 > lon) != (lon2 > lon)) and (
            lat < (lat2 - lat1) * (lon - lon1) / ((lon2 - lon1) or 1e-12) + lat1
        ):
            inside = not inside
    return inside


@lru_cache(maxsize=1)
def _campus_rings() -> list[list[tuple[float, float]]]:
    campus = load_campus()
    rings: list[list[tuple[float, float]]] = []
    for el in campus.get("elements") or []:
        geom = el.get("geometry") or []
        if len(geom) >= 3:
            rings.append([(float(p["lat"]), float(p["lon"])) for p in geom])
    return rings


def on_campus(point: LatLon) -> bool:
    rings = _campus_rings()
    if not rings:
        return True
    return any(_point_in_ring(point.lat, point.lon, ring) for ring in rings)


@dataclass
class WalkResult:
    distance_m: float
    duration_s: float
    geometry: list[list[float]]  # [[lat, lon], ...]
    method: str
    on_campus: bool
    nodes_used: int


@dataclass
class _Node:
    id: int
    ll: LatLon
    kind: str


class WalkGraph:
    def __init__(self) -> None:
        self.nodes: list[_Node] = []
        self.edges: dict[int, list[tuple[int, float]]] = {}
        self._build()

    def _add_node(self, ll: LatLon, kind: str) -> int:
        nid = len(self.nodes)
        self.nodes.append(_Node(id=nid, ll=ll, kind=kind))
        self.edges[nid] = []
        return nid

    def _link(self, a: int, b: int, dist: Optional[float] = None) -> None:
        if a == b:
            return
        d = dist if dist is not None else _hav(self.nodes[a].ll, self.nodes[b].ll)
        if d <= 0:
            return
        self.edges[a].append((b, d))
        self.edges[b].append((a, d))

    def _build(self) -> None:
        routes = load_routes()
        # Stops + bus-route corridors
        for route in routes:
            for stop in route.get("stops") or []:
                self._add_node(
                    LatLon(lat=float(stop["lat"]), lon=float(stop["lon"])),
                    kind=f"stop:{route.get('id')}:{stop.get('id')}",
                )
            line = route.get("line") or []
            prev: Optional[int] = None
            for i, pt in enumerate(line):
                if i % POLYLINE_STEP != 0 and i != len(line) - 1:
                    continue
                nid = self._add_node(
                    LatLon(lat=float(pt[0]), lon=float(pt[1])), kind="corridor"
                )
                if prev is not None:
                    self._link(prev, nid)
                prev = nid

        # OSM road centerlines from twin extract (campus bbox)
        roads_path = repo_root() / "data" / "derived" / "campus_roads.json"
        road_count = 0
        if roads_path.exists():
            import json

            roads = json.loads(roads_path.read_text()).get("roads") or []
            for road in roads:
                coords = road.get("coords") or []
                prev = None
                for pt in coords:
                    nid = self._add_node(
                        LatLon(lat=float(pt[0]), lon=float(pt[1])),
                        kind=f"road:{road.get('kind', 'road')}",
                    )
                    if prev is not None:
                        self._link(prev, nid)
                    prev = nid
                road_count += 1
        self._road_count = road_count

        # Spatial hash for near connections (stitch roads ↔ stops/corridors)
        cell = CONNECT_M / 111_320.0  # rough degrees
        buckets: dict[tuple[int, int], list[int]] = {}
        for n in self.nodes:
            key = (int(n.ll.lat / cell), int(n.ll.lon / cell))
            buckets.setdefault(key, []).append(n.id)

        for n in self.nodes:
            base = (int(n.ll.lat / cell), int(n.ll.lon / cell))
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    for other in buckets.get((base[0] + di, base[1] + dj), []):
                        if other <= n.id:
                            continue
                        # Prefer stitching different layers; skip distant road-road
                        a_kind = self.nodes[n.id].kind
                        b_kind = self.nodes[other].kind
                        both_road = a_kind.startswith("road:") and b_kind.startswith(
                            "road:"
                        )
                        d = _hav(n.ll, self.nodes[other].ll)
                        limit = 45.0 if both_road else CONNECT_M
                        if d <= limit:
                            self._link(n.id, other, d)

    def _nearest_node(self, point: LatLon) -> tuple[int, float]:
        best_i, best_d = 0, float("inf")
        for n in self.nodes:
            d = _hav(point, n.ll)
            if d < best_d:
                best_i, best_d = n.id, d
        return best_i, best_d

    def shortest_path(self, origin: LatLon, dest: LatLon, walk_speed_mps: float) -> WalkResult:
        if not self.nodes:
            straight = _hav(origin, dest)
            detour = CAMPUS_DETOUR if on_campus(origin) and on_campus(dest) else OFF_CAMPUS_DETOUR
            dist = straight * detour
            return WalkResult(
                distance_m=dist,
                duration_s=dist / walk_speed_mps,
                geometry=[[origin.lat, origin.lon], [dest.lat, dest.lon]],
                method="haversine_fallback",
                on_campus=on_campus(origin) and on_campus(dest),
                nodes_used=0,
            )

        # Snap to graph
        o_i, o_snap = self._nearest_node(origin)
        d_i, d_snap = self._nearest_node(dest)

        # Dijkstra
        dist = {o_i: 0.0}
        prev: dict[int, Optional[int]] = {o_i: None}
        pq: list[tuple[float, int]] = [(0.0, o_i)]
        seen: set[int] = set()
        while pq:
            cost, u = heapq.heappop(pq)
            if u in seen:
                continue
            seen.add(u)
            if u == d_i:
                break
            for v, w in self.edges.get(u, []):
                nd = cost + w
                if nd < dist.get(v, float("inf")):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(pq, (nd, v))

        if d_i not in dist:
            straight = _hav(origin, dest)
            detour = CAMPUS_DETOUR if on_campus(origin) and on_campus(dest) else OFF_CAMPUS_DETOUR
            dist_m = straight * detour
            return WalkResult(
                distance_m=dist_m,
                duration_s=dist_m / walk_speed_mps,
                geometry=[[origin.lat, origin.lon], [dest.lat, dest.lon]],
                method="haversine_disconnected",
                on_campus=on_campus(origin) and on_campus(dest),
                nodes_used=0,
            )

        # Reconstruct
        path_ids: list[int] = []
        cur: Optional[int] = d_i
        while cur is not None:
            path_ids.append(cur)
            cur = prev.get(cur)
        path_ids.reverse()
        geom = [[origin.lat, origin.lon]]
        geom.extend([[self.nodes[i].ll.lat, self.nodes[i].ll.lon] for i in path_ids])
        geom.append([dest.lat, dest.lon])

        path_m = dist[d_i] + o_snap + d_snap
        campus = on_campus(origin) and on_campus(dest)
        # Mild campus factor already baked via corridor hugging; tiny trim on campus
        if campus:
            path_m *= 0.98
        else:
            path_m *= OFF_CAMPUS_DETOUR / CAMPUS_DETOUR

        return WalkResult(
            distance_m=path_m,
            duration_s=path_m / max(0.5, walk_speed_mps),
            geometry=geom,
method="stop_corridor_road_dijkstra",
                on_campus=campus,
                nodes_used=len(path_ids),
            )


@lru_cache(maxsize=1)
def get_walk_graph() -> WalkGraph:
    return WalkGraph()


@lru_cache(maxsize=8192)
def _walk_between_cached(
    o_lat: float,
    o_lon: float,
    d_lat: float,
    d_lon: float,
    walk_speed_mps: float,
) -> WalkResult:
    return get_walk_graph().shortest_path(
        LatLon(lat=o_lat, lon=o_lon),
        LatLon(lat=d_lat, lon=d_lon),
        walk_speed_mps,
    )


def walk_between(origin: LatLon, dest: LatLon, walk_speed_mps: float) -> WalkResult:
    # Quantize ~1–2 m so planner candidate fan-out hits cache
    return _walk_between_cached(
        round(origin.lat, 5),
        round(origin.lon, 5),
        round(dest.lat, 5),
        round(dest.lon, 5),
        round(walk_speed_mps, 3),
    )


def walk_graph_meta() -> dict[str, Any]:
    g = get_walk_graph()
    return {
        "walk_nodes": len(g.nodes),
        "walk_edges": sum(len(v) for v in g.edges.values()) // 2,
        "walk_connect_m": CONNECT_M,
        "campus_rings": len(_campus_rings()),
        "road_polylines": getattr(g, "_road_count", 0),
        "walk_limit": (
            "campus.json is boundary-only; walk graph uses bus corridors + twin OSM "
            "road centerlines (not dedicated footways)."
        ),
    }
