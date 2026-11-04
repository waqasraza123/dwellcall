export type Mode = "voice" | "text";
export type Scenario = "renting" | "buying" | "luxury";
export type Turn = { role: "agent" | "user"; content: string };
export type Availability = { authenticated: boolean; voice: boolean; text: boolean; mock: boolean; max_seconds: number };
export type Conversation = {
  id: string; mode: Mode; scenario: Scenario; status: "active" | "unknown" | "ended";
  mock: boolean; expires_at: string; provider_call_id: string | null; turn_count: number; turn_in_flight: boolean;
};
export type VoiceGrant = { call_id: string; access_token: string; transport: "gateway"; ice_servers: RTCIceServer[]; expires_at: number };
export type Started = { conversation: Conversation; greeting: string; state_token: string | null; grant: VoiceGrant | null };
export const REQUEST_KEY = "dwellcall-browser-conversation-v1";
export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export function isConversation(value: unknown): value is Conversation {
  if (!value || typeof value !== "object") return false;
  const data = value as Record<string, unknown>;
  return typeof data.id === "string" && UUID.test(data.id) && ["voice", "text"].includes(String(data.mode))
    && ["renting", "buying", "luxury"].includes(String(data.scenario)) && ["active", "unknown", "ended"].includes(String(data.status))
    && typeof data.mock === "boolean" && typeof data.expires_at === "string" && Number.isFinite(Date.parse(data.expires_at))
    && (data.provider_call_id === null || typeof data.provider_call_id === "string") && Number.isSafeInteger(data.turn_count) && Number(data.turn_count) >= 0 && typeof data.turn_in_flight === "boolean";
}
export function isAvailability(value: unknown): value is Availability {
  if (!value || typeof value !== "object") return false;
  const data = value as Record<string, unknown>;
  return ["authenticated", "voice", "text", "mock"].every(key => typeof data[key] === "boolean") && Number.isSafeInteger(data.max_seconds) && Number(data.max_seconds) > 0 && Number(data.max_seconds) <= 180;
}
export function isGrant(value: unknown): value is VoiceGrant {
  if (!value || typeof value !== "object") return false;
  const grant = value as Record<string, unknown>;
  return typeof grant.access_token === "string" && grant.access_token.length > 0 && typeof grant.call_id === "string" && grant.transport === "gateway" && Number.isSafeInteger(grant.expires_at) && Number(grant.expires_at) > Date.now()
    && Array.isArray(grant.ice_servers) && grant.ice_servers.every(server => server && typeof server === "object" && (typeof server.urls === "string" || Array.isArray(server.urls) && server.urls.every((url: unknown) => typeof url === "string")) && (server.username === undefined || typeof server.username === "string") && (server.credential === undefined || typeof server.credential === "string"));
}
