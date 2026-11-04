import { Suspense } from "react";
import { notFound } from "next/navigation";
import { Dashboard } from "@/features/intelligence/dashboard";
import { Agents, AgentDetail, Listings, ListingDetail } from "@/features/intelligence/listings";
import { Discovery } from "@/features/intelligence/discovery";
import { Reviews, ReviewDetail } from "@/features/intelligence/reviews";
import { Activity } from "@/features/intelligence/activity";
import { OutboundCalls } from "@/features/outbound/outbound-calls";
import { Crm } from "@/features/intelligence/crm";
const labels: Record<string, string> = { dashboard: "Overview", listings: "Properties", agents: "Agent intelligence", discovery: "Discovery", reviews: "Review queue", crm: "CRM integration", activity: "Activity", calls: "Outbound AI Calls" };
export async function generateMetadata({ params }: { params: Promise<{ section: string }> }) { const { section } = await params; return { title: labels[section] ?? "Workspace", robots: { index: false, follow: false } }; }
export default async function WorkspacePage({ params }: { params: Promise<{ section: string; detail?: string[] }> }) {
  const { section, detail } = await params;
  if (!Object.hasOwn(labels, section) || (detail?.length ?? 0) > 1) notFound();
  const id = detail?.[0];
  if (id && (!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(id) || !["listings", "agents", "reviews"].includes(section))) notFound();
  const content = section === "dashboard" ? <Dashboard/> : section === "listings" ? id ? <ListingDetail id={id}/> : <Listings/> : section === "agents" ? id ? <AgentDetail id={id}/> : <Agents/> : section === "discovery" ? <Discovery/> : section === "reviews" ? id ? <ReviewDetail id={id}/> : <Reviews/> : section === "crm" ? <Crm/> : section === "calls" ? <OutboundCalls/> : <Activity/>;
  return <Suspense fallback={<p role="status" className="notice">Loading workspace…</p>}>{content}</Suspense>;
}
