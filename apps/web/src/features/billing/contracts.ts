export type PlanKey = "free" | "pro" | "team";
export type PricingPlan = { key: PlanKey; name: string; amount: number; currency: "usd"; interval: "month"; description: string; features: string[] };
export type PricingCatalog = { plans: PricingPlan[]; checkout_enabled: boolean };
export type BillingStatus = { account_id: string; plan: PlanKey; subscription_status: string; period_start: string | null; period_end: string | null; cancel_at_period_end: boolean; last_synced_at: string | null; checkout_enabled: boolean; portal_enabled: boolean; sync_pending: boolean; checkout_pending: boolean };
export function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
export function parsePlanKey(value: unknown): PlanKey | undefined {
  return value === "free" || value === "pro" || value === "team" ? value : undefined;
}
export function parseCatalog(value: unknown): PricingCatalog {
  if (!record(value) || typeof value.checkout_enabled !== "boolean" || !Array.isArray(value.plans) || value.plans.length !== 3) throw new Error("Pricing could not be loaded.");
  const plans = value.plans.map((plan: unknown): PricingPlan => {
    if (!record(plan) || !parsePlanKey(plan.key) || typeof plan.name !== "string" || !Number.isSafeInteger(plan.amount) || Number(plan.amount) < 0 || plan.currency !== "usd" || plan.interval !== "month" || typeof plan.description !== "string" || !Array.isArray(plan.features) || !plan.features.every((item: unknown) => typeof item === "string")) throw new Error("Pricing could not be loaded.");
    return { key: parsePlanKey(plan.key)!, name: plan.name, amount: Number(plan.amount), currency: "usd", interval: "month", description: plan.description, features: plan.features };
  });
  if (new Set(plans.map(plan => plan.key)).size !== 3) throw new Error("Pricing could not be loaded.");
  return { plans, checkout_enabled: value.checkout_enabled };
}
export function parseBillingStatus(value: unknown): BillingStatus {
  if (!record(value) || typeof value.account_id !== "string" || !parsePlanKey(value.plan) || typeof value.subscription_status !== "string" || !["checkout_enabled", "portal_enabled", "sync_pending", "checkout_pending", "cancel_at_period_end"].every(key => typeof value[key] === "boolean") || !["period_start", "period_end", "last_synced_at"].every(key => value[key] === null || typeof value[key] === "string" && Number.isFinite(Date.parse(value[key] as string)))) throw new Error("Billing status could not be loaded.");
  return value as BillingStatus;
}
export function formatPlanPrice(plan: PricingPlan): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: plan.currency.toUpperCase(), maximumFractionDigits: 0 }).format(plan.amount / 100);
}
export function stripeRedirect(value: unknown, kind: "checkout" | "portal"): string {
  if (!record(value) || typeof value.url !== "string") throw new Error("Stripe did not provide a redirect.");
  const url = new URL(value.url);
  if (url.protocol !== "https:" || url.hostname !== (kind === "checkout" ? "checkout.stripe.com" : "billing.stripe.com") || url.username || url.password || url.port) throw new Error("Stripe returned an invalid redirect.");
  return value.url;
}
