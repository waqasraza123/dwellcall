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
  return NextResponse.json({ error: { message: error instanceof BackendError ? error.message : "The service is unavailable. Refresh history before repeating a write.", ...(error instanceof BackendError && error.code ? { code: error.code } : {}) } }, { status: error instanceof BackendError ? error.status : 503, headers: { "Cache-Control": "no-store" } });
}
export async function forwardResponse(response: Response): Promise<NextResponse> {
  if (!response.ok) {
    const code = response.status;
    const messages: Record<string, string> = {
      ELEVENLABS_CARRIER_STOP_REQUIRED: "End the active SIP call in Telnyx, then reconcile or confirm every carrier leg ended. The reservation remains held.",
      ELEVENLABS_LOOKUP_REQUIRED: "Find the existing conversation in ElevenLabs and bind its ID. Never redial an uncertain request.",
      ELEVENLABS_AGENT_INVALID: "Configure the dedicated DwellCall prompt, end_call tool, signed webhook, zero provider retention and bounded duration.",
      ELEVENLABS_TRUNK_INVALID: "Check the imported ElevenLabs SIP number, authorized caller, Telnyx TLS trunk and credentials.",
      ELEVENLABS_READ_UNAVAILABLE: "ElevenLabs could not confirm configuration or status. Check provider access.",
      DEMO_PHONE_VERIFICATION_REQUIRED: "Verify your number with a new text-message code before requesting a demo call.",
      DEMO_SMS_CODE_INVALID: "The code is invalid or expired. Check the text and try again.",
      DEMO_SMS_LIMIT: "The text verification limit was reached. Try later.",
      OUTBOUND_TRANSCRIPT_CONSENT_REQUIRED: "Explicit permission for transcript retention and OpenAI analysis is required.",
      LEAD_REVIEW_OPERATOR_REQUIRED: "An approved operator account is required to review leads.",
      LEAD_REVIEW_KEY_CONFLICT: "This action key was already used. Refresh the lead before acting again.",
      LEAD_REVIEW_CHANGED: "Another action changed this lead. Refresh its review before acting.",
      LEAD_REVIEW_INELIGIBLE: "Current transcript evidence, explicit permission and recipient eligibility are required.",
      LEAD_REVIEW_EVIDENCE_EXPIRY: "Schedule the task before its retained transcript evidence expires.",
      LEAD_REVIEW_DUE_INVALID: "Choose a future due date within 90 days.",
      LEAD_REVIEW_REQUIRED: "Approve the current assessment before scheduling another task.",
      LEAD_TASK_OPEN: "A task is already open. Complete or cancel it first.",
      LEAD_TASK_NOT_OPEN: "This task is no longer open. Refresh its review.",
      BILLING_UNAVAILABLE: "Paid billing is not available yet.",
      BILLING_APPROVAL_REQUIRED: "Owner approval is required before purchasing or managing a subscription.",
      BILLING_MODE_MISMATCH: "This billing account belongs to another Stripe environment. The owner must review configuration.",
      BILLING_CUSTOMER_UNCONFIRMED: "A previous customer creation is unconfirmed. The owner must reconcile it before retrying.",
      BILLING_CUSTOMER_MISSING: "Choose a paid plan first.",
      BILLING_PRICE_MISMATCH: "The configured subscription price needs owner review.",
      BILLING_HISTORY_REVIEW: "Billing history needs owner review before another checkout.",
      STRIPE_UNAVAILABLE: "Stripe is unavailable. Keep your saved checkout request before retrying.",
      STRIPE_RESPONSE_INVALID: "The Stripe response could not be confirmed. Keep your saved checkout request.",
      SUBSCRIPTION_EXISTS: "Manage your existing subscription through the billing portal.",
      CHECKOUT_REQUEST_CONFLICT: "This checkout request does not match. Refresh billing before continuing.",
      CHECKOUT_PENDING: "A checkout is active or its result is unconfirmed. Resume it or refresh billing before choosing another plan.",
      CHECKOUT_UNCONFIRMED: "The checkout result is unconfirmed. The owner must reconcile it before another checkout.",
      CHECKOUT_FINISHED: "This request has finished. Refresh billing, then clear the completed request before starting another.",
      CHECKOUT_IDENTITY_INVALID: "The checkout identity needs owner review.",
      INVALID_CREDENTIALS: "That email and password do not match. Please try again.",
      ACCOUNT_UNAVAILABLE: "Account access is unavailable or those details are already registered. Try signing in.",
      ACCOUNT_AUTH_REQUIRED: "Sign in to continue.",
      AUTH_RATE_LIMITED: "Too many sign-in attempts. Please try again later.",
      MFA_CHALLENGE_REQUIRED: "Sign in again to continue authenticator verification.",
      MFA_CODE_INVALID: "The code is invalid or already used. Wait for a new code, then retry.",
      MFA_LOCKED: "Too many authenticator attempts. Please try again in 15 minutes.",
      MFA_UNAVAILABLE: "Authenticator verification is unavailable. Please try again later.",
      VALIDATION_FAILED: "Check the required fields, telephone format and explicit confirmations.",
      OUTBOUND_DISABLED: "Outbound calling is disabled. The owner must configure and enable it before preflight.",
      OUTBOUND_UNAVAILABLE: "Calling is disabled or its configuration is incomplete. Recover an existing request before calling again.",
      OUTBOUND_DESTINATION_UNSUPPORTED: "This recipient country is not authorized for calling.",
      OUTBOUND_RECIPIENT_NOT_APPROVED: "This recipient is not on the owner's approved calling allowlist.",
      OUTBOUND_RECIPIENT_SUPPRESSED: "This recipient is suppressed or restricted from calling.",
      OUTBOUND_CALL_LOOP: "Caller, recipient and human transfer numbers must differ.",
      OUTBOUND_CALL_LIMIT: "The daily, per-recipient or cooldown limit has been reached.",
      AUDIO_SESSION_LIMIT: "An audio call is active or unresolved, or the shared daily call/spending budget was reached.",
      OUTBOUND_REQUEST_CONFLICT: "This request ID already belongs to another call. Inspect its existing status.",
      OUTBOUND_KEY_MISMATCH: "The request ID and idempotency header must match. Recover the existing request.",
      OUTBOUND_REQUEST_NOT_FOUND: "The saved request is not visible yet. Inspect history and do not submit another call.",
      OUTBOUND_CALL_NOT_FOUND: "This call request could not be found. Do not redial an uncertain request.",
      OUTBOUND_CALL_IDENTITY_INVALID: "The provider call does not match the authorized agent, recipient, caller or request. Investigate before binding.",
      OUTBOUND_SEND_IN_FLIGHT: "The provider send may still be in flight. Wait, then verify every carrier leg ended.",
      RETELL_CREDENTIALS_MISSING: "Configure the dedicated DwellCall Retell API key on the backend.",
      RETELL_PREFLIGHT_UNAVAILABLE: "Retell configuration could not be read. Check API credentials, access and provider availability.",
      RETELL_CONFIGURATION_INVALID: "Retell returned malformed configuration. Inspect the imported number and published agent before calling.",
      TELNYX_TRUNK_MISSING: "Import the authorized Telnyx number and outbound SIP credentials into Retell.",
      TELNYX_TRUNK_INVALID: "Check the imported caller, Telnyx termination hostname, SIP username and TCP/TLS transport.",
      RETELL_DESTINATIONS_INVALID: "Authorize the configured destination countries on the imported Retell number.",
      RETELL_AGENT_INVALID: "Publish the pinned Custom LLM agent with the backend WebSocket URL and bounded call/ringing durations.",
      RETELL_PRIVACY_INVALID: "Disable recording/transcript storage, contact memory and session tools; configure retention and DNC detection.",
      RETELL_WEBHOOK_INVALID: "Configure the signed DwellCall Retell webhook and all three lifecycle events.",
      RETELL_LOOKUP_UNAVAILABLE: "Provider lookup is incomplete or ambiguous. Investigate and bind the existing call without redialing.",
      RETELL_STATUS_INVALID: "The provider returned invalid call identity or lifecycle evidence. The reservation remains held.",
      RETELL_STOP_UNCERTAIN: "Stopping is unconfirmed. Verify all carrier legs before releasing this call.",
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
    let controlledCode: string | undefined;
    try { const payload = await response.json(); if (typeof payload?.error?.code === "string") { controlledCode = payload.error.code; controlledMessage = messages[payload.error.code]; } } catch { /* Non-JSON failures use a safe local message. */ }
    if (controlledMessage) return proxyFailure(new BackendError(code, controlledMessage, controlledCode));
    return proxyFailure(new BackendError(code, code === 401 ? "Operator access has expired or is unavailable. Sign in again." : code === 403 ? "This action is not authorized." : code === 404 ? "This record or feature is unavailable." : code === 409 ? "The action is blocked or was already submitted. Refresh history and inspect the record before trying again." : code === 422 ? "Check the required fields, source permissions and selected values." : code === 429 ? "A limit or another operation is active. Wait before trying again." : "The service could not complete the request. Refresh history before repeating a write."));
  }
  if (response.status === 204) return new NextResponse(null, { status: 204, headers: { "Cache-Control": "no-store" } });
  if (!response.headers.get("content-type")?.includes("application/json")) return proxyFailure(new BackendError(502, "The service returned an unavailable response."));
  return new NextResponse(await response.text(), { status: response.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
}
