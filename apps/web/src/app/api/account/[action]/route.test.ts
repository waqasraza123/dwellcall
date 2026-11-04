import { beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
vi.mock("@/lib/account-session", async () => {
  const original = await vi.importActual<typeof import("@/lib/account-session")>("@/lib/account-session");
  return { ...original, accountBackend: vi.fn() };
});
import { accountBackend } from "@/lib/account-session";
import { GET, POST } from "./route";
const context = (action: string) => ({ params: Promise.resolve({ action }) });
const request = (origin = "https://dwellcall.test", body = "{}") => new NextRequest("https://dwellcall.test/api/account/login", { method: "POST", headers: { Origin: origin, "Content-Type": "application/json" }, body });
beforeEach(() => vi.resetAllMocks());
it("keeps the MFA challenge in an HttpOnly cookie without issuing a session", async () => {
  vi.mocked(accountBackend).mockResolvedValue(Response.json({ mfa_required: true, next_action: "verify", challenge_token: "x".repeat(43), expires_in: 600 }));
  const response = await POST(request(), context("login"));
  expect(response.status).toBe(200);
  expect(await response.json()).toEqual({ mfa_required: true, next_action: "verify" });
  expect(response.cookies.get("dwellcall-mfa")?.value).toBe("x".repeat(43));
  expect(response.cookies.get("dwellcall-session")?.value).toBe("");
  expect(response.headers.get("set-cookie")).toContain("HttpOnly");
  expect(response.headers.get("set-cookie")).toContain("SameSite=strict");
});
it("issues a session only after MFA and removes the challenge cookie", async () => {
  vi.mocked(accountBackend).mockResolvedValue(Response.json({ mfa_verified: true, session_token: "s".repeat(43), expires_in: 28800, user: { id: "synthetic-account", email: "demo@example.com", full_name: "Demo", operator_access: false }, recovery_codes: null }));
  const response = await POST(request(), context("mfa-verify"));
  expect(response.status).toBe(200);
  expect(response.cookies.get("dwellcall-session")?.value).toBe("s".repeat(43));
  expect(response.cookies.get("dwellcall-mfa")?.value).toBe("");
  expect(JSON.stringify(await response.json())).not.toContain("session_token");
});
it("rejects an upstream session before MFA", async () => {
  vi.mocked(accountBackend).mockResolvedValue(Response.json({ session_token: "s".repeat(43), expires_in: 28800 }));
  expect((await POST(request(), context("login"))).status).toBe(502);
});
it("rejects cross-site actions and oversized bodies before contacting the backend", async () => {
  expect((await POST(request("https://other.test"), context("login"))).status).toBe(403);
  expect((await POST(request("https://dwellcall.test", JSON.stringify({ password: "x".repeat(4096) })), context("login"))).status).toBe(413);
  expect(accountBackend).not.toHaveBeenCalled();
});
it("does not clear the session until database revocation succeeds", async () => {
  vi.mocked(accountBackend).mockResolvedValue(new Response(null, { status: 503 }));
  const response = await POST(request(), context("logout"));
  expect(response.status).toBe(503);
  expect(response.headers.has("set-cookie")).toBe(false);
});
it("does not expose arbitrary backend paths", async () => {
  expect((await GET(new NextRequest("https://dwellcall.test/api/account/admin"), context("admin"))).status).toBe(404);
  expect(accountBackend).not.toHaveBeenCalled();
});
