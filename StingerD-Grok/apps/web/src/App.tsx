import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { API_BASE, fetchHealth, planTrip } from "./api";
import { ExplainPanel } from "./ExplainPanel";
import { PlanCard } from "./PlanCard";
import type { PlanExplanation, TripTrace } from "./types";
import "./App.css";

/** Demo presets on Georgia Tech campus */
const PRESETS = {
  "CRC → Klaus": {
    origin: { lat: 33.7758, lon: -84.4025 },
    destination: { lat: 33.7772, lon: -84.3956 },
  },
  "Student Center → Midtown MARTA": {
    origin: { lat: 33.7738, lon: -84.3986 },
    destination: { lat: 33.7812, lon: -84.3867 },
  },
  "West Campus → Clough": {
    origin: { lat: 33.7783, lon: -84.4042 },
    destination: { lat: 33.7753, lon: -84.3961 },
  },
  "North Ave → Tech Square (xfer-friendly)": {
    origin: { lat: 33.7710, lon: -84.3910 },
    destination: { lat: 33.7765, lon: -84.3890 },
  },
} as const;

type PresetKey = keyof typeof PRESETS;
type Tab = "plan" | "campus";

const LAST_PLAN_KEY = "stingerd-grok:last-plan";

function highlightPayload(explain?: PlanExplanation | null) {
  if (!explain?.highlight) return null;
  return {
    type: "stingerd-highlight" as const,
    ...explain.highlight,
    label: explain.summary,
  };
}

function highlightQuery(explain?: PlanExplanation | null): string {
  const q = new URLSearchParams({ embed: "1" });
  if (explain?.highlight) {
    const h = explain.highlight;
    if (h.route_ids?.length) q.set("routeIds", h.route_ids.join(","));
    if (h.route_names?.length) q.set("routeNames", h.route_names.join(","));
    if (h.stop_names?.length) q.set("stopNames", h.stop_names.slice(0, 12).join(","));
  }
  // Keep URL short — full polylines go via postMessage
  return `/campus-3d/index.html?${q.toString()}`;
}

function App() {
  const [tab, setTab] = useState<Tab>("plan");
  const [preset, setPreset] = useState<PresetKey>("CRC → Klaus");
  const [health, setHealth] = useState<string>("checking…");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<TripTrace | null>(null);
  const [arriveBy, setArriveBy] = useState("");
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const explain = trace?.explain ?? trace?.chosen?.explain;
  const campusSrc = useMemo(() => highlightQuery(explain), [explain]);

  useEffect(() => {
    fetchHealth()
      .then((h) => setHealth(`${h.status} · ${h.routes_loaded} routes`))
      .catch((e) => setHealth(`down (${e.message})`));
    try {
      const raw = localStorage.getItem(LAST_PLAN_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw) as {
        preset?: PresetKey;
        arriveBy?: string;
        trace?: TripTrace;
      };
      if (saved.preset && saved.preset in PRESETS) setPreset(saved.preset);
      if (typeof saved.arriveBy === "string") setArriveBy(saved.arriveBy);
      if (saved.trace?.chosen) setTrace(saved.trace);
    } catch {
      /* ignore corrupt cache */
    }
  }, []);

  useEffect(() => {
    if (!trace) return;
    try {
      localStorage.setItem(
        LAST_PLAN_KEY,
        JSON.stringify({ preset, arriveBy, trace, savedAt: Date.now() })
      );
    } catch {
      /* quota / private mode */
    }
  }, [trace, preset, arriveBy]);

  function pushHighlight() {
    const payload = highlightPayload(explain);
    if (!payload || !iframeRef.current?.contentWindow) return;
    iframeRef.current.contentWindow.postMessage(payload, "*");
  }

  useEffect(() => {
    if (tab !== "campus") return;
    pushHighlight();
  }, [trace, tab, campusSrc]);

  async function onPlan(e?: FormEvent) {
    e?.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const pts = PRESETS[preset];
      const body = {
        origin: pts.origin,
        destination: pts.destination,
        ...(arriveBy
          ? { arrive_by: new Date(arriveBy).toISOString() }
          : {}),
        prefs: { on_time_target: 0.85, walk_speed_mps: 1.35 },
      };
      const result = await planTrip(body);
      setTrace(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <header className="hero">
        <p className="brand">StingerD-Grok</p>
        <h1>TripTrace planner backbone</h1>
        <p className="lede">
          Deterministic walk → wait → ride → (transfer) → walk plans with
          confidence bands. Numbers come only from the API <code>TripTrace</code>.
        </p>
        <p className="status">
          API <code>{API_BASE}</code> — {health}
        </p>
        <nav className="tabs" aria-label="Primary">
          <button
            type="button"
            className={tab === "plan" ? "on" : ""}
            onClick={() => setTab("plan")}
          >
            Plan
          </button>
          <button
            type="button"
            className={tab === "campus" ? "on" : ""}
            onClick={() => setTab("campus")}
          >
            3D campus
          </button>
          <a className="tab-link" href={campusSrc} target="_blank" rel="noreferrer">
            Open 3D fullscreen
          </a>
        </nav>
      </header>

      {tab === "campus" ? (
        <section className="campus-panel">
          <p className="muted">
            Twin overlay: walk polylines (gold) + ride segments + stop beacons via
            postMessage.
            {explain?.highlight?.polylines?.length
              ? ` ${explain.highlight.polylines.length} path segment(s) queued.`
              : " Plan a trip first to draw the path."}
          </p>
          <iframe
            ref={iframeRef}
            title="GT campus 3D simulation"
            src={campusSrc}
            className="campus-frame"
            onLoad={pushHighlight}
          />
        </section>
      ) : (
        <>
          <form className="controls" onSubmit={onPlan}>
            <label>
              Campus preset
              <select
                value={preset}
                onChange={(e) => setPreset(e.target.value as PresetKey)}
              >
                {Object.keys(PRESETS).map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Arrive by (optional)
              <input
                type="datetime-local"
                value={arriveBy}
                onChange={(e) => setArriveBy(e.target.value)}
              />
            </label>
            <button type="submit" disabled={loading}>
              {loading ? "Planning…" : "Plan trip"}
            </button>
          </form>

          {error && <p className="error">{error}</p>}

          {trace && (
            <div className="results">
              <p className="meta">
                request <code>{trace.request_id}</code> · mode{" "}
                <code>{trace.mode}</code> · predictor{" "}
                <code>{String(trace.meta?.predictor ?? "—")}</code> · walk nodes{" "}
                <code>{String(trace.meta?.walk_nodes ?? "—")}</code>
                {trace.meta?.road_polylines != null && (
                  <>
                    {" "}
                    · roads <code>{String(trace.meta.road_polylines)}</code>
                  </>
                )}
                {" · "}
                <button
                  type="button"
                  className="linkish"
                  onClick={() => {
                    localStorage.removeItem(LAST_PLAN_KEY);
                    setTrace(null);
                  }}
                >
                  clear saved plan
                </button>
              </p>
              <ExplainPanel trace={trace} plan={trace.chosen} />
              <PlanCard plan={trace.chosen} />
              {trace.alternatives.map((alt, i) => (
                <PlanCard
                  key={alt.plan_id}
                  plan={alt}
                  title={`Alternative ${i + 1}`}
                  compactExplain
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default App;
