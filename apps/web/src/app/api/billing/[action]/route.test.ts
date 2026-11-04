import { beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
vi.mock("@/lib/account-session", () => ({ accountBackend: vi.fn() }));
vi.mock("@/features/billing/server", () => ({ publicCatalog: vi.fn() }));
import { accountBackend } from "@/lib/account-session";
import { publicCatalog } from "@/features/billing/server";
import { GET, POST } from "./route";
const context = (action: string) => ({ params: Promise.resolve({ action }) });
const request = (origin = "https://dwellcall.test") => new NextRequest("https://dwellcall.test/api/billing/checkout", { method: "POST", headers: { Origin: origin, "Content-Type": "application/json" }, body: JSON.stringify({ plan: "pro", request_id: "synthetic-request" }) });
beforeEach(() => vi.resetAllMocks());
it("forwards billing through the account session without an admin credential", async () => {
  vi.mocked(accountBackend).mockResolvedValue(Response.json({ url: "https://checkout.stripe.com/synthetic" }));
  const response = await POST(request(), context("checkout"));
  expect(response.status).toBe(200);
  expect(accountBackend).toHaveBeenCalledWith("billing/checkout", "POST", JSON.stringify({ plan: "pro", request_id: "synthetic-request" }));
});
it("rejects cross-origin checkout and invalid returned URLs", async () => {
  expect((await POST(request("https://foreign.test"), context("checkout"))).status).toBe(403);
  expect(accountBackend).not.toHaveBeenCalled();
  vi.mocked(accountBackend).mockResolvedValue(Response.json({ url: "https://foreign.test" }));
  expect((await POST(request(), context("checkout"))).status).toBe(502);
});
it("keeps pricing public and the remaining backend paths private", async () => {
  vi.mocked(publicCatalog).mockResolvedValue({ plans: [], checkout_enabled: false });
  expect((await GET(new NextRequest("https://dwellcall.test/api/billing/plans"), context("plans"))).status).toBe(200);
  expect(accountBackend).not.toHaveBeenCalled();
  expect((await GET(new NextRequest("https://dwellcall.test/api/billing/checkout"), context("checkout"))).status).toBe(404);
  expect((await POST(request(), context("admin"))).status).toBe(404);
});
