import type { ReactNode } from "react";
import { Brand, GitHubLink } from "@/components/brand";

export function AuthLayout({ children }: { children: ReactNode }) {
  return <div className="public-shell"><header className="top-nav"><Brand/><GitHubLink/></header><main className="login-layout"><section className="login-intro"><p className="eyebrow">DWELLCALL WORKSPACE</p><h1>A clearer view.<br/>A stronger pipeline.</h1><p>Discover properties, understand the agents behind them and move qualified records into your CRM.</p><span className="release-label">UNVERIFIED · owner acceptance pending</span></section><section className="ops-card login-card">{children}</section></main></div>;
}
