import { describe, expect, it } from "vitest";
import { bridgeAllowed } from "./bridge-policy";
const id = "11111111-1111-4111-8111-111111111111";
describe("operator bridge capability boundary", () => {
  it("allows the implemented reads and deliberate writes", () => {
    expect(bridgeAllowed("GET", "intelligence/workspace/dashboard")).toBe(true);
    expect(bridgeAllowed("GET", `intelligence/workspace/listings/${id}/history`)).toBe(true);
    expect(bridgeAllowed("POST", `intelligence/reviews/${id}/resolve`)).toBe(true);
    expect(bridgeAllowed("POST", "crm/ghl/jobs/process")).toBe(true);
    expect(bridgeAllowed("PUT", `intelligence/workspace/jobs/${id}`)).toBe(true);
  });
  it("does not turn page reads into CRM dispatch or expose provisioning", () => {
    expect(bridgeAllowed("GET", "crm/ghl/jobs/process")).toBe(false);
    expect(bridgeAllowed("POST", "crm/ghl/locations/provision")).toBe(false);
    expect(bridgeAllowed("GET", "intelligence/../secrets")).toBe(false);
    expect(bridgeAllowed("GET", "intelligence/%2e%2e/secrets")).toBe(false);
    expect(bridgeAllowed("POST", "intelligence/sources/demo/purge")).toBe(false);
  });
});

it("exposes explicit HubSpot operations without turning reads into writes", () => {
  expect(bridgeAllowed("GET", "crm/providers")).toBe(true);
  expect(bridgeAllowed("GET", "crm/hubspot/status")).toBe(true);
  expect(bridgeAllowed("GET", "crm/hubspot/agents")).toBe(true);
  expect(bridgeAllowed("POST", "crm/hubspot/setup")).toBe(true);
  expect(bridgeAllowed("POST", "crm/hubspot/properties/create")).toBe(true);
  expect(bridgeAllowed("POST", `crm/hubspot/jobs/${id}/reconcile`)).toBe(true);
  expect(bridgeAllowed("GET", "crm/hubspot/properties/create")).toBe(false);
  expect(bridgeAllowed("GET", "crm/hubspot/jobs/process")).toBe(false);
  expect(bridgeAllowed("POST", "crm/hubspot/credentials")).toBe(false);
});
