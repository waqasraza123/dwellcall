import { afterEach, describe, expect, it, vi } from "vitest";
import { applyLeadReview } from "./review-api";
import type { ReviewMutation } from "./review-contracts";
const id = "11111111-1111-4111-8111-111111111111";
const request: ReviewMutation = { request_id: id, action: "approve", expected_version: 0, evidence_reviewed: true, due_at: null, outcome: null };
const review = { call_id: id, status: "approved", version: 1, eligible: true, blockers: [], reviewed_at: "2026-11-08T12:00:00Z", task_status: "none", task_actionable: false, due_at: null, completed_at: null, outcome: null, recent_events: [] };
afterEach(() => vi.unstubAllGlobals());
describe("recoverable lead actions", () => {
  it("reuses the saved request after an interrupted response", async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new Error("interrupted")).mockResolvedValueOnce(Response.json(review));
    vi.stubGlobal("fetch", fetcher);
    await expect(applyLeadReview(id, request)).rejects.toThrow("interrupted");
    expect((await applyLeadReview(id, request)).version).toBe(1);
    expect(fetcher.mock.calls[0][1].body).toBe(fetcher.mock.calls[1][1].body);
  });
  it("rejects a response belonging to another call", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ ...review, call_id: "22222222-2222-4222-8222-222222222222" })));
    await expect(applyLeadReview(id, request)).rejects.toThrow("unconfirmed");
  });
});
