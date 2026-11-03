"use client";
import Link from "next/link";
import { params, useResource } from "./api";
import type { Dashboard as DashboardData, Event, Listing, Page, Source } from "./contracts";
import { address, date, Empty, money, State, Status, Table, useWorkspace } from "./ui";

export function Dashboard() {
  const { mode } = useWorkspace();
  const data = useResource<DashboardData>(`intelligence/workspace/dashboard?mode=${mode}`);
  const recent = useResource<Page<Listing>>(`intelligence/listings?${params({ mode, page_size: 5, sort: "updated" })}`);
  const activity = useResource<Page<Event>>(`intelligence/workspace/activity?${params({ mode, page_size: 5, kind: "discovery" })}`);
  const sources = useResource<Source[]>("intelligence/sources");
  function refresh() { data.refresh(); recent.refresh(); activity.refresh(); sources.refresh(); }
  return <><div className="section-heading"><div><p className="eyebrow">YOUR MARKET, IN FOCUS</p><h1>Your next opportunity starts here.</h1><p>New properties. Clear identities. A pipeline you can trust.</p></div><button onClick={refresh}>Refresh overview ↻</button></div>
    <State {...data} retry={data.refresh}>{data.data && <>
      <div className="ops-metrics">{([ ["Discovered listings", "listings"], ["New today · UTC", "new_today"], ["Listing agents", "agents"], ["Verified business contacts", "verified_agents"], ["Agents synced to CRM", "synced"], ["Pending sync jobs", "pending"], ["Failed / uncertain jobs", "failed"] ] as const).map(([label, key]) => <article key={key}><span>{label}</span><strong>{data.data!.metrics[key].toLocaleString()}</strong></article>)}</div>
      <div className="detail-grid chart-grid"><section className="ops-card"><div className="card-heading"><h2>Discovery over time</h2><span className="muted">Last 14 days · UTC</span></div><Trend values={data.data.trend}/></section><section className="ops-card"><h2>Lead distribution</h2><p className="muted">Properties by source-reported listing status</p><Distribution values={data.data.distribution}/></section></div>
      <p className="timestamp">As of {date(data.data.as_of)} UTC. {mode === "synthetic" ? "Demo data is excluded from live CRM exports." : "Only records with current display permissions and retention appear."}</p>
    </>}</State>
    <section className="ops-card"><div className="card-heading"><h2>Recently updated listings</h2><Link href={`/listings?mode=${mode}`}>View listings →</Link></div><State {...recent} retry={recent.refresh}>{recent.data && (recent.data.items.length ? <Table label="Recent listings" headers={["Property", "Price", "Status", "Source updated (UTC)"]}>{recent.data.items.map(row => <tr key={row.id}><td><Link className="record-title" href={`/listings/${row.id}?mode=${mode}`}>{row.property.street_address ?? "Address not supplied"}</Link><small>{address(row.property)}</small></td><td>{money(row.property)}</td><td><Status value={row.property.status}/></td><td>{date(row.property.source_updated_at)}</td></tr>)}</Table> : <Empty>Run a permitted discovery job to bring your first properties into view. <Link href="/discovery">Open discovery →</Link></Empty>)}</State></section>
    <div className="detail-grid"><section className="ops-card"><div className="card-heading"><h2>Discovery activity</h2><Link href="/discovery">Manage jobs →</Link></div><State {...activity} retry={activity.refresh}>{activity.data && (activity.data.items.length ? <ul className="activity-list">{activity.data.items.map(row => <li key={row.id}><div><strong>{row.summary.replaceAll("_", " ")}</strong><small>{row.source} · {date(row.at)} UTC</small></div><Status value={row.status}/></li>)}</ul> : <Empty>No discovery activity has been recorded.</Empty>)}</State></section>
    <section className="ops-card"><h2>Source health</h2><State {...sources} retry={sources.refresh}>{sources.data && (sources.data.length ? <ul className="activity-list">{sources.data.filter(s => s.permissions.data_mode === mode).map(source => <li key={source.source_key}><div><strong>{source.source_key}</strong><small>{source.permissions.provider} · {source.permissions.data_mode === "synthetic" ? "Demo file source" : "Permission-scoped file import"}</small><small>Last successful import: {date(source.last_success_at)}</small></div><Status value={source.permissions.enabled ? "enabled" : "disabled"}/></li>)}</ul> : <Empty>No source permissions have been registered. <Link href="/discovery">Configure discovery →</Link></Empty>)}</State></section></div>
  </>;
}
function Trend({ values }: { values: { label: string; value: number }[] }) {
  const max = Math.max(1, ...values.map(v => v.value));
  return <><svg className="trend-chart" viewBox="0 0 560 170" role="img" aria-labelledby="trend-title trend-desc"><title id="trend-title">Newly discovered listings per day</title><desc id="trend-desc">{values.map(v => `${v.label}: ${v.value}`).join("; ")}</desc>{[0, 1, 2].map(i => <line key={i} x1="20" x2="550" y1={20 + i * 60} y2={20 + i * 60} stroke="var(--line)"/>)}{values.map((v, i) => <g key={v.label}><rect x={24 + i * 37} y={140 - v.value / max * 110} width="22" height={v.value / max * 110} rx="2" fill="var(--bronze)"/><text x={35 + i * 37} y={132 - v.value / max * 110} textAnchor="middle" fontSize="10" fill="var(--muted)">{v.value || ""}</text>{i % 3 === 0 && <text x={35 + i * 37} y="163" textAnchor="middle" fontSize="10" fill="var(--muted)">{v.label.slice(5)}</text>}</g>)}</svg><details className="chart-data"><summary>View chart data</summary><Table label="Daily listing counts" headers={["Date (UTC)", "New listings"]}>{values.map(v => <tr key={v.label}><td>{v.label}</td><td>{v.value}</td></tr>)}</Table></details></>;
}
function Distribution({ values }: { values: { label: string; value: number }[] }) {
  const total = values.reduce((sum, v) => sum + v.value, 0);
  if (!total) return <Empty>No listings are available for this data mode.</Empty>;
  return <ul className="distribution">{values.map(v => <li key={v.label}><div><Status value={v.label}/><span>{v.value.toLocaleString()} · {Math.round(v.value / total * 100)}%</span></div><meter min={0} max={total} value={v.value} aria-label={`${v.label}: ${v.value} of ${total} properties`}/></li>)}</ul>;
}
