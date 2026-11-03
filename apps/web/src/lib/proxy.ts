import { NextRequest, NextResponse } from "next/server";
import { BackendError } from "./backend";

export function requireSameOrigin(request: NextRequest): void {
  if (request.headers.get("origin") !== request.nextUrl.origin || request.headers.get("sec-fetch-site") === "cross-site") throw new BackendError(403, "Use the form on this website.");
}
export async function requestBody(request: NextRequest, limit = 1_114_112): Promise<string> {
  if (!request.headers.get("content-type")?.startsWith("application/json")) throw new BackendError(415, "Send this form as JSON.");
  const stream = request.body?.getReader();
  if (!stream) return "{}";
  const chunks: Uint8Array[] = []; let length = 0;
  try {
    while (true) { const result = await stream.read(); if (result.done) break; length += result.value.byteLength; if (length > limit) { await stream.cancel(); throw new BackendError(413, "Choose a smaller file."); } chunks.push(result.value); }
    const bytes = new Uint8Array(length); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    const body = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    JSON.parse(body); return body;
  } catch (error) { if (error instanceof BackendError) throw error; throw new BackendError(400, "Check the form and try again."); }
}
export function proxyFailure(error: unknown): NextResponse {
  return NextResponse.json({ error: { message: error instanceof BackendError ? error.message : "The service is unavailable. Refresh history before repeating a write." } }, { status: error instanceof BackendError ? error.status : 503, headers: { "Cache-Control": "no-store" } });
}
export async function forwardResponse(response: Response): Promise<NextResponse> {
  if (!response.ok) {
    const code = response.status;
    const messages: Record<string, string> = {
      CRM_PROVIDER_NOT_SELECTED: "This CRM is not selected on the backend. Ask the owner to configure CRM_PROVIDER before using its workflows.",
      HUBSPOT_PHONE_REGION_NOT_CONFIGURED: "The owner must configure this phone’s country calling code before HubSpot matching. No contact was created.",
      HUBSPOT_CONTACT_COUNTRY_AMBIGUOUS: "A matching local phone lacks reliable country evidence. Inspect the existing HubSpot contact before binding or creating records.",
      HUBSPOT_CONTACT_REVIEW_REQUIRED: "A matching HubSpot contact needs an explicit reviewed binding. Use Review existing contact after inspecting its identity.",
      HUBSPOT_COMPANY_REVIEW_REQUIRED: "An existing company has the same brokerage name. The owner must add an explicit HubSpot company mapping before synchronization.",
      HUBSPOT_SCHEMA_CREATION_DISABLED: "The backend owner has not enabled HubSpot custom property creation.",
      HUBSPOT_PORTAL_MISMATCH: "The configured token does not belong to the expected HubSpot account. No writes are authorized.",
      HUBSPOT_API_DISABLED: "HubSpot API access is disabled by backend configuration.",
      HUBSPOT_SETUP_REQUIRED: "Validate the HubSpot connection and all required properties before synchronization.",
      HUBSPOT_SYNC_DISABLED: "HubSpot synchronization is disabled by the owner-controlled backend gates.",
      HUBSPOT_REJECTED_401: "HubSpot rejected the configured credential. The owner must correct or rotate it before validation.",
      HUBSPOT_REJECTED_403: "HubSpot denied this operation. Check the token scopes and account permissions.",
      HUBSPOT_OUTCOME_UNRESOLVED: "A previous HubSpot write has an uncertain outcome. Reconcile it before queuing another export.",
      HUBSPOT_RETRY_UNSAFE: "This HubSpot operation cannot be retried safely. Inspect its audit and reconcile uncertain writes first.",
      HUBSPOT_BACKOFF_ACTIVE: "HubSpot backoff is active. Wait until the recorded next attempt time.",

      ACTION_ALREADY_SUBMITTED: "This action was already submitted. Refresh its history before allowing another attempt.",
      JOB_RUNNING: "This discovery job is already running. Refresh discovery history.",
      JOB_CHANGED: "This job changed since you opened it. Refresh before saving.",
      SOURCE_SCOPE_HAS_DATA: "This source already has stored records. Revoke display rights if needed; the owner must purge affected records before changing source scope.",
      SOURCE_PERMISSION_REQUIRED: "The source needs explicit retrieval and storage permission before it can run.",
      INGESTION_DAILY_LIMIT: "The daily discovery limit has been reached. Try again after the limit resets.",
      GHL_SYNC_DISABLED: "Live synchronization is disabled. The owner must enable the existing backend approval gates.",
      GHL_SETUP_REQUIRED: "Validate the GoHighLevel connection and all required field mappings first.",
      GHL_API_DISABLED: "GoHighLevel API access is disabled by the backend configuration.",
      GHL_RETRY_UNSAFE: "This failure cannot be safely retried. Inspect the audit and reconcile uncertain outcomes first.",
      GHL_OUTCOME_UNRESOLVED: "A previous write has an uncertain outcome. Reconcile that job before queuing another.",
      GHL_SETUP_OR_BACKOFF: "Complete connection setup and wait for the recorded provider backoff before trying again.",
      GHL_BACKOFF_ACTIVE: "Provider backoff is active. Wait until the next recorded attempt time.",
      REVIEW_ALREADY_RESOLVED: "This review already has an immutable decision. Refresh the review record.",
      REVIEW_CANDIDATE_INVALID: "Approval requires one of the retained proposed candidates.",
      AGENT_SUPPRESSED: "Suppression blocks this identity. Review approval cannot override it.",
    };
    let controlledMessage: string | undefined;
    try { const payload = await response.json(); if (typeof payload?.error?.code === "string") controlledMessage = messages[payload.error.code]; } catch { /* Non-JSON failures use a safe local message. */ }
    if (controlledMessage) return proxyFailure(new BackendError(code, controlledMessage));
    return proxyFailure(new BackendError(code, code === 401 ? "Operator access has expired or is unavailable. Sign in again." : code === 403 ? "This action is not authorized." : code === 404 ? "This record or feature is unavailable." : code === 409 ? "The action is blocked or was already submitted. Refresh history and inspect the record before trying again." : code === 422 ? "Check the required fields, source permissions and selected values." : code === 429 ? "A limit or another operation is active. Wait before trying again." : "The service could not complete the request. Refresh history before repeating a write."));
  }
  if (response.status === 204) return new NextResponse(null, { status: 204, headers: { "Cache-Control": "no-store" } });
  if (!response.headers.get("content-type")?.includes("application/json")) return proxyFailure(new BackendError(502, "The service returned an unavailable response."));
  return new NextResponse(await response.text(), { status: response.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
}
