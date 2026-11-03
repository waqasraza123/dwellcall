import { Suspense, type ReactNode } from "react";
import { redirect } from "next/navigation";
import { Brand, GitHubLink } from "@/components/brand";
import { authenticated } from "@/lib/operator-session";
import { Navigation } from "@/features/intelligence/navigation";
export const dynamic = "force-dynamic";
export default async function WorkspaceLayout({ children }: { children: ReactNode }) {
  if (!await authenticated()) redirect("/login");
  return <div className="workspace-shell"><a className="skip-link" href="#workspace-content">Skip to workspace</a><header className="workspace-header"><Brand/><div className="header-right"><span className="release-label">UNVERIFIED · owner acceptance pending</span><GitHubLink/></div></header><Suspense fallback={<p className="notice">Loading workspace navigation…</p>}><Navigation/></Suspense><main id="workspace-content" className="workspace-content" tabIndex={-1}>{children}</main><footer className="workspace-footer">Source permissions and verification determine what appears. No autonomous outreach.</footer></div>;
}
