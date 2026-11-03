import { afterEach, describe, expect, it, vi } from "vitest";
vi.mock("next/headers", () => ({ cookies: vi.fn() }));
import { issueSession, validPassword, verifySession } from "./operator-session";
afterEach(() => { vi.unstubAllEnvs(); vi.useRealTimers(); });
describe("operator sessions", () => {
  it("fails closed without independent strong configuration", () => {
    vi.stubEnv("DWELLCALL_OPERATOR_PASSWORD", "short");
    vi.stubEnv("DWELLCALL_SESSION_SECRET", "");
    expect(validPassword("short")).toBe(false);
    expect(verifySession("forged.signature")).toBe(false);
    expect(() => issueSession()).toThrow();
  });
  it("rejects tampered and expired cookies", () => {
    vi.useFakeTimers(); vi.setSystemTime(new Date("2026-11-03T00:00:00Z"));
    vi.stubEnv("DWELLCALL_SESSION_SECRET", "synthetic-session-secret-xxxxxxxxxxxxxxxx");
    const cookie = issueSession();
    expect(verifySession(cookie)).toBe(true);
    expect(verifySession(cookie + "x")).toBe(false);
    vi.advanceTimersByTime(8 * 60 * 60 * 1000 + 1);
    expect(verifySession(cookie)).toBe(false);
  });
});
