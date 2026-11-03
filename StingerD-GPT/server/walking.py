"""A* walking estimates on the supplied road/path snapshot, with explicit fallbacks.

The extract lacks verified entrances, access permissions, crossings and stairs.
A graph path is a network estimate, never an accessibility guarantee.
"""
from functools import lru_cache
import heapq
import json
import math
from pathlib import Path
import threading

_ROOT = Path(__file__).resolve().parents[1]
_LOCK = threading.Lock()
_GRAPH = None
CELL = 80
ALLOWED = {'footway', 'path', 'pedestrian', 'residential', 'service', 'unclassified', 'tertiary', 'secondary', 'primary', 'tertiary_link'}


def _length(points):
    total = 0
    for a, b in zip(points, points[1:]):
        lat = math.radians((a[0] + b[0]) / 2)
        total += math.hypot((b[0] - a[0]) * 111320, (b[1] - a[1]) * 111320 * math.cos(lat))
    return total


def _load():
    global _GRAPH
    if _GRAPH is not None:
        return _GRAPH
    with _LOCK:
        if _GRAPH is not None:
            return _GRAPH
        twin = json.loads((_ROOT / 'web/assets/campus.json').read_text())
        lat, lon = twin['meta']['origin']
        kx = 111320 * math.cos(math.radians(lat))
        adj = {}
        for road in twin['roads']:
            if road['k'] not in ALLOWED:
                continue
            p = road['p']
            points = [(round(p[i], 1), round(p[i+1], 1)) for i in range(0, len(p)-1, 2)]
            for a, b in zip(points, points[1:]):
                if a == b:
                    continue
                distance = math.hypot(b[0]-a[0], b[1]-a[1])
                adj.setdefault(a, {})[b] = distance
                adj.setdefault(b, {})[a] = distance
        grid = {}
        for point in adj:
            grid.setdefault((math.floor(point[0]/CELL), math.floor(point[1]/CELL)), []).append(point)
        _GRAPH = {'adj': adj, 'grid': grid, 'lat': lat, 'lon': lon, 'kx': kx}
        return _GRAPH


def _nearest(g, x, y):
    cx, cy = math.floor(x/CELL), math.floor(y/CELL)
    points = [p for i in range(cx-2, cx+3) for j in range(cy-2, cy+3) for p in g['grid'].get((i, j), [])]
    return sorted(points, key=lambda p: math.hypot(p[0]-x, p[1]-y))[:3]


def _astar(adj, start, end):
    heuristic = lambda p: math.hypot(p[0]-end[0], p[1]-end[1])
    queue, costs, parents = [(heuristic(start), 0, start)], {start: 0}, {}
    steps = 0
    while queue and steps < 35000:
        _, cost, node = heapq.heappop(queue)
        if cost != costs.get(node):
            continue
        if node == end:
            path = [node]
            while node in parents:
                node = parents[node]
                path.append(node)
            return list(reversed(path)), cost
        steps += 1
        for neighbor, distance in adj[node].items():
            next_cost = cost + distance
            if next_cost < costs.get(neighbor, float('inf')):
                costs[neighbor], parents[neighbor] = next_cost, node
                heapq.heappush(queue, (next_cost+heuristic(neighbor), next_cost, neighbor))
    return None


@lru_cache(maxsize=4096)
def _path(lat1, lon1, lat2, lon2):
    direct = [[lat1, lon1], [lat2, lon2]]
    direct_length = _length(direct)
    if direct_length < 3:
        return direct, direct_length, 'direct_connector'
    g = _load()
    xy = lambda lat, lon: ((lon-g['lon'])*g['kx'], (lat-g['lat'])*111320)
    a, b = xy(lat1, lon1), xy(lat2, lon2)
    starts, ends = _nearest(g, *a), _nearest(g, *b)
    options = []
    # Endpoint connectors join building centers to the nearest mapped network.
    for start in starts:
        for end in ends:
            connector = math.dist(a, start) + math.dist(b, end)
            if math.dist(a, start) > 100 or math.dist(b, end) > 100:
                continue
            result = _astar(g['adj'], start, end)
            if result and result[1] + connector < direct_length * 3.5 + 150:
                options.append((result[1]+connector, result[0]))
        if options:
            break
    if options:
        _, path = min(options, key=lambda x: x[0])
        points = [direct[0]] + [[g['lat']+y/111320, g['lon']+x/g['kx']] for x, y in path] + [direct[1]]
        return points, _length(points), 'osm_network_estimate'
    return direct, direct_length * 1.22, 'straight_line_fallback'


def route(a, b):
    points, distance, source = _path(*(round(v, 7) for v in [a[0], a[1], b[0], b[1]]))
    return {'geometry': [list(p) for p in points], 'distance_m': distance, 'source': source}
