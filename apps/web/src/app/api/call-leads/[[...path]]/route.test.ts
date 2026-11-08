import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
vi.mock("@/lib/account-session", () => ({ currentAccount: vi.fn(), accountBackend: vi.fn() }));
import { currentAccount, accountBackend } from "@/lib/account-session";
import { GET, POST } from "./route";
const id = "11111111-1111-4111-8111-111111111111";
const context = (path: string[]) => ({ params: Promise.resolve({ path }) });
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(currentAccount).mockResolvedValue({ status: "authenticated", user: { id, full_name: "Synthetic", email: "synthetic@example.test", operator_access: true } });
});
describe("account-authenticated lead reviews", () => {
  it("rejects anonymous or unapproved accounts before forwarding", async () => {
    vi.mocked(currentAccount).mockResolvedValue({ status: "anonymous" });
    expect((await GET(new NextRequest("https://dwellcall.test/api/call-leads/tasks"), context(["tasks"]))).status).toBe(401);
    vi.mocked(currentAccount).mockResolvedValue({ status: "authenticated", user: { id, full_name: "Synthetic", email: "synthetic@example.test", operator_access: false } });
    expect((await GET(new NextRequest("https://dwellcall.test/api/call-leads/tasks"), context(["tasks"]))).status).toBe(401);
    expect(accountBackend).not.toHaveBeenCalled();
  });
  it("blocks cross-site mutations and arbitrary endpoints", async () => {
    const response = await POST(new NextRequest(`https://dwellcall.test/api/call-leads/${id}/actions`, { method: "POST", headers: { origin: "https://other.test", "Content-Type": "application/json" }, body: JSON.stringify({ request_id: id }) }), context([id, "actions"]));
    expect(response.status).toBe(403);
    expect((await GET(new NextRequest("https://dwellcall.test/api/call-leads/calls"), context(["calls"]))).status).toBe(404);
    expect(accountBackend).not.toHaveBeenCalled();
  });
  it("forwards the stable action key through the account session bridge", async () => {
    vi.mocked(accountBackend).mockResolvedValue(Response.json({ version: 1 }));
    const body = JSON.stringify({ request_id: id, expected_version: 0, action: "approve", evidence_reviewed: true });
    const response = await POST(new NextRequest(`https://dwellcall.test/api/call-leads/${id}/actions`, { method: "POST", headers: { origin: "https://dwellcall.test", "Content-Type": "application/json" }, body }), context([id, "actions"]));
    expect(response.status).toBe(200);
    expect(accountBackend).toHaveBeenCalledWith(`call-leads/${id}/actions`, "POST", body);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
  });
  it("allows only supported task filters", async () => {
    expect((await GET(new NextRequest("https://dwellcall.test/api/call-leads/tasks?status=../calls"), context(["tasks"]))).status).toBe(422);
    expect(accountBackend).not.toHaveBeenCalled();
  });
});
