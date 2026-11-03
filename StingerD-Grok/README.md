# StingerD-Grok

Working backbone for the StingerDelay-3D vision: deterministic trip planner (`TripTrace`) + web shell.

Plans/source: nearby `../StingerDelay-3D`  
Delay research source: nearby `../stinger-delay`

## Layout

| Path | Purpose |
|---|---|
| `apps/web/` | React + TypeScript (Vite) plan UI |
| `services/api/` | FastAPI planner + health |
| `data/base/` | Routes + campus geometry (from StingerDelay-3D) |
| `docs/` | Copied product vision / plan notes |
| `reference/` | Stinger Delay model summary |
| `scripts/` | Dev helpers |

## Run locally

```bash
# Optional: rebuild delay quantile table from ../stinger-delay GPS
python3 scripts/build_delay_quantiles.py

# API (port 8000) — bind all interfaces so LAN / Cursor preview can reach it
cd services/api
python3 -m pip install -r requirements.txt
python3 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Web (port 5173) — separate terminal; Vite proxies /api → :8000
cd apps/web
npm install
npm run dev
```

- Web (use this): http://127.0.0.1:5173/ — API calls go through `/api` proxy  
- Direct API health: http://127.0.0.1:8000/health  
- API docs: http://127.0.0.1:8000/docs  
- Plan: `POST /trips/plan` · verify: `POST /trips/verify`  
- 3D campus (stripped of solar/energy chrome): http://127.0.0.1:5173/campus-3d/?embed=1  

Leave stinger-delay Data-Viz on :3000 alone. Upstream StingerDelay-3D also serves raw `web-sim/` on **8080** (`python -m http.server 8080`) — that is the visual baseplate, not the planner API.

## Delay quantiles

`data/derived/delay_quantiles.json` is built from `../stinger-delay/Platform/red_line` ETA polls, blended with the published model-summary lateness. No trained `.pkl` weights are checked in yet — see TODOs in that JSON.
