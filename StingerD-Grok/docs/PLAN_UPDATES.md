# Incremental plan updates

## 2026-11-02 — Grok Bot + calendar + PRT-style UI + confidence bands

Added to the base Buzz Route spec:

- **In-app Grok Bot helper** (web first): “Hey Grok, using my calendar, when should I leave for the next event?”  
  Uses Google Calendar connector (next event only for now). Separate iOS Grok Bot handles mobile deployment later. Same backend tools.

- **PRT-style segmented plan card**:  
  Walk to stop → wait → ride → (optional transfer walk + wait + ride) → final walk.  
  Shows duration per segment + total ETA + `p_on_time`.

- **Accuracy bounds that widen with horizon**:  
  Near-term (bus < ~3 min): tight p10–p90, high confidence.  
  Far-term (≥ 60–90 min): wider bands + explicit “check again closer to departure” message.  
  Driven by Monte Carlo sampling over the Stinger Delay quantiles.

All numbers still come exclusively from the deterministic `TripTrace`. Verification required before display or speech.

See root `README.md` for repo hierarchy and ownership rules.
