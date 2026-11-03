import type { PlanExplanation, TripPlan, TripTrace } from "./types";

function fmtMin(s: number): string {
  return `${(s / 60).toFixed(1)} min`;
}

export function ExplainPanel({
  trace,
  plan,
}: {
  trace: TripTrace;
  plan: TripPlan;
}) {
  const explain: PlanExplanation | null | undefined =
    plan.explain ?? trace.explain;
  if (!explain) return null;

  const walkSegs =
    explain.highlight?.polylines?.filter((p) =>
      String(p.kind || "").includes("walk")
    ).length ?? 0;
  const rideSegs =
    explain.highlight?.polylines?.filter((p) => p.kind === "ride").length ?? 0;

  return (
    <aside className="explain-panel" aria-label="Why this plan">
      <header>
        <p className="eyebrow">Why this plan</p>
        <h3>{explain.summary}</h3>
      </header>

      <div className="explain-grid">
        <section>
          <h4>Decision</h4>
          <ul>
            {explain.why_chosen.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </section>

        <section>
          <h4>Quantile source</h4>
          <p>{explain.quantile_source}</p>
          <p className="muted small">
            p10/p50/p90 = {fmtMin(plan.total_duration_s.p10_s)} /{" "}
            {fmtMin(plan.total_duration_s.p50_s)} /{" "}
            {fmtMin(plan.total_duration_s.p90_s)} · band{" "}
            <strong>{plan.confidence.label}</strong>
          </p>
        </section>

        <section>
          <h4>Walk model</h4>
          <p>
            <code>{explain.walk_method}</code>
          </p>
          <p className="muted small">
            Graph nodes {String(trace.meta?.walk_nodes ?? "—")} · edges{" "}
            {String(trace.meta?.walk_edges ?? "—")} · overlay walk segs {walkSegs}{" "}
            · ride segs {rideSegs}
          </p>
        </section>

        <section>
          <h4>vs alternatives</h4>
          {explain.compared_to_alts.length ? (
            <ul className="mono">
              {explain.compared_to_alts.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          ) : (
            <p className="muted small">No alternatives scored ahead of this plan.</p>
          )}
        </section>
      </div>

      <footer className="explain-hl">
        <span>
          3D highlight:{" "}
          {(explain.highlight?.route_names || []).join(", ") || "walk path"}
        </span>
        <span className="muted small">
          stops {(explain.highlight?.stop_names || []).slice(0, 4).join(" · ") || "—"}
        </span>
      </footer>
    </aside>
  );
}
