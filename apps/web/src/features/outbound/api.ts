import { isOutboundCall, type OutboundCall, type Scenario, UUID_PATTERN } from "./contracts";

export const STORAGE_KEY = "dwellcall-outbound-request-v1";
export class CallApiError extends Error {
  constructor(readonly code: string, message: string) { super(message); }
}
export async function callRequest(path: string, method = "GET", body?: unknown, key?: string, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(`/api/ops/outbound/${path}`, {
    method, cache: "no-store", signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(50_000)]) : AbortSignal.timeout(50_000),
    headers: { "Content-Type": "application/json", ...(method === "GET" ? {} : { "Idempotency-Key": key ?? crypto.randomUUID() }) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data: unknown = await response.json();
  if (!response.ok) {
    const error = data && typeof data === "object" && "error" in data && data.error && typeof data.error === "object" ? data.error as Record<string, unknown> : {};
    throw new CallApiError(typeof error.code === "string" ? error.code : "OUTBOUND_UNCONFIRMED", typeof error.message === "string" ? error.message : "The outcome is unconfirmed. Recover this request before calling again.");
  }
  return data;
}
export function pendingRequest(storage: Pick<Storage, "getItem">): string | null {
  const value = storage.getItem(STORAGE_KEY);
  if (value !== null && !UUID_PATTERN.test(value)) throw new Error("The saved call request is invalid. Inspect call history before clearing it.");
  return value;
}
export async function requestCall(requestId: string, phone: string, scenario: Scenario): Promise<OutboundCall> {
  const result = await callRequest("calls", "POST", {
    request_id: requestId, phone_number: phone, scenario, consent: true,
    consent_version: "dwellcall-ai-call-v1", recipient_consent_confirmed: true, do_not_call_checked: true,
  }, requestId);
  if (!isOutboundCall(result) || result.request_id !== requestId) throw new Error("The provider receipt could not be confirmed. Recover the saved request.");
  return result;
}
export async function recoverCall(requestId: string, signal?: AbortSignal): Promise<OutboundCall> {
  const result = await callRequest(`requests/${requestId}`, "GET", undefined, undefined, signal);
  if (!isOutboundCall(result) || result.request_id !== requestId) throw new Error("The recovered call identity is invalid. Inspect call history.");
  return result;
}
