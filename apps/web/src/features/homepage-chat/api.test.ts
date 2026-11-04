import { afterEach, describe, expect, it, vi } from "vitest";
import { conversationRequest, conversationStatus } from "./api";
import { isConversation, isGrant } from "./contracts";

const id = "11111111-1111-4111-8111-111111111111";
const conversation = { id, mode: "text", scenario: "renting", status: "active", mock: true, expires_at: "2099-01-01T00:00:00Z", provider_call_id: null, turn_count: 0, turn_in_flight: false };
afterEach(() => vi.unstubAllGlobals());
describe("hero conversation boundaries", () => {
  it("recovers only the saved request without generating another conversation", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json(conversation)); vi.stubGlobal("fetch", fetcher);
    expect(await conversationStatus(id)).toEqual(conversation);
    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher.mock.calls[0][0]).toBe(`/api/homepage-chat/sessions/${id}`);
    expect(fetcher.mock.calls[0][1].method).toBe("GET");
  });
  it("never retries a lost creation or text reply automatically", async () => {
    const fetcher = vi.fn().mockRejectedValue(new TypeError("Lost connection")); vi.stubGlobal("fetch", fetcher);
    await expect(conversationRequest(`sessions/${id}/turn`, "POST", { transcript: [], state_token: "synthetic" })).rejects.toThrow("Lost connection");
    expect(fetcher).toHaveBeenCalledOnce();
  });
  it("rejects a recovered session with another identity", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ ...conversation, id: "22222222-2222-4222-8222-222222222222" })));
    await expect(conversationStatus(id)).rejects.toThrow("does not match");
    expect(isConversation({ ...conversation, status: "connected" })).toBe(false);
  });
  it("requires the provider's declared transport and unexpired grant", () => {
    const grant = { call_id: "call_synthetic", access_token: "synthetic-grant", transport: "gateway", ice_servers: [{ urls: "stun:stun.example.test" }], expires_at: Date.now() + 60_000 };
    expect(isGrant(grant)).toBe(true);
    expect(isGrant({ ...grant, transport: "livekit" })).toBe(false);
    expect(isGrant({ ...grant, expires_at: 1 })).toBe(false);
    expect(isGrant({ ...grant, ice_servers: [{ urls: 123 }] })).toBe(false);
  });
});
