from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    # services/api/app/data_loader.py → repo root
    return Path(__file__).resolve().parents[3]


def data_root() -> Path:
    return repo_root() / "data" / "base"


@lru_cache(maxsize=1)
def load_routes() -> list[dict[str, Any]]:
    path = data_root() / "routes.json"
    with path.open() as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_campus() -> dict[str, Any]:
    path = data_root() / "campus.json"
    with path.open() as f:
        return json.load(f)
