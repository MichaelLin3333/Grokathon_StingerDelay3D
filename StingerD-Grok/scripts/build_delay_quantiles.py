#!/usr/bin/env python3
"""Derive delay quantile bins from nearby stinger-delay GPS ETA polls.

No trained model weights ship in-repo. Estimates TransLoc ETA error from
red_line_data.csv, blends with published summary lateness, writes
data/derived/delay_quantiles.json.

TODO: replace with HistGradientBoosting / ExtraTrees / XGB artifacts once
exported from Analysis notebooks.
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "derived" / "delay_quantiles.json"
RED = (
    Path(__file__).resolve().parents[2]
    / "stinger-delay"
    / "Platform"
    / "red_line"
    / "data"
    / "red_line_data.csv"
)

BINS = [
    (0, 120, "under_2_min"),
    (120, 300, "2_to_5_min"),
    (300, 600, "5_to_10_min"),
    (600, 1200, "10_to_20_min"),
    (1200, 10_000, "20_plus_min"),
]

# From reference/stinger-delay-summary.md lateness patterns (seconds)
SUMMARY = {
    "under_2_min": (20, 90, 180),
    "2_to_5_min": (40, 150, 320),
    "5_to_10_min": (60, 220, 450),
    "10_to_20_min": (80, 320, 600),
    "20_plus_min": (100, 400, 750),
}


def parse_ts(s: str) -> datetime:
    s = s.strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")


def percentile(vals: list[float], p: float) -> float:
    vals = sorted(vals)
    k = (len(vals) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return vals[int(k)]
    return vals[f] * (c - k) + vals[c] * (k - f)


def main() -> None:
    if not RED.exists():
        raise SystemExit(f"missing GPS source: {RED}")

    series: dict[tuple[str, str], list[tuple[datetime, float]]] = defaultdict(list)
    with RED.open(newline="") as f:
        for row in csv.DictReader(f):
            try:
                eta = float(row["eta_seconds"])
                if not (0 < eta <= 3600):
                    continue
                key = (str(row["vehicle_id"]), str(row["route_stop_id"]))
                series[key].append((parse_ts(row["snapshot_time_utc"]), eta))
            except Exception:
                continue

    errors: dict[str, list[float]] = {name: [] for _, _, name in BINS}
    for pts in series.values():
        pts = sorted(pts)
        if len(pts) < 3:
            continue
        arrival = next((t for t, eta in pts if eta <= 45), None)
        if arrival is None:
            continue
        for t, eta in pts:
            if t >= arrival:
                break
            err = max(-180.0, min(600.0, (arrival - t).total_seconds() - eta))
            for lo, hi, name in BINS:
                if lo < eta <= hi:
                    errors[name].append(err)
                    break

    bins_out = []
    for lo, hi, name in BINS:
        vals = errors[name]
        n = len(vals)
        sp10, sp50, sp90 = SUMMARY[name]
        if n >= 30:
            ep10, ep50, ep90 = percentile(vals, 0.10), percentile(vals, 0.50), percentile(vals, 0.90)
            # Blend empirical with summary; clamp upper tail for planning stability
            p10 = 0.4 * ep10 + 0.6 * sp10
            p50 = max(ep50, sp50 * 0.7)
            p90 = min(max(ep90, sp90 * 0.8), sp90 * 1.35)
            ordered = sorted([p10, p50, p90])
            p10, p50, p90 = ordered
            source = "red_line_blended_summary"
        else:
            p10, p50, p90 = sp10, sp50, sp90
            source = "summary_fallback_thin_sample"
        bins_out.append(
            {
                "name": name,
                "eta_lo_s": lo,
                "eta_hi_s": hi,
                "n": n,
                "delay_p10_s": round(p10, 1),
                "delay_p50_s": round(p50, 1),
                "delay_p90_s": round(p90, 1),
                "source": source,
            }
        )

    payload = {
        "generated_for": "StingerD-Grok",
        "source_file": str(RED),
        "method": (
            "ETA realization errors from red_line polls (eta<=45s ≈ arrival), "
            "winsorized, blended with stinger-delay summary lateness."
        ),
        "todos": [
            "Export trained HistGradientBoosting/ExtraTrees/XGB quantile predictors from Analysis notebooks",
            "Join stop/route/time-of-day features instead of ETA-only bins",
            "Add live TransLoc/GPS adapter to refresh delays in realtime",
        ],
        "bins": bins_out,
        "headway_wait_s": {"p10_s": 60, "p50_s": 240, "p90_s": 480},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {OUT}")
    for b in bins_out:
        print(b["name"], "n=", b["n"], b["delay_p10_s"], b["delay_p50_s"], b["delay_p90_s"], b["source"])


if __name__ == "__main__":
    main()
