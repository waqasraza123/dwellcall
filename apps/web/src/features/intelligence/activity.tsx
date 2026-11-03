"use client";
import Link from "next/link";
import { params, useResource } from "./api";
import type { Event, Page } from "./contracts";
import { date, Empty, Filters, Pager, State, Status, Table, useWorkspace } from "./ui";

export function Activity() {
  const { mode, page, search, update } = useWorkspace();
  const data = useResource<Page<Event>>(`intelligence/workspace/activity?${params({ mode, page, q: search.get("q"), kind: search.get("kind"), status: search.get("status") })}`);
  const href = (row: Event) => row.kind === "listing" ? `/listings/${row.reference}?mode=${mode}` : row.kind === "review" ? `/reviews/${row.reference}?mode=${mode}` : row.kind === "crm" ? `/crm?job=${row.reference}` : "/discovery";
  return <><div className="section-heading"><div><p className="eyebrow">AUTOMATION & ACTIVITY</p><h1>Follow the work.</h1><p>Discovery, listing changes, review decisions and CRM outcomes.</p></div><button onClick={data.refresh}>Refresh activity</button></div><p className="notice">AI enrichment is not configured. Only events actually recorded by the backend appear here.</p>
    <Filters key={search.toString()} onSubmit={f => update({ q: String(f.get("q") ?? ""), kind: String(f.get("kind") ?? ""), status: String(f.get("status") ?? "") })}><label className="search-field">Search events<input name="q" maxLength={120} defaultValue={search.get("q") ?? ""} placeholder="Event description"/></label><label>Event type<select name="kind" defaultValue={search.get("kind") ?? ""}><option value="">All events</option>{["discovery", "listing", "review", "crm", "system"].map(v => <option key={v}>{v}</option>)}</select></label><label>Status<select name="status" defaultValue={search.get("status") ?? ""}><option value="">All statuses</option>{["failed", "unknown", "running", "partial", "completed", "pending", "approved", "rejected", "sent", "updated", "new"].map(v => <option key={v}>{v}</option>)}</select></label><Link href={`/activity?mode=${mode}`}>Reset</Link></Filters>
    <State {...data} retry={data.refresh}>{data.data && <section className="ops-card">{data.data.items.length ? <Table label="System activity" headers={["Event", "Type", "Source", "Status", "Recorded (UTC)", "Inspect"]}>{data.data.items.map(row => <tr key={`${row.kind}-${row.id}`}><td className="record-title">{row.summary.replaceAll("_", " ")}</td><td>{row.kind}</td><td>{row.source}</td><td><Status value={row.status}/></td><td>{date(row.at)}</td><td>{row.kind === "system" ? <span className="muted">Audit event</span> : <Link href={href(row)}>Inspect →</Link>}</td></tr>)}</Table> : <Empty>No recorded events match these filters.</Empty>}<Pager data={data.data} onPage={p => update({ page: String(p) })}/></section>}</State></>;
}
