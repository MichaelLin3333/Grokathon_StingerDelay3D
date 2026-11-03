# Verification record

45 Python unit/HTTP integration tests pass using `python3 -m unittest discover -s tests -q`.

Browser checks completed in the connected local browser:

- 3D renderer loads entirely local assets and fits the map container.
- Walking, bus-preferred, selected alternative, and calendar arrive-by plans render.
- Saved plan remains visible in IndexedDB after navigation and reload.
- Demo classes generate three chained travel plans and show their leave times.
- Trip simulation starts, ends, and replans from simulated coordinates after a delay.
- Helper next-class and leave-now assessment return verified responses.
- Travel date distinguishes next-day calendar events.
- Connections surface shows demo/integration modes and upstream watch state.
- Mobile breakpoint at 390 × 844: document width equals viewport width, no horizontal overflow.
- Frontend modules parse; browser console has no JavaScript errors during the final core flow.

Google OAuth, real Calendar requests, live xAI inference, and hardware microphone/location permission flows were not exercised with credentials or user permission. X and transit live feeds are not implemented. Browser voice feature availability is detected at runtime.

Map baseline: real OSM geometry/historical route replay. Prediction and walking limitations are shown in UI and documented in README.
