import { expect, it } from "vitest";
import { parseAuthIntent, authPageHref, authReturnHref } from "@/features/account/auth-continuation";
import { parseCatalog, stripeRedirect } from "./contracts";

it("keeps plan selection through signup and mandatory MFA without open redirects", () => {
  expect(authPageHref("/signup", "billing-team")).toBe("/signup?returnTo=billing-team");
  expect(authPageHref("/mfa", "billing-team")).toBe("/mfa?returnTo=billing-team");
  expect(authReturnHref(parseAuthIntent("billing-team"))).toBe("/billing?plan=team");
  expect(authReturnHref(parseAuthIntent("billing-pro"))).toBe("/billing?plan=pro");
  expect(authReturnHref(parseAuthIntent("https://foreign.test"))).toBe("/account");
  expect(authReturnHref("conversation")).toBe("/account?returnTo=conversation");
});
it("rejects foreign Stripe redirects", () => {
  expect(stripeRedirect({ url: "https://checkout.stripe.com/synthetic" }, "checkout")).toBe("https://checkout.stripe.com/synthetic");
  for (const url of ["https://checkout.stripe.com.foreign.test/test", "https://checkout.stripe.com@foreign.test/test", "javascript:alert(1)", "https://billing.stripe.com/test"]) expect(() => stripeRedirect({ url }, "checkout")).toThrow();
});
it("rejects inconsistent catalogs", () => {
  const plans = ["free", "pro", "team"].map(key => ({ key, name: key, amount: 0, currency: "usd", interval: "month", description: "Synthetic", features: [] }));
  expect(parseCatalog({ plans, checkout_enabled: false }).plans).toHaveLength(3);
  expect(() => parseCatalog({ plans: [plans[0], plans[0], plans[2]], checkout_enabled: false })).toThrow();
  expect(() => parseCatalog({ plans: plans.map(plan => ({ ...plan, currency: "eur" })), checkout_enabled: false })).toThrow();
});
