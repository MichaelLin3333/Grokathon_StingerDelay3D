#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="${HOME}/.local/bin:${PATH}"
cd "$ROOT/services/api"
exec python3 -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
