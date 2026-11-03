"use client";
import { useRef, useState, type FormEvent, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ConfirmActionDialog, type ConfirmAction } from "@/components/confirm-dialog";
import { clearPendingActions } from "./api";
import type { Mode, Page, Property } from "./contracts";

export function useWorkspace() {
  const search = useSearchParams(); const router = useRouter(); const pathname = usePathname();
  const mode: Mode = search.get("mode") === "live" ? "live" : "synthetic";
  const parsedPage = Number(search.get("page"));
  const page = Number.isSafeInteger(parsedPage) && parsedPage > 0 ? parsedPage : 1;
  function update(values: Record<string, string | null>) { const next = new URLSearchParams(search.toString()); for (const [key, value] of Object.entries(values)) if (value) next.set(key, value); else next.delete(key); if (!("page" in values)) next.delete("page"); router.push(`${pathname}?${next.toString()}`, { scroll: false }); }
  return { search, mode, page, update };
}
export function useAction(onSuccess?: () => void) {
  const lock = useRef(false); const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [message, setMessage] = useState("");
  const [confirmation, setConfirmation] = useState<{ action: ConfirmAction; task: () => Promise<unknown> } | null>(null);
  async function act(task: () => Promise<unknown>, success = "Saved. The latest state is shown below.") {
    if (lock.current) return; lock.current = true; setBusy(true); setError(""); setMessage("");
    try { await task(); setMessage(success); setConfirmation(null); onSuccess?.(); } catch (e) { setError(e instanceof Error ? e.message : "The action could not be completed."); setConfirmation(null); } finally { lock.current = false; setBusy(false); }
  }
  const feedback = <>{error && <div role="alert" className="notice error"><p>{error}</p><button type="button" disabled={busy} onClick={() => setConfirmation({ action: { title: "Allow a new attempt?", description: "First refresh and inspect discovery or CRM history. The earlier action may have completed. Continuing clears this browser’s pending request IDs so your next deliberate submission can use a new ID.", label: "I checked history · allow a new attempt", path: "reset" }, task: async () => { clearPendingActions(); setError(""); } })}>Recover a pending action</button></div>}{message && <p role="status" className="notice success">{message}</p>}{confirmation && <ConfirmActionDialog action={confirmation.action} busy={busy} onClose={() => setConfirmation(null)} onConfirm={() => void act(confirmation.task)} />}</>;
  function confirm(title: string, description: string, task: () => Promise<unknown>, label = "Confirm action") { setError(""); setConfirmation({ action: { title, description, label, path: title }, task }); }
  return { busy, act, confirm, feedback };
}
export function Status({ value }: { value: string | boolean | null | undefined }) {
  const text = typeof value === "boolean" ? value ? "enabled" : "disabled" : value ?? "unknown";
  const good = ["sent", "synced", "completed", "verified", "approved", "active", "enabled", "eligible"].includes(text);
  const bad = ["failed", "suppressed", "rejected", "unknown"].includes(text);
  return <span className={`badge ${good ? "good" : bad ? "bad" : "neutral"}`}>{text.replaceAll("_", " ")}</span>;
}
export function State({ loading, error, children, retry }: { loading?: boolean; error?: string; children?: ReactNode; retry?: () => void }) {
  if (loading) return <div className="skeleton-group" role="status" aria-label="Loading workspace"><span className="sr-only">Loading…</span>{[1, 2, 3, 4].map(n => <div className="skeleton" key={n}/>)}</div>;
  if (error) return <div role="alert" className="notice error"><h3>This view is unavailable</h3><p>{error}</p>{retry && <button onClick={retry}>Try again</button>}<Link href="/login">Operator sign in</Link></div>;
  return children;
}
export function Empty({ children }: { children: ReactNode }) { return <div className="empty-state"><span className="empty-mark" aria-hidden="true">⌂</span><h3>No records to show</h3><p>{children}</p></div>; }
export function Pager({ data, onPage }: { data: Pick<Page<unknown>, "page" | "total" | "page_size">; onPage: (page: number) => void }) {
  const max = Math.max(1, Math.ceil(data.total / data.page_size));
  return <nav className="pager" aria-label="Result pages"><span>{data.total.toLocaleString()} records · Page {data.page} of {max}</span><div><button disabled={data.page <= 1} onClick={() => onPage(data.page - 1)}>Previous</button><button disabled={data.page >= max} onClick={() => onPage(data.page + 1)}>Next</button></div></nav>;
}
export function Table({ headers, children, label }: { headers: string[]; children: ReactNode; label: string }) { return <div className="table-scroll" role="region" aria-label={label} tabIndex={0}><table><caption className="sr-only">{label}</caption><thead><tr>{headers.map(h => <th scope="col" key={h}>{h}</th>)}</tr></thead><tbody>{children}</tbody></table></div>; }
export function Filters({ children, onSubmit }: { children: ReactNode; onSubmit: (form: FormData) => void }) {
  return <form className="filters" onSubmit={(e: FormEvent<HTMLFormElement>) => { e.preventDefault(); onSubmit(new FormData(e.currentTarget)); }}>{children}<button type="submit" className="primary">Apply filters</button></form>;
}
export function SafeLink({ href, children }: { href?: string | null; children: ReactNode }) {
  if (!href) return <span className="muted">Not supplied</span>;
  try { const url = new URL(href); if (!["https:", "http:"].includes(url.protocol) || url.username || url.password) return <span>Unavailable</span>; } catch { return <span>Unavailable</span>; }
  return <a href={href} target="_blank" rel="noopener noreferrer">{children}<span className="sr-only"> (opens in a new tab)</span> ↗</a>;
}
export function money(property: Property) { const value = property.price; if (value == null) return "Price not supplied"; if (!property.currency) return `${value} · currency not supplied`; try { return new Intl.NumberFormat("en-US", { style: "currency", currency: property.currency, maximumFractionDigits: 0 }).format(Number(value)); } catch { return `${value} ${property.currency ?? ""}`; } }
export function date(value?: string | null) { if (!value) return "Not recorded"; const d = new Date(value.length === 10 ? `${value}T00:00:00Z` : value); if (!Number.isFinite(d.getTime())) return "Not recorded"; return new Intl.DateTimeFormat("en-US", { dateStyle: "medium", ...(value.length > 10 ? { timeStyle: "short" as const } : {}), timeZone: "UTC" }).format(d); }
export function address(property: Property) { return [property.city, property.state, property.postal_code].filter(Boolean).join(", "); }
export const propertyTypes = ["single_family", "condo", "townhouse", "multifamily", "land", "other"];
export const listingStatuses = ["active", "pending", "sold", "removed", "unknown"];
export function Options({ values }: { values: string[] }) { return values.map(v => <option value={v} key={v}>{v.replaceAll("_", " ")}</option>); }
