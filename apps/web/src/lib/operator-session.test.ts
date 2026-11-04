import { beforeEach, describe, expect, it, vi } from "vitest";
vi.mock("./account-session", () => ({ currentAccount: vi.fn() }));
import { currentAccount } from "./account-session";
import { authenticated } from "./operator-session";

beforeEach(() => vi.resetAllMocks());
describe("operator authorization", () => {
  it("requires a database-backed MFA session with owner-approved access", async () => {
    vi.mocked(currentAccount).mockResolvedValue({ status: "authenticated", user: { id: "synthetic-account", full_name: "Demo", email: "demo@example.com", operator_access: false } });
    expect(await authenticated()).toBe(false);
    vi.mocked(currentAccount).mockResolvedValue({ status: "authenticated", user: { id: "synthetic-account", full_name: "Demo", email: "demo@example.com", operator_access: true } });
    expect(await authenticated()).toBe(true);
  });
  it.each(["anonymous", "unavailable"] as const)("denies %s sessions", async status => {
    vi.mocked(currentAccount).mockResolvedValue({ status });
    expect(await authenticated()).toBe(false);
  });
});
