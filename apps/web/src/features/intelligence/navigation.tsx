"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { useWorkspace } from "./ui";
import { ProductIcon } from "@/components/product-icons";
const links = [["dashboard", "Overview", "home"], ["listings", "Properties", "home"], ["agents", "Agent intelligence", "shield"], ["discovery", "Discovery", "arrow"], ["reviews", "Review queue", "shield"], ["crm", "CRM integration", "check"], ["calls", "Outbound AI Calls", "clock"], ["activity", "Activity", "clock"]] as const;
export function Navigation() {
  const pathname = usePathname(); const { mode, update } = useWorkspace(); const router = useRouter(); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  return <><aside className="sidebar"><p className="eyebrow">WORKSPACE</p><nav aria-label="Workspace navigation">{links.map(([path, label, icon]) => <Link aria-current={pathname.startsWith(`/${path}`) ? "page" : undefined} href={`/${path}?mode=${mode}`} key={path}><span aria-hidden="true"><ProductIcon name={icon}/></span>{label}</Link>)}</nav><div className="sidebar-bottom"><p>Built for a clearer<br/>view of the market.</p><small>DwellCall · UNVERIFIED</small></div></aside><div className="workspace-toolbar"><div className="mode-control"><label htmlFor="data-mode">Data mode</label><select id="data-mode" value={mode} onChange={e => update({ mode: e.target.value })}><option value="synthetic">Demo · synthetic data</option><option value="live">Live · authorized data</option></select></div><div className="toolbar-right"><span className="muted">Operator workspace</span><button disabled={busy} onClick={async () => { setBusy(true); setError(""); try { const response = await fetch("/api/session", { method: "DELETE", cache: "no-store" }); if (!response.ok) throw new Error("Sign out could not be completed."); router.replace("/login"); router.refresh(); } catch { setError("Sign out is unavailable. Try again."); } finally { setBusy(false); } }}>{busy ? "Signing out…" : "Sign out"}</button></div>{error && <p role="alert">{error}</p>}</div></>;
}
