# Product vision — StingerDelay-3D

**Grok Bot is the helper for Stinger Delay.** It uses three integrations:

1. **Grok Voice Agent API** — spoken requests and guidance
2. **Google Calendar** — next event / class schedule
3. **X (Twitter)** — secondary social signals (game days, crowds, spontaneous events)

The routing engine + Stinger Delay models still own every number. Grok interprets, fetches, speaks, and explains. Verification required.

## End-goal user flows

- “Hey Grok, using my calendar, when should I leave for the next event?”
- “If I leave now, will I be fine?”
- “Plan a path to Klaus by 8:30, avoid stairs.”
- “Look at my calendar, grab my classes, and create a bus schedule for the day.”
- Flick through a personal daily bus schedule that dynamically assigns buses based on current location, classes, and time.
- Path storage (local for now — simple JSON / IndexedDB, not a full database).

## Secondary social / uncertainty layer (not primary)

- X posts (and optionally location-tagged ones) feed an uncertainty signal.
- Game days, large events, or high post volume in an area → inflate wait/ride variance or add a crowd heatmap overlay.
- Inspired by waitz.io/gatech crowd levels, but driven by social signals + known events rather than sensors.
- Applied as a secondary multiplier or extra quantile spread on top of the Stinger Delay predictor. Never overrides the deterministic engine.
- Human approval or clear “social signal” badge required before it changes a plan.

## Executable breakdown (concurrent-friendly)

### Shared (do once, both web + iOS consume)
1. **Data contracts + TripTrace** — normalized stops, routes, walk graph, quantiles.
2. **Planner API** — `/trips/plan` returning segmented legs + p10/p50/p90 + p_on_time.
3. **Calendar tool** — next event → arrive_by + place resolve.
4. **X signal ingest** (secondary) — scheduled or on-demand, produces optional disruption/crowd factors.
5. **Local path storage schema** — simple saved plans keyed by day/class.

### Web (this agent / Cursor)
1. PRT-style segmented plan card + confidence bands.
2. Voice Agent relay + in-app Grok helper.
3. Calendar-driven “next event” and daily schedule view.
4. Replay + simulate-walk demo mode.

### iOS (separate agent — do not overlap)
1. Consume the same planner API.
2. Native map + voice.
3. Calendar + location.
4. Offline-capable local plan storage.

## Priority order
1. Deterministic planner + TripTrace + segmented UI (no Grok required for basic demo).
2. Voice + Calendar tools.
3. Personal daily schedule from calendar.
4. Secondary X/social uncertainty layer.
5. Polish, verification, explainability.

All agents: read `README.md` hierarchy first. Routing engine owns numbers. Social signals are secondary.
