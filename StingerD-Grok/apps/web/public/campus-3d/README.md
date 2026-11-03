# 3D Campus Simulation (baseplate)

Self-contained Three.js scene of the Georgia Tech campus with Stinger buses.

## Run locally

```bash
cd web-sim
python -m http.server 8080
# open http://localhost:8080
```

- Buildings, roads, and green space from OpenStreetMap
- Buses replay real Stinger Delay GPS (March 2026), map-matched to routes
- Sun and shadows follow real solar geometry (kept for dynamic lighting)
- Blue buses are synthetic (no GPS logs)

Solar/materials/energy panes are still in the UI for now but can be ignored or stripped later. The map and buses are the baseplate.
