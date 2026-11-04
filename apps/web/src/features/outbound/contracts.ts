export const scenarios = { renting: "Renting", buying: "Buying", luxury: "Luxury" } as const;
export type Scenario = keyof typeof scenarios;
export const statuses = ["reserved", "dialing", "ringing", "in_progress", "completed", "rejected", "unanswered", "failed", "unknown", "transferred", "transfer_unconfirmed"] as const;
export const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export type OutboundCall = {
  id: string; request_id: string; provider_call_id: string | null; status: typeof statuses[number];
  transfer_status: "not_requested" | "requested" | "refer_accepted" | "failed" | "unconfirmed";
  scenario: string; created_at: string; started_at: string | null; finalized_at: string | null;
  duration_seconds: number | null; terminal: boolean; mock: boolean; message: string; error_code: string | null;
};
export type Availability = {
  available: boolean; mock: boolean; transfer_available: boolean; max_duration_seconds: number;
  daily_limit: number; countries: string[]; calls_paused: boolean; transfers_paused: boolean;
};
export function isOutboundCall(value: unknown): value is OutboundCall {
  if (typeof value !== "object" || value === null) return false;
  const call = value as Record<string, unknown>;
  const timestamp = (v: unknown) => typeof v === "string" && Number.isFinite(Date.parse(v));
  return typeof call.id === "string" && UUID_PATTERN.test(call.id) && typeof call.request_id === "string" && UUID_PATTERN.test(call.request_id)
    && (call.provider_call_id === null || (typeof call.provider_call_id === "string" && /^[A-Za-z0-9_-]{1,200}$/.test(call.provider_call_id)))
    && typeof call.status === "string" && statuses.some(s => s === call.status)
    && typeof call.transfer_status === "string" && ["not_requested", "requested", "refer_accepted", "failed", "unconfirmed"].includes(call.transfer_status)
    && typeof call.scenario === "string" && Object.hasOwn(scenarios, call.scenario)
    && timestamp(call.created_at) && (call.started_at === null || timestamp(call.started_at)) && (call.finalized_at === null || timestamp(call.finalized_at))
    && (call.duration_seconds === null || (Number.isSafeInteger(call.duration_seconds) && Number(call.duration_seconds) >= 0))
    && typeof call.terminal === "boolean" && call.terminal === (call.finalized_at !== null)
    && (!call.terminal || ["completed", "failed", "unanswered", "rejected"].includes(call.status))
    && typeof call.mock === "boolean" && typeof call.message === "string" && call.message.length > 0 && call.message.length <= 1000
    && (call.error_code === null || typeof call.error_code === "string");
}
export function isAvailability(value: unknown): value is Availability {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return ["available", "mock", "transfer_available", "calls_paused", "transfers_paused"].every(k => typeof v[k] === "boolean")
    && Number.isSafeInteger(v.max_duration_seconds) && Number(v.max_duration_seconds) <= 180 && Number(v.max_duration_seconds) > 0
    && Number.isSafeInteger(v.daily_limit) && Array.isArray(v.countries) && v.countries.every(c => typeof c === "string");
}
