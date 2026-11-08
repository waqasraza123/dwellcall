import { platformExtensionsEnabled } from "@/lib/product-scope";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Brand, GitHubLink } from "@/components/brand";
import { PricingSection } from "@/features/billing/pricing-section";
export const metadata = { title: "Pricing" };
export const dynamic = "force-dynamic";
export default function PricingPage() {
  if (!platformExtensionsEnabled()) redirect("/");
  return <div className="public-shell"><header className="top-nav"><Brand/><nav aria-label="Main navigation"><GitHubLink/><Link href="/login">Sign in →</Link></nav></header><main><PricingSection/></main><footer className="public-footer"><Brand/><Link href="/">Back to home</Link></footer></div>;
}
