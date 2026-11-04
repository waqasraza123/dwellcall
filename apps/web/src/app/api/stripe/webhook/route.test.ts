import { afterEach, expect, it, vi } from "vitest";
import { POST } from "./route";
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });
it("preserves raw webhook bytes and the Stripe signature without account or admin credentials", async () => {
  vi.stubEnv("DWELLCALL_API_BASE_URL", "https://api.dwellcall.test");
  const fetcher = vi.fn().mockResolvedValue(Response.json({ received: true }));
  vi.stubGlobal("fetch", fetcher);
  const body = '{\n  "id": "evt_synthetic"\n}\n';
  const response = await POST(new Request("https://dwellcall.test/api/stripe/webhook", { method: "POST", headers: { "Stripe-Signature": "synthetic-signature" }, body }));
  expect(response.status).toBe(200);
  const [url, options] = fetcher.mock.calls[0];
  expect(url).toBe("https://api.dwellcall.test/api/v1/billing/webhook");
  expect(new TextDecoder().decode(options.body)).toBe(body);
  expect(options.headers).toEqual({ "Content-Type": "application/json", "Stripe-Signature": "synthetic-signature" });
});
it("bounds the actual body even without a Content-Length header", async () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  const response = await POST(new Request("https://dwellcall.test/api/stripe/webhook", { method: "POST", body: "x".repeat(1_048_577) }));
  expect(response.status).toBe(413);
  expect(fetcher).not.toHaveBeenCalled();
});
