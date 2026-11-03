#!/usr/bin/env python3
"""Build an offline search catalog from supplied OSM buildings and transit stops."""
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build():
    twin = json.loads((ROOT / 'web/assets/campus.json').read_text())
    routes = json.loads((ROOT / 'data/routes.json').read_text())
    landmarks = json.loads((ROOT / 'data/landmarks.json').read_text())
    lat0, lon0 = twin['meta']['origin']
    catalog = [{**place, 'kind': 'landmark', 'source': 'curated campus landmark'} for place in landmarks]
    for building in twin['buildings']:
        name = str(building.get('n', '')).strip()
        p = building.get('p', [])
        if not name or len(p) < 6:
            continue
        xs, ys = p[::2], p[1::2]
        lat = lat0 + sum(ys) / len(ys) / 111320
        lon = lon0 + sum(xs) / len(xs) / (111320 * math.cos(math.radians(lat0)))
        if not (33.76 <= lat <= 33.80 and -84.42 <= lon <= -84.37):
            continue
        ident = hashlib.sha256((name + str(p)).encode()).hexdigest()[:12]
        catalog.append({'id': 'building-' + ident, 'name': name, 'lat': round(lat, 7), 'lon': round(lon, 7),
                        'kind': 'building', 'source': 'OpenStreetMap campus snapshot'})
    stops = {}
    for route in routes:
        for stop in route['stops']:
            stops.setdefault(str(stop['id']), {'id': 'stop-' + str(stop['id']), 'name': stop['name'].strip(),
                'lat': stop['lat'], 'lon': stop['lon'], 'kind': 'stop', 'source': 'Stinger route snapshot'})
    catalog.extend(sorted(stops.values(), key=lambda p: p['name']))
    # Names can repeat for separate buildings/stops; ids remain unique.
    (ROOT / 'data/places.json').write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + '\n')
    return catalog


if __name__ == '__main__':
    places = build()
    print(f'Built {len(places)} searchable places from buildings, stops, and landmark aliases.')
