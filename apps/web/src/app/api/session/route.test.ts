import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
vi.mock("@/lib/backend", async () => { const original = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend"); return { ...original, operatorBackend: vi.fn() }; });
import { operatorBackend } from "@/lib/backend";
import { POST } from "./route";
afterEach(() => { vi.resetAllMocks(); vi.unstubAllEnvs(); });
describe("operator login", () => {
  it("sets only a signed HttpOnly session, never backend credentials", async () => {
    vi.stubEnv("DWELLCALL_OPERATOR_PASSWORD", "synthetic-operator-password-xxxxxxxxxxxx");
    vi.stubEnv("DWELLCALL_SESSION_SECRET", "synthetic-signing-secret-xxxxxxxxxxxxxx");
    vi.mocked(operatorBackend).mockResolvedValue(Response.json({ configured: false }));
    const response = await POST(new NextRequest("https://dwellcall.test/api/session", { method: "POST", headers: { Origin: "https://dwellcall.test", "Content-Type": "application/json" }, body: JSON.stringify({ password: "synthetic-operator-password-xxxxxxxxxxxx" }) }));
    expect(response.status).toBe(200);
    expect(response.headers.get("set-cookie")).toContain("HttpOnly");
    expect(response.headers.get("set-cookie")).toContain("SameSite=strict");
    expect(await response.json()).toEqual({ authenticated: true });
    expect(response.headers.get("set-cookie")).not.toContain("synthetic-operator-password");
  });
  it("rejects cross-origin authentication before contacting the backend", async () => {
    const response = await POST(new NextRequest("https://dwellcall.test/api/session", { method: "POST", headers: { Origin: "https://other.test", "Content-Type": "application/json" }, body: "{}" }));
    expect(response.status).toBe(403);
    expect(operatorBackend).not.toHaveBeenCalled();
  });
});
