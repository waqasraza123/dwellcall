import { CallApiError } from "./api";
import { isLeadReview, type LeadReview, type ReviewMutation } from "./review-contracts";

export async function leadReviewRequest(path: string, body?: ReviewMutation, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(`/api/call-leads/${path}`, {
    method: body ? "POST" : "GET", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(25000)]) : AbortSignal.timeout(25000),
  });
  const data: unknown = await response.json();
  if (!response.ok) {
    const error = data && typeof data === "object" && "error" in data && data.error && typeof data.error === "object" ? data.error as Record<string, unknown> : {};
    throw new CallApiError(typeof error.code === "string" ? error.code : "LEAD_REVIEW_UNCONFIRMED", typeof error.message === "string" ? error.message : "The action is unconfirmed. Recover your saved action before submitting another.");
  }
  return data;
}
export async function loadLeadReview(callId: string, signal?: AbortSignal): Promise<LeadReview> {
  const value = await leadReviewRequest(callId, undefined, signal);
  if (!isLeadReview(value) || value.call_id !== callId) throw new Error("The review identity could not be confirmed.");
  return value;
}
export async function applyLeadReview(callId: string, mutation: ReviewMutation): Promise<LeadReview> {
  const value = await leadReviewRequest(`${callId}/actions`, mutation);
  if (!isLeadReview(value) || value.call_id !== callId) throw new Error("The action outcome is unconfirmed. Retry the saved action.");
  return value;
}
