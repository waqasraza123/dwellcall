import { isConversation, type Conversation } from "./contracts";

export class ConversationApiError extends Error {
  constructor(readonly code: string, readonly status: number, message: string) { super(message); }
}

export async function conversationRequest(path = "", method = "GET", body?: unknown, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(`/api/homepage-chat${path ? `/${path}` : ""}`, {
    method, headers: { "Content-Type": "application/json" }, cache: "no-store",
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(45_000)]) : AbortSignal.timeout(45_000),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data: unknown = await response.json();
  if (!response.ok) {
    const error = data && typeof data === "object" && "error" in data && data.error && typeof data.error === "object" ? data.error as Record<string, unknown> : {};
    throw new ConversationApiError(typeof error.code === "string" ? error.code : "", response.status, typeof error.message === "string" ? error.message : "The connection was interrupted. Check the saved conversation before continuing.");
  }
  return data;
}
export async function conversationStatus(id: string, signal?: AbortSignal): Promise<Conversation> {
  const data = await conversationRequest(`sessions/${id}`, "GET", undefined, signal);
  if (!isConversation(data) || data.id !== id) throw new Error("The recovered conversation does not match this request.");
  return data;
}
