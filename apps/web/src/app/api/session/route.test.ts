import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest, NextResponse } from "next/server";
vi.mock("../account/[action]/route", () => ({ POST: vi.fn() }));
import { POST as accountAction } from "../account/[action]/route";
import { POST, DELETE } from "./route";
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(accountAction).mockResolvedValue(new NextResponse(null, { status: 204 }));
});
describe("legacy session endpoint", () => {
  it("delegates login to the mandatory MFA flow", async () => {
    const request = new NextRequest("https://dwellcall.test/api/session", { method: "POST" });
    await POST(request);
    const [forwarded, context] = vi.mocked(accountAction).mock.calls[0];
    expect(forwarded).toBe(request);
    expect(await context.params).toEqual({ action: "login" });
  });
  it("maps DELETE to revocation while preserving the origin for CSRF checks", async () => {
    await DELETE(new NextRequest("https://dwellcall.test/api/session", { method: "DELETE", headers: { Origin: "https://other.test" } }));
    const [forwarded, context] = vi.mocked(accountAction).mock.calls[0];
    expect(forwarded.method).toBe("POST");
    expect(forwarded.headers.get("origin")).toBe("https://other.test");
    expect(await context.params).toEqual({ action: "logout" });
  });
});
