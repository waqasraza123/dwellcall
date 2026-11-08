import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
vi.mock("@/lib/operator-session", () => ({ authenticated: vi.fn() }));
vi.mock("@/lib/backend", async () => { const original = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend"); return { ...original, operatorBackend: vi.fn() }; });
import { authenticated } from "@/lib/operator-session";
import { operatorBackend } from "@/lib/backend";
import { GET, POST } from "./route";
const context = (path = "") => ({ params: Promise.resolve({ path: path ? path.split("/") : [] }) });
beforeEach(() => { vi.stubEnv("DWELLCALL_PLATFORM_EXTENSIONS_ENABLED", "true"); vi.mocked(authenticated).mockResolvedValue(true); });
afterEach(() => { vi.resetAllMocks(); vi.unstubAllEnvs(); });
describe("homepage conversation bridge adapted from HVACLine", () => {
  it("shows a sign-in state without contacting providers for an anonymous visitor", async () => {
    vi.mocked(authenticated).mockResolvedValue(false);
    const response = await GET(new NextRequest("https://dwellcall.test/api/homepage-chat"), context());
    expect((await response.json()).authenticated).toBe(false);
    expect(operatorBackend).not.toHaveBeenCalled();
  });
  it("rejects unauthenticated starts and cross-site messages", async () => {
    vi.mocked(authenticated).mockResolvedValue(false);
    const request = (origin: string) => new NextRequest("https://dwellcall.test/api/homepage-chat/sessions", { method: "POST", headers: { origin, "Content-Type": "application/json" }, body: "{}" });
    expect((await POST(request("https://dwellcall.test"), context("sessions"))).status).toBe(401);
    expect((await POST(request("https://other.test"), context("sessions"))).status).toBe(403);
    expect(operatorBackend).not.toHaveBeenCalled();
  });
  it("forwards only allowlisted conversation routes with the server-owned browser identity", async () => {
    vi.mocked(operatorBackend).mockResolvedValue(Response.json({ id: "synthetic" }));
    const owner = "v".repeat(43);
    const response = await POST(new NextRequest("https://dwellcall.test/api/homepage-chat/sessions", { method: "POST", headers: { origin: "https://dwellcall.test", "Content-Type": "application/json", Cookie: `dwellcall-browser=${owner}` }, body: "{}" }), context("sessions"));
    expect(response.status).toBe(200);
    expect(operatorBackend).toHaveBeenCalledWith("browser-conversations/sessions", "POST", "{}", undefined, owner);
    expect((await GET(new NextRequest("https://dwellcall.test/api/homepage-chat/outbound/calls"), context("outbound/calls"))).status).toBe(404);
  });
});
it("does not contact the browser conversation backend in the focused product", async () => {
  vi.stubEnv("DWELLCALL_PLATFORM_EXTENSIONS_ENABLED", "false");
  expect((await GET(new NextRequest("https://dwellcall.test/api/homepage-chat"), context())).status).toBe(404);
  expect(operatorBackend).not.toHaveBeenCalled();
});
