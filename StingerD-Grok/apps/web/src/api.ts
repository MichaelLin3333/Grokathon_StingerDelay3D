import type { PlanRequest, TripTrace } from "./types";

/**
 * Prefer same-origin `/api` (Vite proxy → FastAPI :8000).
 * Override with VITE_API_BASE only when calling the API without the web server.
 */
const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

export async function fetchHealth(): Promise<{
  status: string;
  routes_loaded: number;
}> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error(`health ${res.status}`);
  return res.json();
}

export async function planTrip(body: PlanRequest): Promise<TripTrace> {
  const res = await fetch(`${API_BASE}/trips/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`plan ${res.status}: ${text}`);
  }
  return res.json();
}

export { API_BASE };
