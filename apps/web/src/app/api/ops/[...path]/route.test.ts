import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
vi.mock("@/lib/operator-session", () => ({ authenticated: vi.fn() }));
vi.mock("@/lib/backend", async () => { const original = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend"); return { ...original, operatorBackend: vi.fn() }; });
import { authenticated } from "@/lib/operator-session";
import { operatorBackend } from "@/lib/backend";
import { GET, POST } from "./route";
const context = (path: string) => ({ params: Promise.resolve({ path: path.split("/") }) });
beforeEach(() => { vi.mocked(authenticated).mockResolvedValue(true); });
afterEach(() => vi.resetAllMocks());
describe("authenticated operational bridge", () => {
  it("requires auth before reading data or calling the backend", async () => {
    vi.mocked(authenticated).mockResolvedValue(false);
    const response = await GET(new NextRequest("https://dwellcall.test/api/ops/intelligence/listings"), context("intelligence/listings"));
    expect(response.status).toBe(401); expect(operatorBackend).not.toHaveBeenCalled();
  });
  it("blocks cross-site writes before forwarding", async () => {
    const response = await POST(new NextRequest("https://dwellcall.test/api/ops/crm/ghl/jobs/process", { method: "POST", headers: { origin: "https://other.test", "Content-Type": "application/json", "Idempotency-Key": "11111111-1111-4111-8111-111111111111" }, body: "{}" }), context("crm/ghl/jobs/process"));
    expect(response.status).toBe(403); expect(operatorBackend).not.toHaveBeenCalled();
  });
  it("preserves filters and pagination without allowing write endpoints as GET", async () => {
    vi.mocked(operatorBackend).mockResolvedValue(Response.json({ items: [], total: 0 }));
    const response = await GET(new NextRequest("https://dwellcall.test/api/ops/intelligence/listings?page=2&q=Austin"), context("intelligence/listings"));
    expect(response.status).toBe(200);
    expect(operatorBackend).toHaveBeenCalledWith("intelligence/listings?page=2&q=Austin", "GET", undefined, undefined);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    const denied = await GET(new NextRequest("https://dwellcall.test/api/ops/crm/ghl/jobs/process"), context("crm/ghl/jobs/process"));
    expect(denied.status).toBe(404);
  });
  it("preserves safe outbound error codes for correction without exposing backend details", async () => {
    vi.mocked(operatorBackend).mockResolvedValue(Response.json({ error: { code: "OUTBOUND_RECIPIENT_SUPPRESSED", message: "private provider content" } }, { status: 403 }));
    const response = await POST(new NextRequest("https://dwellcall.test/api/ops/outbound/calls", { method: "POST", headers: { origin: "https://dwellcall.test", "Content-Type": "application/json", "Idempotency-Key": "11111111-1111-4111-8111-111111111111" }, body: "{}" }), context("outbound/calls"));
    expect(response.status).toBe(403);
    const result = await response.json();
    expect(result.error.code).toBe("OUTBOUND_RECIPIENT_SUPPRESSED");
    expect(result.error.message).not.toContain("private provider");
  });
  it("rejects cross-site outbound creation and unauthenticated recovery", async () => {
    const response = await POST(new NextRequest("https://dwellcall.test/api/ops/outbound/calls", { method: "POST", headers: { origin: "https://other.test", "Content-Type": "application/json", "Idempotency-Key": "11111111-1111-4111-8111-111111111111" }, body: "{}" }), context("outbound/calls"));
    expect(response.status).toBe(403);
    vi.mocked(authenticated).mockResolvedValue(false);
    expect((await GET(new NextRequest("https://dwellcall.test/api/ops/outbound/requests/11111111-1111-4111-8111-111111111111"), context("outbound/requests/11111111-1111-4111-8111-111111111111"))).status).toBe(401);
    expect(operatorBackend).not.toHaveBeenCalled();
  });
});
