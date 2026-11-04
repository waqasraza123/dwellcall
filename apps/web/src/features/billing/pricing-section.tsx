import Link from "next/link";
import { ProductIcon } from "@/components/product-icons";
import { authPageHref } from "@/features/account/auth-continuation";
import { formatPlanPrice } from "./contracts";
import { publicCatalog } from "./server";

export async function PricingSection() {
  const catalog = await publicCatalog();
  return <section className="pricing-section" id="pricing" aria-labelledby="pricing-heading"><div className="section-heading"><p className="eyebrow">A PLAN FOR YOUR NEXT MOVE</p><h2 id="pricing-heading">Start with clarity.<br/>Grow your pipeline.</h2><p>Choose a monthly DwellCall subscription. Workspace access requires owner approval.</p></div>
    {catalog ? <><div className="pricing-grid">{catalog.plans.map(plan => <article className={`pricing-card${plan.key === "pro" ? " pricing-featured" : ""}`} key={plan.key}><div className="pricing-card-top"><h3>{plan.name}</h3>{plan.key === "pro" && <span className="eyebrow">PRO PLAN</span>}</div><p className="muted">{plan.description}</p><p className="pricing-amount">{formatPlanPrice(plan)}<span>USD / month</span></p><ul>{plan.features.map(feature => <li key={feature}><ProductIcon name="check"/>{feature}</li>)}</ul><Link className={plan.key === "free" ? "secondary" : "primary"} href={authPageHref("/signup", plan.key === "free" ? undefined : `billing-${plan.key}`)}>{plan.key === "free" ? "Create a Free account" : `Choose ${plan.name}`} →</Link></article>)}</div>
    <p className="muted pricing-footnote">Paid plans renew monthly. Manage payment details, plan changes and cancellation through Stripe. Calling limits and provider availability remain subject to your workspace configuration. Team invitations and shared credit allowances are not available yet.</p>
    {!catalog.checkout_enabled && <p className="notice" role="status">Paid checkout is not available yet. You can create a Free account.</p>}</> : <p className="notice" role="status">Pricing is temporarily unavailable. Please try again shortly.</p>}
  </section>;
}
