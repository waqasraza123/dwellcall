import { platformExtensionsEnabled } from "@/lib/product-scope";
import { Suspense, type ReactNode } from "react";
import { redirect } from "next/navigation";
import { Brand, GitHubLink } from "@/components/brand";
import { currentAccount } from "@/lib/account-session";
import { Navigation } from "@/features/intelligence/navigation";
export const dynamic = "force-dynamic";
export default async function WorkspaceLayout({ children }: { children: ReactNode }) {
  const account = await currentAccount();
  if (account.status === "anonymous") redirect("/login");
  if (account.status === "unavailable") return <p className="notice error">Workspace access could not be checked. Please refresh shortly.</p>;
  if (account.status !== "authenticated" || !account.user.operator_access) redirect("/account");
  return <div className="workspace-shell"><a className="skip-link" href="#workspace-content">Skip to workspace</a><header className="workspace-header"><Brand/><div className="header-right"><span className="release-label">UNVERIFIED · owner acceptance pending</span><GitHubLink/></div></header><Suspense fallback={<p className="notice">Loading workspace navigation…</p>}><Navigation extensionsEnabled={platformExtensionsEnabled()}/></Suspense><main id="workspace-content" className="workspace-content" tabIndex={-1}>{children}</main><footer className="workspace-footer">Each call requires recipient permission. Transcripts and qualification summaries stay in the call workspace.</footer></div>;
}
