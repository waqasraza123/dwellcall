import { afterEach, describe, expect, it, vi } from "vitest";
import { callRequest, pendingRequest, recoverCall, requestCall, unresolvedCall, STORAGE_KEY } from "./api";
import { isOutboundCall, type OutboundCall } from "./contracts";

const id = "11111111-1111-4111-8111-111111111111";
const call = { id, request_id: id, provider_call_id: "call_mock_synthetic", status: "dialing", transfer_status: "not_requested", scenario: "renting", created_at: "2026-11-04T12:00:00Z", started_at: null, finalized_at: null, duration_seconds: null, terminal: false, mock: true, message: "Simulated request", error_code: null };
afterEach(() => vi.unstubAllGlobals());
describe("outbound request and refresh recovery", () => {
  it("uses one stable request ID for body and authenticated bridge idempotency", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json(call)); vi.stubGlobal("fetch", fetcher);
    expect(await requestCall(id, "+12025550124", "renting")).toEqual(call);
    const [path, init] = fetcher.mock.calls[0];
    expect(path).toBe("/api/ops/outbound/calls"); expect(init.headers["Idempotency-Key"]).toBe(id);
    const body = JSON.parse(init.body); expect(body.request_id).toBe(id); expect(body.recipient_consent_confirmed).toBe(true);
    expect(body.consent_version).toBe("dwellcall-ai-call-v2"); expect(body.do_not_call_checked).toBe(true);
  });
  it("persists and recovers only a request ID and never initiates during recovery", async () => {
    expect(pendingRequest({ getItem: key => key === STORAGE_KEY ? id : null })).toBe(id);
    const fetcher = vi.fn().mockResolvedValue(Response.json(call)); vi.stubGlobal("fetch", fetcher);
    expect(await recoverCall(id)).toEqual(call);
    expect(fetcher).toHaveBeenCalledOnce(); expect(fetcher.mock.calls[0][0]).toBe(`/api/ops/outbound/requests/${id}`);
    expect(fetcher.mock.calls[0][1].method).toBe("GET");
  });
  it("never creates or redials when recovery is missing or unavailable", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ error: { code: "OUTBOUND_REQUEST_NOT_FOUND", message: "Investigate before redialing" } }, { status: 404 })); vi.stubGlobal("fetch", fetcher);
    await expect(recoverCall(id)).rejects.toThrow("Investigate before redialing");
    expect(fetcher).toHaveBeenCalledOnce(); expect(fetcher.mock.calls[0][1].method).toBe("GET");
  });
  it("recovers an unresolved history request when this tab has no saved ID", () => {
    const ongoing = call as OutboundCall;
    const final: OutboundCall = { ...ongoing, status: "completed", finalized_at: "2026-11-04T12:01:00Z", terminal: true };
    expect(unresolvedCall([final, ongoing])).toBe(ongoing);
    expect(unresolvedCall([final])).toBeNull();
    expect(unresolvedCall([{ ...ongoing, status: "unknown" }])?.request_id).toBe(id);
  });
  it("retains uncertainty after a lost creation receipt without retrying", async () => {
    const fetcher = vi.fn().mockRejectedValue(new TypeError("Connection lost")); vi.stubGlobal("fetch", fetcher);
    await expect(requestCall(id, "+12025550124", "renting")).rejects.toThrow("Connection lost");
    expect(fetcher).toHaveBeenCalledOnce();
  });
  it("rejects identity mismatches and inconsistent final or transfer outcomes", async () => {
    expect(isOutboundCall({ ...call, status: "transferred", terminal: true })).toBe(false);
    expect(isOutboundCall({ ...call, status: "unknown", finalized_at: "2026-11-04T12:01:00Z", terminal: true })).toBe(false);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ ...call, request_id: "22222222-2222-4222-8222-222222222222" })));
    await expect(recoverCall(id)).rejects.toThrow("identity");
    expect(() => pendingRequest({ getItem: () => "corrupt" })).toThrow("invalid");
  });
  it("preserves actionable provider errors without interpreting them as answers", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ error: { code: "RETELL_AGENT_INVALID", message: "Publish the pinned agent" } }, { status: 503 })));
    await expect(callRequest("preflight", "POST", {})).rejects.toThrow("Publish the pinned agent");
    expect(isOutboundCall({ ...call, terminal: true })).toBe(false);
  });
});
