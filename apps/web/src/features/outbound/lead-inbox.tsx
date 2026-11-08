"use client";
import { useCallback, useEffect, useState } from "react";
import { callRequest } from "./api";
import { isOutboundCall, type OutboundCall } from "./contracts";
type Lead = { call: OutboundCall; assessment: { disposition: string; summary: string; next_step: string; follow_up_permission: boolean } };
function isLead(value: unknown): value is Lead {
  if (!value || typeof value !== "object" || !("call" in value) || !isOutboundCall(value.call) || !("assessment" in value) || !value.assessment || typeof value.assessment !== "object") return false;
  const a = value.assessment as Record<string, unknown>;
  return typeof a.disposition === "string" && typeof a.summary === "string" && typeof a.next_step === "string" && typeof a.follow_up_permission === "boolean";
}
export function LeadInbox({ onSelect }: { onSelect: (call: OutboundCall) => void }) {
  const [rows, setRows] = useState<Lead[]>([]);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("follow_up");
  const [busy, setBusy] = useState(false);
  const refresh = useCallback(async (signal?: AbortSignal) => {
    setBusy(true);
    try {
      const data = await callRequest("leads", "GET", undefined, undefined, signal);
      if (!Array.isArray(data) || !data.every(isLead)) throw new Error("Lead assessments are unavailable.");
      if (!signal?.aborted) { setRows(data); setError(""); }
    } catch (e) { if (!signal?.aborted) setError(e instanceof Error ? e.message : "Lead assessments are unavailable."); }
    finally { if (!signal?.aborted) setBusy(false); }
  }, []);
  useEffect(() => { const controller = new AbortController(); void refresh(controller.signal); return () => controller.abort(); }, [refresh]);
  return <section className="ops-card" aria-busy={busy}><h2>Qualified call results</h2><p>Latest 100 retained assessments. Review the transcript and permission before further contact.</p><div className="actions"><label>Show<select value={filter} onChange={e => setFilter(e.target.value)}>{["follow_up", "nurture", "insufficient", "not_interested", "do_not_contact", "demonstration", "all"].map(v => <option key={v} value={v}>{v.replaceAll("_", " ")}</option>)}</select></label><button disabled={busy} onClick={() => void refresh()}>Refresh leads</button></div>{error && <p role="alert">{error}</p>}
    {rows.filter(row => filter === "all" || row.assessment.disposition === filter).map(row => <article key={row.call.id}><h3>{row.assessment.disposition.replaceAll("_", " ")}</h3><p>{row.assessment.summary}</p><p>{row.assessment.next_step}</p><button onClick={() => onSelect(row.call)}>Review call &amp; transcript</button></article>)}
    {!rows.some(row => filter === "all" || row.assessment.disposition === filter) && <p>No retained assessments in this category.</p>}
  </section>;
}
