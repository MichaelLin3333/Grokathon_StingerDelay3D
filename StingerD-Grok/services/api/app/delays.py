from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from .data_loader import repo_root
from .models import Quantiles

# Searched ../stinger-delay (2026-11-02): no exportable trained artifacts found
# (no .pkl / .joblib / .onnx / .pt quantile models outside notebooks/venv).
# Available: GPS CSVs + notebooks that *train* models in-memory.
# Until Analysis exports joblib/pickle weights, we use empirical ETA-bin quantiles
# from data/derived/delay_quantiles.json (built from red_line GPS + summary blend).
#
# TODO: export HistGradientBoosting / ExtraTrees / XGB from Analysis notebooks to
#   data/models/delay_quantile.{joblib,pkl} and load via try_load_trained_model().

MODEL_CANDIDATES = (
    "data/models/delay_quantile.joblib",
    "data/models/delay_quantile.pkl",
    "data/models/quantile_model.joblib",
)


@lru_cache(maxsize=1)
def try_load_trained_model() -> Optional[Any]:
    """Return a loaded sklearn-like model if present; else None."""
    root = repo_root()
    for rel in MODEL_CANDIDATES:
        path = root / rel
        if not path.exists():
            continue
        try:
            if path.suffix == ".joblib":
                import joblib  # type: ignore

                return joblib.load(path)
            import pickle

            with path.open("rb") as f:
                return pickle.load(f)
        except Exception as exc:  # noqa: BLE001 — surface in meta, keep heuristic
            print(f"[delays] failed to load {path}: {exc}")
            return None
    return None


@lru_cache(maxsize=1)
def load_delay_table() -> dict[str, Any]:
    path = repo_root() / "data" / "derived" / "delay_quantiles.json"
    if not path.exists():
        return {
            "bins": [],
            "headway_wait_s": {"p10_s": 60, "p50_s": 240, "p90_s": 480},
            "todos": ["Run scripts/build_delay_quantiles.py"],
        }
    with path.open() as f:
        return json.load(f)


def delay_quantiles_for_eta(eta_s: float) -> Quantiles:
    """Return additive delay quantiles for a base travel/ETA of eta_s seconds."""
    model = try_load_trained_model()
    if model is not None:
        # Expected contract if/when exported: model.predict([[eta_s]]) -> [p10,p50,p90]
        # or model with .predict_quantiles. Keep heuristic fallback on any error.
        try:
            if hasattr(model, "predict_quantiles"):
                q = model.predict_quantiles([[eta_s]])[0]
                return Quantiles(p10_s=float(q[0]), p50_s=float(q[1]), p90_s=float(q[2]))
            pred = model.predict([[eta_s]])[0]
            if hasattr(pred, "__len__") and len(pred) >= 3:
                return Quantiles(
                    p10_s=float(pred[0]), p50_s=float(pred[1]), p90_s=float(pred[2])
                )
        except Exception as exc:  # noqa: BLE001
            print(f"[delays] trained model predict failed: {exc}")

    table = load_delay_table()
    bins = table.get("bins") or []
    chosen = None
    for b in bins:
        lo = float(b.get("eta_lo_s", 0))
        hi = float(b.get("eta_hi_s", 1e9))
        if lo < eta_s <= hi:
            chosen = b
            break
    if chosen is None and bins:
        chosen = bins[-1]
    if not chosen:
        return Quantiles(p10_s=30, p50_s=180, p90_s=400)
    return Quantiles(
        p10_s=float(chosen.get("delay_p10_s") or 0),
        p50_s=float(chosen.get("delay_p50_s") or 0),
        p90_s=float(chosen.get("delay_p90_s") or 0),
    )


def apply_delay(base_s: float) -> Quantiles:
    d = delay_quantiles_for_eta(base_s)
    return Quantiles(
        p10_s=max(0.0, base_s + d.p10_s),
        p50_s=max(0.0, base_s + d.p50_s),
        p90_s=max(0.0, base_s + d.p90_s),
    )


def headway_wait_quantiles() -> Quantiles:
    w = load_delay_table().get("headway_wait_s") or {}
    return Quantiles(
        p10_s=float(w.get("p10_s", 60)),
        p50_s=float(w.get("p50_s", 240)),
        p90_s=float(w.get("p90_s", 480)),
    )


def predictor_meta() -> dict[str, Any]:
    table = load_delay_table()
    trained = try_load_trained_model() is not None
    todos = list(table.get("todos") or [])
    todos.append(
        "No trained weights in stinger-delay checkout — export joblib to data/models/"
    )
    return {
        "predictor": (
            "trained-quantile-model" if trained else "empirical-eta-bin-quantiles"
        ),
        "trained_model_loaded": trained,
        "delay_table": str(
            (repo_root() / "data" / "derived" / "delay_quantiles.json").relative_to(
                repo_root()
            )
        ),
        "model_search_paths": list(MODEL_CANDIDATES),
        "todos": todos,
        "note": table.get("method"),
    }
