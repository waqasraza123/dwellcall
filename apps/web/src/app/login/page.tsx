import { redirect } from "next/navigation";
import { Brand, GitHubLink } from "@/components/brand";
import { LoginForm } from "@/features/intelligence/login-form";
import { authenticated } from "@/lib/operator-session";
export const metadata = { title: "Operator sign in", robots: { index: false, follow: false } };
export default async function LoginPage({ searchParams }: { searchParams: Promise<{ returnTo?: string }> }) {
  const returnTo = (await searchParams).returnTo === "conversation" ? "conversation" : undefined;
  if (await authenticated()) redirect(returnTo === "conversation" ? "/#try-dwellcall" : "/dashboard");
  return <div className="public-shell"><header className="top-nav"><Brand/><GitHubLink/></header><main className="login-layout"><section className="login-intro"><p className="eyebrow">DWELLCALL WORKSPACE</p><h1>A clearer view.<br/>A stronger pipeline.</h1><p>Discover properties, understand the agents behind them and move qualified records into your CRM.</p><span className="release-label">UNVERIFIED · owner acceptance pending</span></section><section className="ops-card login-card"><p className="eyebrow">OPERATOR ACCESS</p><h2>Welcome back.</h2><p className="muted">Your market intelligence starts here.</p><LoginForm returnTo={returnTo}/></section></main></div>;
}
