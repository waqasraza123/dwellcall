import { platformExtensionsEnabled } from "@/lib/product-scope";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Brand } from "@/components/brand";
import { currentAccount } from "@/lib/account-session";
import { authPageHref } from "@/features/account/auth-continuation";
import { parsePlanKey } from "@/features/billing/contracts";
import { publicCatalog } from "@/features/billing/server";
import { BillingDashboard } from "@/features/billing/billing-dashboard";
import { SignOut } from "@/features/account/sign-out";
export const metadata = { title: "Billing", robots: { index: false, follow: false } };
export const dynamic = "force-dynamic";
export default async function BillingPage({ searchParams }: { searchParams: Promise<{ plan?: string | string[]; checkout?: string | string[] }> }) {
  if (!platformExtensionsEnabled()) redirect("/calls");
  const params = await searchParams;
  const plan = parsePlanKey(params.plan);
  const account = await currentAccount();
  if (account.status === "anonymous") redirect(authPageHref("/login", plan && plan !== "free" ? `billing-${plan}` : "billing"));
  return <div className="public-shell"><header className="top-nav"><Brand/><nav aria-label="Account navigation"><Link href="/pricing">Pricing</Link><Link href="/dashboard">Workspace →</Link><SignOut/></nav></header><main className="billing-page">{account.status === "authenticated" && account.user.operator_access ? <BillingDashboard accountId={account.user.id} catalog={await publicCatalog()} initialPlan={plan} checkoutResult={typeof params.checkout === "string" ? params.checkout : undefined}/> : <section className="ops-card"><h1>{account.status === "unavailable" ? "Account temporarily unavailable." : "Owner approval is pending."}</h1><p>{account.status === "unavailable" ? "Your session could not be checked. Please refresh shortly." : "Your account needs owner approval before purchasing or managing a subscription."}</p><Link href={plan && plan !== "free" ? `/account?returnTo=billing-${plan}` : "/account?returnTo=billing"}>View account status →</Link></section>}</main></div>;
}
