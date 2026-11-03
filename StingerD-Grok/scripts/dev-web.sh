#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="${HOME}/.local/node/current/bin:${PATH}"
cd "$ROOT/apps/web"
exec npm run dev -- --host 127.0.0.1 --port 5173
