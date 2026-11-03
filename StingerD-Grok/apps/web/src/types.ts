export type LegKind = "walk" | "wait" | "ride" | "transfer_walk";

export interface Quantiles {
  p10_s: number;
  p50_s: number;
  p90_s: number;
}

export interface TripLeg {
  kind: LegKind;
  label: string;
  duration_s: Quantiles;
  from_name?: string | null;
  to_name?: string | null;
  route_id?: string | null;
  route_name?: string | null;
  explanation?: string | null;
  geometry?: number[][];
}

export interface ConfidenceBand {
  horizon_s: number;
  width_s: number;
  label: "near" | "mid" | "far";
  note: string;
}

export interface PlanPolyline {
  kind: string;
  label?: string;
  coords: number[][];
  color?: string | null;
  route_id?: string | null;
  route_name?: string | null;
}

export interface PlanExplanation {
  summary: string;
  why_chosen: string[];
  quantile_source: string;
  walk_method: string;
  compared_to_alts: string[];
  highlight: {
    route_ids?: string[];
    route_names?: string[];
    stop_names?: string[];
    stop_ids?: Array<string | number>;
    polylines?: PlanPolyline[];
  };
}

export interface TripPlan {
  plan_id: string;
  total_duration_s: Quantiles;
  p_on_time: number;
  p_catch: number;
  leave_by?: string | null;
  arrive_by_est?: string | null;
  legs: TripLeg[];
  confidence: ConfidenceBand;
  explanation_facts: string[];
  explain?: PlanExplanation | null;
}

export interface TripTrace {
  request_id: string;
  mode: "live" | "replay" | "heuristic";
  chosen: TripPlan;
  alternatives: TripPlan[];
  allowed_numbers: number[];
  meta: Record<string, unknown>;
  explain?: PlanExplanation | null;
}

export interface PlanRequest {
  origin: { lat: number; lon: number };
  destination: { lat: number; lon: number };
  depart_at?: string;
  arrive_by?: string;
  prefs?: {
    avoid_stairs?: boolean;
    walk_speed_mps?: number;
    on_time_target?: number;
  };
}
