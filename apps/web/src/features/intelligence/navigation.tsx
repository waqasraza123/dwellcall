"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ProductIcon } from "@/components/product-icons";
import { SignOut } from "@/features/account/sign-out";
import { ExtensionNavigation } from "./extension-navigation";

export function Navigation({ extensionsEnabled = false }: { extensionsEnabled?: boolean }) {
  const pathname = usePathname();
  if (extensionsEnabled) return <ExtensionNavigation/>;
  return <><aside className="sidebar"><p className="eyebrow">CALL WORKSPACE</p><nav aria-label="Workspace navigation"><Link href="/calls" aria-current={pathname === "/calls" ? "page" : undefined}><ProductIcon name="phone"/>Calls &amp; results</Link><Link href="/?demo_call=1"><ProductIcon name="mic"/>Try the phone demo</Link></nav><div className="sidebar-bottom"><p>One call.<br/>A useful result.</p><small>DwellCall · owner acceptance pending</small></div></aside><div className="workspace-toolbar"><span className="muted">Requested outbound calls · AI only</span><SignOut/></div></>;
}
