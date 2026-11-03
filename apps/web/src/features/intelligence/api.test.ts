import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { requestApi } from "./api";
let storage: Map<string, string>;
beforeEach(() => { storage = new Map(); vi.stubGlobal("sessionStorage", { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value), removeItem: (key: string) => storage.delete(key) }); });
afterEach(() => vi.unstubAllGlobals());
describe("workspace requests", () => {
  it("keeps auth credentials off browser requests and disables caching", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ total: 3, items: [] })); vi.stubGlobal("fetch", fetcher);
    await requestApi("intelligence/listings?mode=live&q=Austin");
    expect(fetcher.mock.calls[0][0]).toBe("/api/ops/intelligence/listings?mode=live&q=Austin");
    expect(fetcher.mock.calls[0][1].cache).toBe("no-store");
    expect(fetcher.mock.calls[0][1].headers).not.toHaveProperty("X-Admin-Token");
    expect(fetcher.mock.calls[0][1].headers).not.toHaveProperty("Authorization");
  });
  it("reuses the same durable action key after an uncertain network outcome", async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new TypeError("network lost")).mockResolvedValueOnce(Response.json({ status: "sent" })); vi.stubGlobal("fetch", fetcher);
    await expect(requestApi("crm/ghl/jobs/process?batch_size=12", "POST", {})).rejects.toThrow();
    expect(storage.size).toBe(1);
    await requestApi("crm/ghl/jobs/process?batch_size=12", "POST", {});
    expect(fetcher.mock.calls[0][1].headers["Idempotency-Key"]).toBe(fetcher.mock.calls[1][1].headers["Idempotency-Key"]);
    expect(storage.size).toBe(0);
  });
  it("does not auto-retry a failed write", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ error: { message: "Inspect history" } }, { status: 503 })); vi.stubGlobal("fetch", fetcher);
    await expect(requestApi("crm/ghl/agents/queue", "POST", { agent_ids: ["demo"] })).rejects.toThrow("Inspect history");
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(storage.size).toBe(1);
  });
});

it("HubSpot schema changes require an explicit POST carrying an action key", async () => {
  const fetcher = vi.fn().mockResolvedValue(Response.json({ properties: { agent_id: "created" } }));
  vi.stubGlobal("fetch", fetcher);
  const body = { evidence_reference: "mock-owner-approval", approve_external_creation: true, custom_fields: { agent_id: "dwellcall_agent_id" } };
  await requestApi("crm/hubspot/properties/create", "POST", body);
  expect(fetcher.mock.calls[0][0]).toBe("/api/ops/crm/hubspot/properties/create");
  expect(fetcher.mock.calls[0][1].method).toBe("POST");
  expect(fetcher.mock.calls[0][1].headers["Idempotency-Key"]).toMatch(/^[a-f0-9-]{36}$/i);
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual(body);
  expect(fetcher.mock.calls[0][1].headers).not.toHaveProperty("Authorization");
});
