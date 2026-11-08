import type { ReactNode } from "react";
import { Brand, GitHubLink } from "@/components/brand";

export function AuthLayout({ children }: { children: ReactNode }) {
  return <div className="public-shell"><header className="top-nav"><Brand/><GitHubLink/></header><main className="login-layout"><section className="login-intro"><p className="eyebrow">DWELLCALL WORKSPACE</p><h1>A useful conversation.<br/>A clear next step.</h1><p>Request an AI call, follow its progress and review the transcript and qualification summary.</p><span className="release-label">UNVERIFIED · owner acceptance pending</span></section><section className="ops-card login-card">{children}</section></main></div>;
}
