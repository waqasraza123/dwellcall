"use client";
import { useCallback, useEffect, useState } from "react";
import { isOutboundCall, type OutboundCall } from "./contracts";
import { leadReviewRequest } from "./review-api";
import { isLeadReview, type LeadReview } from "./review-contracts";
type Task = { call: OutboundCall; review: LeadReview };
function isTask(value: unknown): value is Task {
  return !!value && typeof value === "object" && "call" in value && isOutboundCall(value.call) && "review" in value && isLeadReview(value.review) && value.call.id === value.review.call_id;
}
export function LeadTaskInbox({ onSelect }: { onSelect: (call: OutboundCall) => void }) {
  const [status, setStatus] = useState("open");
  const [rows, setRows] = useState<Task[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const refresh = useCallback(async (signal?: AbortSignal) => {
    setBusy(true);
    try {
      const value = await leadReviewRequest(`tasks?status=${status}`, undefined, signal);
      if (!Array.isArray(value) || !value.every(isTask)) throw new Error("The task list could not be loaded.");
      if (!signal?.aborted) { setRows(value); setError(""); }
    } catch (e) { if (!signal?.aborted) { setRows([]); setError(e instanceof Error ? e.message : "The task list is unavailable."); } }
    finally { if (!signal?.aborted) setBusy(false); }
  }, [status]);
  useEffect(() => { const controller = new AbortController(); void refresh(controller.signal); return () => controller.abort(); }, [refresh]);
  return <section className="ops-card" aria-busy={busy}><h2>Follow-up tasks</h2><p>Local reminders for deliberate action. Scheduling a task does not place a call or write to a CRM. Up to 100 tasks, ordered by due date.</p><div className="actions"><label>Show<select value={status} onChange={e => { setStatus(e.target.value); setRows([]); }}>{["open", "deferred", "completed", "cancelled"].map(v => <option key={v} value={v}>{v}</option>)}</select></label><button disabled={busy} onClick={() => void refresh()}>Refresh tasks</button></div>{error && <p role="alert">{error}</p>}
    {rows.map(({ call, review }) => <article key={call.id}><h3>{review.status} · {review.task_status}</h3><p>{review.due_at ? `Due ${new Date(review.due_at).toLocaleString()}` : "No due date"}{review.task_status === "open" && !review.task_actionable ? " · blocked by current evidence or recipient restrictions" : ""}</p>{review.outcome && <p>{review.outcome.replaceAll("_", " ")}</p>}<button onClick={() => onSelect(call)}>Open lead review</button></article>)}
    {!rows.length && !busy && !error && <p>No tasks in this view.</p>}
  </section>;
}
