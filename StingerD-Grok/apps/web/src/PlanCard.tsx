import type { TripPlan } from "./types";

function fmtMin(s: number): string {
  return `${(s / 60).toFixed(1)} min`;
}

const kindClass: Record<string, string> = {
  walk: "leg walk",
  wait: "leg wait",
  ride: "leg ride",
  transfer_walk: "leg walk",
};

export function PlanCard({
  plan,
  title = "Chosen plan",
  compactExplain = false,
}: {
  plan: TripPlan;
  title?: string;
  compactExplain?: boolean;
}) {
  const { total_duration_s: q, confidence, explain } = plan;
  const bandLeft = ((q.p10_s / q.p90_s) * 100).toFixed(1);
  const bandWidth = (
    ((q.p90_s - q.p10_s) / Math.max(q.p90_s, 1)) *
    100
  ).toFixed(1);
  const p50Mark = ((q.p50_s / q.p90_s) * 100).toFixed(1);

  return (
    <section className="plan-card">
      <header className="plan-head">
        <div>
          <p className="eyebrow">{title}</p>
          <h2>
            {fmtMin(q.p50_s)}{" "}
            <span className="muted">
              (p10 {fmtMin(q.p10_s)} · p90 {fmtMin(q.p90_s)})
            </span>
          </h2>
        </div>
        <div className="metrics">
          <div>
            <span className="metric-label">p_on_time</span>
            <strong>{(plan.p_on_time * 100).toFixed(0)}%</strong>
          </div>
          <div>
            <span className="metric-label">p_catch</span>
            <strong>{(plan.p_catch * 100).toFixed(0)}%</strong>
          </div>
        </div>
      </header>

      {compactExplain && explain && (
        <p className="explain-summary muted">{explain.summary}</p>
      )}

      <div className="confidence">
        <div className="confidence-meta">
          <span className={`badge ${confidence.label}`}>{confidence.label}</span>
          <span>{confidence.note}</span>
        </div>
        <div className="band-track" aria-hidden>
          <div
            className="band-range"
            style={{ left: `${bandLeft}%`, width: `${bandWidth}%` }}
          />
          <div className="band-p50" style={{ left: `${p50Mark}%` }} />
        </div>
        <div className="band-labels">
          <span>p10</span>
          <span>p50</span>
          <span>p90</span>
        </div>
      </div>

      <ol className="legs">
        {plan.legs.map((leg, i) => (
          <li key={`${plan.plan_id}-${i}`} className={kindClass[leg.kind]}>
            <div className="leg-kind">{leg.kind}</div>
            <div className="leg-body">
              <strong>{leg.label}</strong>
              <p>
                {leg.from_name} → {leg.to_name}
              </p>
              <p className="muted">
                {fmtMin(leg.duration_s.p50_s)}
                {leg.explanation ? ` · ${leg.explanation}` : ""}
                {leg.geometry && leg.geometry.length > 1
                  ? ` · ${leg.geometry.length} pts`
                  : ""}
              </p>
            </div>
          </li>
        ))}
      </ol>

      <footer className="plan-foot">
        <p>
          Leave by <strong>{plan.leave_by ?? "—"}</strong> · Arrive ~{" "}
          <strong>{plan.arrive_by_est ?? "—"}</strong>
        </p>
        <ul className="facts">
          {plan.explanation_facts.map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      </footer>
    </section>
  );
}
