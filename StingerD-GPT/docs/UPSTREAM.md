# Upstream implementation baseline

Repository: https://github.com/danmano411/StingerDelay-3D

Initial source inspected: `38869af84336624818ea5627fa7cbf6805050973` (web execution plan and iOS handshake). Snapshot map and route files came from this local checkout.

Subsequently reviewed:

- `1df9759afd5bac2489cdc473cd25ecfd62b92a18`: SwiftUI iOS app added. Separate client; no web API change.
- `e618f1efbfe6741a1cbec3777bc278c588fd7b01`: iOS MapKit uses base Stinger routes. Web already uses the corresponding base route geometry.

- `8aea9b87863e3c9ff40f3a7bd604d49b511c0017`: embeds the 3D twin in iOS WKWebView; no shared API/data contract change.
- `79a566259d7db4ea4b5a1fd157fb3507b23e4e01`: includes vendored Three module in iOS; web already bundles the same dependency.
- `9480aeaa91cf17b8952d638ac710d7d9a9eceb28`: preserves the Twin folder structure in iOS; no web compatibility change.

No upstream files were modified or automatically merged. The running server polls GitHub every 300 seconds and writes observation state to `upstream-state.json`.

Differences from the suggested implementation plan: this isolated folder uses native browser ES modules and a dependency-free Python HTTP API rather than Vite/React/FastAPI. This avoids installing missing runtimes on the user's computer. The supplied API/schema preserve a migration path. ETA uncertainty is explicitly an uncalibrated replay baseline; the summary does not contain enough trained weights or decile statistics to reproduce the research model.

## Latest alignment audit

Reviewed through `fff8ca945c115ab1fab751359d4a8150759895da`. Significant shared web/API/assistant/3D/weekly-calendar changes have landed. Product alignment remains; contract compatibility and newer features require adoption. See [ALIGNMENT.md](ALIGNMENT.md). Reviewed revision is separate from the implementation baseline.
