# Buzz Route · StingerD-GPT

A local web implementation of the StingerDelay-3D travel-assistant vision. Plan across Georgia Tech, explore a real 3D campus, replay Stinger GPS, build a calendar-driven day, and ask for verified travel guidance.

## Run

Python 3.11+ is the only runtime dependency. No Node, package installation, API keys, or network access is needed for the demo.

```sh
cd /Users/yuyanglin/Desktop/GT/Grokathon/StingerD-GPT
./start.sh
```

Open **http://127.0.0.1:8765**. Stop with Ctrl-C. Use `./start.sh --port 8766` for another port; update the Google redirect URI if you change it. The server binds to loopback by default. This is a local single-user development server, not a production deployment.

## Implemented experience

- Interactive Three.js campus: buildings, roads, green space, route polylines, labelled landmarks, orbit/zoom, top-down view, and lighting. All renderer assets are bundled locally; Canvas2D fallback works when WebGL fails.
- Historical GPS buses on Red/Green/Gold/Clough; synthetic Blue is marked. Replay clock, scrubbing, speed, bus/label toggles.
- Twelve campus destinations, walking/transit comparison, forward route direction, optional one-transfer candidates, replay-derived stop crossing times, missed-bus handling, and timetable fallback when coverage ends.
- Leave-now/depart-at/arrive-by planning, travel preferences, latest departure search, per-leg instructions, alternatives, p10/p50/p90, catch/on-time probabilities, and horizon-aware spread.
- Opt-in demonstration crowd uncertainty; it widens transit uncertainty rather than changing the median.
- Trip simulation with progress, segment guidance, and a “Test delay + replan” action from simulated current coordinates.
- Next-class planning and a chained daily schedule. Demo classes work immediately; Google Calendar can be connected with server credentials.
- Local saved trips and imported calendar events in IndexedDB. View, refresh, and delete routes. JSON and basic single-occurrence timed `.ics` import; add classes by hand. Recurring .ics rules must be expanded first; Google Calendar expands recurrence itself.
- In-app helper with verified template responses, destination/time requests, imported-calendar context, server-trusted alternative explanations, optional live Grok, browser speech recognition where supported, and browser text-to-speech for voice requests.
- Same-origin JSON API, OpenAPI, TripTrace JSON Schema, request validation, numeric verification, and structured integration states.
- Read-only upstream GitHub checks every five minutes **while this server runs**. No automatic pull, merge, push, or edits to sibling projects.

## Suggested demo

1. Plan Student Center → Klaus. Compare walking with a bus alternative, or choose Options → Prefer bus.
2. Select Arrive by and choose a time in Atlanta. Review the leave-by recommendation and uncertainty.
3. Save the route and open Saved. Refresh before using a saved estimate.
4. Start the trip simulation. Select “Test delay + replan” to inject a bus delay and reroute from the simulated position.
5. Open My day → Plan my day. Select an event’s arrow to inspect its route on the map.
6. Ask the helper “When should I leave for my next class?” or “Plan a path to Klaus by 10:30 AM.”
7. Open Connections to inspect integrations and the latest upstream revision.

## Optional real integrations

Credentials stay in the server process; none are stored in the browser or committed. `.env.example` documents supported variables; the server reads environment variables, not `.env` files.

### Grok

Set `XAI_API_KEY` in the server environment. `XAI_MODEL` selects a compatible xAI Responses model; choose one available to your account. Without a key, or on provider/verification failure, responses use the planner-grounded template. Browser voice is browser speech input/output, **not an xAI realtime Voice Agent session**. No API credentials were available to test real provider requests in this implementation.

### Google Calendar

Create a Google OAuth web client with the read-only Calendar scope and redirect URI `http://127.0.0.1:8765/auth/google/callback`. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and optionally `GOOGLE_REDIRECT_URI`. Open the app using the same hostname as the redirect URI (127.0.0.1 and localhost have separate cookies), then Connections → Connect.

Alternatively set `GOOGLE_CALENDAR_ACCESS_TOKEN` to a valid short-lived read-only token. OAuth access/refresh tokens are held only in server memory and are lost on restart. Calendar reads cover upcoming timed events in the primary calendar; unresolved places remain unresolved. No calendar writes or invitations occur. API failures are labelled as a demo fallback.

### X and live transit

The X surface is an explicit **demo signal**, not a live social feed. Live transit ingestion, trained model deployment, production OAuth persistence, and xAI realtime Voice remain future integration work. No invented weights or live status are presented.

## Accuracy and scope

The planner is `replay_baseline_v0`, with reproducible seeded sampling. It uses historical route timings and replay crossings; its uncertainty is an **uncalibrated demo heuristic**, not a deployed Stinger Delay model or learned ETA-decile table. The source research’s reported 44–54% MAE improvement does not apply to this app. Map routes replay different March 2026 weekdays and do not represent one synchronized live day.

Walking connectors use straight-line distance with a detour factor. Paths may cross buildings or non-walkable space. Closures, crossings, entrances, elevation, and stairs are not verified. Requesting stair avoidance shows a limitation rather than promising accessibility. Probabilities are illustrative and should not be treated as reliable travel guarantees.

Leave-now uses the visible replay clock; depart/arrive inputs include a travel date in Atlanta. Calendar events retain their own dates. Long-horizon estimates widen and should be checked again closer to travel. The replay runs within its recorded service window; outside coverage, schedule fallback is explicitly identified.

## API and tests

```sh
python3 -m unittest discover -s tests -v
python3 scripts/check_upstream.py
```

Main endpoints: `GET /health`, `/places`, `/routes`, `/calendar/events`, `/calendar/next`, `/integrations/status`, `/signals/x`, `/upstream`; `POST /trips/plan`, `/trips/verify`, `/schedule`, `/grok/chat`, `/calendar/import`. `/api/...` aliases are available. Pass `evaluate_at` with `arrive_by` to assess a fixed departure against an arrival deadline instead of searching for the latest leave time. OpenAPI: `/openapi.json`; schema: `/contracts/trip-trace.json`. See `docs/INTERFACE.md` and `docs/local_plan_v0.json`.

Tests cover trace consistency, forward stop alignment, replay crossings/missed buses, arrival targets, horizon and crowd spread, invalid input, synthetic Blue, trusted alternative explanations, OAuth state, calendar imports, and HTTP workflows. Browser QA covers the map, bus planning, saved routes, schedules, helper, simulation, and responsive layout. Optional live provider calls require credentials and were not exercised.

## Upstream and project isolation

Source: https://github.com/danmano411/StingerDelay-3D. The initial map/routes snapshot was copied into this folder. The watcher compares the sibling checkout HEAD with remote HEAD, records commit summaries in `docs/upstream-state.json`, and exposes them in Connections. Watching does not automatically incorporate code or asset changes. If both the upstream checkout and remote move together, compare the recorded implementation baseline in `docs/UPSTREAM.md` to decide what to adopt. Network failures retain the last successful revision.

The sibling `StingerDelay-3D`, its iOS tree, `StingerD-Grok`, and original `stinger-delay` are untouched. This project uses browser ES modules and a Python stdlib server so it runs on this machine without installing a frontend toolchain. Contracts are JSON-first and can be served by a future FastAPI adapter.

## Data and licenses

Campus geometry from OpenStreetMap contributors (ODbL): https://www.openstreetmap.org/copyright. Historical GT Stinger data and route geometry copied from the upstream project. Upstream source licensing should be reviewed before redistribution. Three.js 0.170.0 is bundled under MIT; see `web/assets/vendor/THREE-LICENSE.txt`.
