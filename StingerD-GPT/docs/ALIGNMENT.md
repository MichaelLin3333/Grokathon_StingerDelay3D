# Alignment audit: StingerD-GPT vs StingerDelay-3D

Reviewed GitHub main through `fff8ca945c115ab1fab751359d4a8150759895da` (Nov 2, 2026, 8:44 PM America/New_York). The source was updated repeatedly during this audit. Review includes full files at a3dc14a and the following fff8ca9 changes. Local source initially lagged GitHub, so remote pinned files were used. No upstream files were changed.

## Conclusion

The web app matches the product direction and core demo flows, but is a separate implementation and is not compatible with the newly committed shared API/assistant/3D bridge. Reviewed does not mean merged or synchronized.

## What remains aligned

- Both build campus walking + Stinger navigation, with replay-first 3D, segmented plans, arrival ranges, catch/on-time probabilities, calendar planning and verified explanations.
- The copied base routes.json and campus.json are byte-identical to the current source base files at audit time.
- Both mark Blue synthetic, keep credentials server-side, and require numeric grounding. StingerD-GPT already has an independent renderer, saved plans, optional Google OAuth, template/live text helper, and delay-triggered simulation replanning.
- Neither implementation establishes calibrated production arrival guarantees or a verified stairs/accessibility graph. The upstream road graph newly added in fff8ca9 is explicitly display-only, not a source of travel times.

## Concrete drift

| Area | Upstream now | StingerD-GPT now | Required alignment |
| --- | --- | --- | --- |
| Planning request | `{constraints:{origin:{lat,lon,place_id},destination:...,prefs:{walk_speed_mps,avoid_stairs}}}` | Flat origin/destination/prefs | Add adapter or converge on shared request schema |
| Planning response | `{trace,contract_version}`, with `trace.plan.total_s` | Bare trace, `chosen.quantiles` in minutes | Explicit seconds/minutes conversion and response mapping |
| Trace state | `status: ok / at_risk`, `verification_version`, `confidence_horizon_s` | Warnings and separate constraints/probabilities, no canonical status | Adopt shared fields with tested semantics |
| Place data | Normalized ids/coordinates, e.g. `marta-midtown` | Seeded places, e.g. `midtown-marta`, several coordinate differences | Use one canonical place dataset plus aliases |
| Assistant | Conversation IDs, state patches, actual Responses function-tool loop, show_path/walk/stop actions | Cached trace + regex intents + optional Grok explanation | Adopt conversational contract, stacked time/origin/preferences, navigation actions |
| 3D integration | sim_bridge v0: plan.show, plan.clear, walk.start/stop, camera.focus; sim.ready/pick and walk.progress/done | Direct CampusMap class, separate renderer | Implement/embed shared bridge and preserve fallback |
| Walking display | A* on scene road network for display, dashed walking and route-colored rides | Straight walking connectors, solid paths with different colors | Adopt display paths and distinguish leg styles; keep timing caveat |
| Schedule | Today + Mon–Fri, /routes/week, weekly RRULE BYDAY expansion, saved weekly plans | One daily schedule, saved individual plans; recurring ICS explicitly rejected | Add weekly view, recurrence handling and matching persistence |
| Calendar endpoints | /calendar/day, /calendar/status, /day/plan, /routes/week | /calendar/events, /integrations/status, /schedule | Add aliases/adapters rather than discard existing functionality |
| X | Partial cached x_search/citation-link fetch at /signals/x/feed; plan calls for mapped, confidence-gated, budgeted widening | Demo crowd toggle only | Add feed states, citations, freshness and conservative factor policy |
| Voice | Server /grok/transcribe route exists; current UI still uses browser recognition | Browser recognition + device speech synthesis | Add optional server transcription; full realtime voice remains separate work |

The canonical source of shared contract details is current services/api/contracts plus OpenAPI. Some older upstream README/curl descriptions are stale (e.g. planner stub descriptions).

## Runtime proof of incompatibility

Sent an upstream-shaped `{constraints:...}` request to the running StingerD-GPT `/trips/plan`: HTTP 422, `origin and destination are required`. The local `/routes/week`, `/grok/status`, `/signals/x/feed` and GET `/day/plan` were 404; code inspection confirms POST `/day/plan` is not registered either. These paths are not implemented by the same-named local APIs.

## Priority

1. Converge on one shared API and versioned TripTrace contract; preserve the current UI through a compatibility layer. Add contract tests for wrappers, units, place ids, status, day plans and assistant actions.
2. Adopt accumulated conversational constraints and the shared 3D bridge, with navigation start/stop and step progress.
3. Add weekly schedules/RRULE support and road-following display paths.
4. Add the X feed, server transcription and conservative disruption integration. Do not claim optional live integrations work until tested with credentials.

Full WebSocket sessions, continuous real GPS rerouting, realtime xAI voice and calibrated trained prediction remain larger full-spec work. Their presence in a plan is not evidence of a working deployment.

## Monitor repair made during audit

The local server responded, but its background watcher had a failed GitHub check. The watcher now checks the GitHub API independently of local Git access and falls back to Git transport. Stale commit details are identified, remote errors remain explicit, and last successful in-process revisions are retained. The integration UI distinguishes known alignment gaps from unreviewed commits. Regression tests cover both transport paths and failure retention. This audit did not merge upstream feature code.

Deployment note: watcher changes are saved and tested. Restarting the existing background process was blocked by current process permissions; its in-memory watcher code has not been replaced. A manual check with the repaired watcher succeeded against GitHub.
