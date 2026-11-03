# Delay quantile models

**Status:** empty — no trained artifacts found in `../stinger-delay` (notebooks train in-memory only).

Drop an exported model here to activate `services/api/app/delays.py`:

- `delay_quantile.joblib` (preferred) or `delay_quantile.pkl`
- Expected API: `predict([[eta_seconds]]) -> [p10, p50, p90]` additive delay seconds  
  or `predict_quantiles([[eta_seconds]]) -> [[p10, p50, p90]]`

Until then the API uses `data/derived/delay_quantiles.json`.
