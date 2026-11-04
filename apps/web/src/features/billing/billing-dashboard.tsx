"use client";
import { useEffect, useState } from "react";
import { formatPlanPrice, parseBillingStatus, record, stripeRedirect, type BillingStatus, type PlanKey, type PricingCatalog } from "./contracts";

type Pending = { request_id: string; plan: "pro" | "team" };
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i;
async function billingRequest(action: string, body?: object): Promise<unknown> {
  const response = await fetch(`/api/billing/${action}`, { method: body === undefined ? "GET" : "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store", signal: AbortSignal.timeout(60_000) });
  const result: unknown = await response.json();
  if (!response.ok) throw new Error(record(result) && record(result.error) && typeof result.error.message === "string" ? result.error.message : "Billing is unavailable. Keep your saved request and try again shortly.");
  return result;
}

export function BillingDashboard({ accountId, catalog, initialPlan, checkoutResult }: { accountId: string; catalog: PricingCatalog | null; initialPlan?: PlanKey; checkoutResult?: string }) {
  const storageKey = `dwellcall:billing:${accountId}`;
  const [status, setStatus] = useState<BillingStatus>();
  const [plan, setPlan] = useState<"pro" | "team">(initialPlan === "team" ? "team" : "pro");
  const [pending, setPending] = useState<Pending>();
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    try {
      const saved = sessionStorage.getItem(storageKey);
      if (saved) {
        const value: unknown = JSON.parse(saved);
        if (!record(value) || typeof value.request_id !== "string" || !uuid.test(value.request_id) || value.plan !== "pro" && value.plan !== "team") throw new Error("The saved checkout request could not be read. Refresh billing before preparing a new one.");
        const request: Pending = { request_id: value.request_id, plan: value.plan };
        setPending(request); setPlan(request.plan);
      }
      void billingRequest("status").then(value => { if (active) { setStatus(parseBillingStatus(value)); setReady(true); } }).catch(failure => { if (active) setError(failure instanceof Error ? failure.message : "Billing status is unavailable."); });
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Checkout storage is unavailable."); }
    return () => { active = false; };
  }, [storageKey]);
  async function refresh() {
    if (busy) return;
    setBusy(true); setError("");
    try { setStatus(parseBillingStatus(await billingRequest("refresh", {}))); setReady(true); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Billing could not be refreshed."); }
    finally { setBusy(false); }
  }
  async function checkout() {
    if (busy || !ready) return;
    setBusy(true); setError("");
    try {
      const request = pending ?? { plan, request_id: crypto.randomUUID() };
      sessionStorage.setItem(storageKey, JSON.stringify(request));
      setPending(request);
      const result = await billingRequest("checkout", request);
      window.location.assign(stripeRedirect(result, "checkout"));
    } catch (failure) {
      setError(failure instanceof Error && !["TimeoutError", "TypeError"].includes(failure.name) ? failure.message : "The checkout result is unconfirmed. Keep this request and refresh billing before retrying.");
      try { setStatus(parseBillingStatus(await billingRequest("status"))); } catch { /* Keep the saved request while billing is unavailable. */ }
    } finally { setBusy(false); }
  }
  async function portal() {
    if (busy) return;
    setBusy(true); setError("");
    try { window.location.assign(stripeRedirect(await billingRequest("portal", {}), "portal")); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Billing management is unavailable."); }
    finally { setBusy(false); }
  }
  return <div className="billing-content"><div className="section-heading"><p className="eyebrow">YOUR SUBSCRIPTION</p><h1>Room to grow.</h1><p>Manage your DwellCall plan and payment details.</p></div>
    {checkoutResult === "success" && <p className="notice" role="status">You returned from Stripe. Refresh billing to confirm your subscription.</p>}
    {checkoutResult === "canceled" && <p className="notice" role="status">You returned without completing checkout. You can resume the saved request.</p>}
    {error && <p className="notice error" role="alert">{error}</p>}
    {!ready && !error && <p role="status">Loading billing status…</p>}
    {status && <section className="ops-card"><div className="card-heading"><h2>Current plan: {status.plan === "free" ? "Free" : status.plan === "pro" ? "Pro" : "Team"}</h2><span className="release-label">{status.subscription_status.replaceAll("_", " ")}</span></div><p>{status.cancel_at_period_end ? "Cancellation is scheduled for the end of your paid period." : "Your subscription status is confirmed by Stripe reconciliation."}</p>{status.period_end && <p>Current period ends: {new Date(status.period_end).toLocaleString()}</p>}{status.last_synced_at && <p className="muted">Last confirmed: {new Date(status.last_synced_at).toLocaleString()}</p>}{status.sync_pending && <p className="notice">A Stripe update is waiting to synchronize. Refresh billing to apply it.</p>}<div className="actions"><button onClick={() => void refresh()} disabled={busy || !status.checkout_enabled}>{busy ? "Please wait…" : "Refresh billing"}</button><button onClick={() => void portal()} disabled={busy || !status.portal_enabled}>Manage payment and subscription ↗</button></div></section>}
    <section className="ops-card"><h2>Choose a monthly plan</h2>{catalog ? <><label htmlFor="billing-plan">Plan<select id="billing-plan" value={plan} disabled={busy || !!pending} onChange={event => setPlan(event.target.value === "team" ? "team" : "pro")}>{catalog.plans.filter(item => item.key !== "free").map(item => <option value={item.key} key={item.key}>{item.name} · {formatPlanPrice(item)} USD / month</option>)}</select></label><p className="muted">Subscriptions renew monthly. Existing subscribers change plans or cancel through the billing portal.</p><button className="primary" disabled={busy || !ready || !status?.checkout_enabled || status.plan !== "free"} onClick={() => void checkout()}>{pending ? "Resume saved checkout ↗" : "Continue to Stripe ↗"}</button></> : <p role="status">Pricing is temporarily unavailable.</p>}{status && !status.checkout_enabled && <p className="notice">Paid checkout is not available yet.</p>}{pending && <p className="muted">Your checkout request is saved in this tab until its result is confirmed. Reference: <code>{pending.request_id}</code></p>}{pending && status && !status.checkout_pending && <button disabled={busy} onClick={() => { sessionStorage.removeItem(storageKey); setPending(undefined); setError(""); }}>Clear completed request</button>}</section>
    <p className="muted">Provider availability, calling limits and owner-approved workspace access still apply. Team invitations and shared credit allowances are not included in this billing release.</p>
  </div>;
}
