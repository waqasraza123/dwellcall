"use client";
import { useEffect, useRef, useState } from "react";
import { CallApiError } from "./api";
import { applyLeadReview, loadLeadReview } from "./review-api";
import { isReviewMutation, taskOutcomes, type LeadReview, type ReviewAction, type ReviewMutation, type TaskOutcome } from "./review-contracts";

export function LeadReviewPanel({ callId }: { callId: string }) {
  const [review, setReview] = useState<LeadReview | null>(null);
  const [pending, setPending] = useState<ReviewMutation | null>(null);
  const [ready, setReady] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [due, setDue] = useState("");
  const [outcome, setOutcome] = useState<TaskOutcome>("contacted");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const submitting = useRef(false);
  const key = `dwellcall-lead-review-${callId}`;
  useEffect(() => {
    const controller = new AbortController();
    try {
      const saved = sessionStorage.getItem(key);
      if (saved !== null) {
        const parsed: unknown = JSON.parse(saved);
        if (!isReviewMutation(parsed)) throw new Error("The saved action is invalid. Inspect the action history before clearing recovery storage.");
        setPending(parsed);
      }
      setReady(true);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Recovery storage is unavailable."); }
    void loadLeadReview(callId, controller.signal).then(value => { if (!controller.signal.aborted) setReview(value); }).catch(error => { if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : "Review is unavailable."); });
    return () => controller.abort();
  }, [callId, key]);
  function clearPending() {
    sessionStorage.removeItem(key);
    setPending(null);
  }
  async function refresh() {
    if (submitting.current) return;
    setBusy(true);
    try {
      const value = await loadLeadReview(callId);
      setReview(value);
      if (pending && value.recent_events.some(e => e.request_id === pending.request_id)) {
        clearPending(); setConfirmed(false); setMessage("The saved action was recorded.");
      } else setMessage(pending ? "Retry the saved action to resolve its outcome before submitting another." : "Review refreshed.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Review is unavailable."); }
    finally { setBusy(false); }
  }
  async function act(action?: ReviewAction) {
    if (submitting.current || !ready || !review || (pending && action)) return;
    submitting.current = true; setBusy(true); setMessage("");
    let mutation = pending;
    try {
      if (!mutation) {
        if (!action) return;
        const dueAt = (action === "schedule" || action === "defer") && due ? new Date(due).toISOString() : null;
        mutation = { request_id: crypto.randomUUID(), expected_version: review.version, action, evidence_reviewed: confirmed, due_at: dueAt, outcome: action === "complete" ? outcome : null };
        sessionStorage.setItem(key, JSON.stringify(mutation));
        setPending(mutation);
      }
      const result = await applyLeadReview(callId, mutation);
      setReview(result); clearPending(); setConfirmed(false); setDue("");
      setMessage("Action recorded. The follow-up task is local; no contact was initiated.");
    } catch (error) {
      if (error instanceof CallApiError && ["LEAD_REVIEW_CHANGED", "LEAD_REVIEW_INELIGIBLE", "LEAD_REVIEW_DUE_INVALID", "LEAD_REVIEW_EVIDENCE_EXPIRY", "LEAD_REVIEW_REQUIRED", "LEAD_TASK_OPEN", "LEAD_TASK_NOT_OPEN", "LEAD_REVIEW_KEY_CONFLICT", "VALIDATION_FAILED"].includes(error.code)) {
        try { clearPending(); } catch { setReady(false); }
      }
      setMessage(error instanceof Error ? error.message : "The action is unconfirmed. Retry the saved action.");
    } finally { submitting.current = false; setBusy(false); }
  }
  const disabled = busy || !!pending || !ready || !review;
  return <div className="lead-review-panel" aria-busy={busy}><h3>Review &amp; next action</h3>
    <p>Decision: {review?.status ?? "Loading…"}. Task: {review?.task_status ?? "Loading…"}.</p>
    {review?.blockers.length ? <ul>{review.blockers.map(text => <li key={text}>{text}</li>)}</ul> : null}
    {review?.due_at && <p>Due: {new Date(review.due_at).toLocaleString()}{new Date(review.due_at).getTime() < Date.now() && review.task_status === "open" ? " · overdue" : ""}.</p>}
    {review?.outcome && <p>Recorded outcome: {review.outcome.replaceAll("_", " ")}.</p>}
    {review?.task_status === "open" && !review.task_actionable && <p>This task is blocked. Review current evidence and recipient restrictions before further contact.</p>}
    <label className="call-consent"><input type="checkbox" checked={confirmed} disabled={disabled} onChange={e => setConfirmed(e.target.checked)}/><span>I reviewed the transcript and confirm the recipient expressed relevant interest and explicit permission for a further conversation.</span></label>
    <div className="actions"><button disabled={disabled || !confirmed || !review?.eligible || review?.task_status === "open"} onClick={() => void act("approve")}>Approve lead</button><button disabled={disabled} onClick={() => void act("reject")}>Reject lead</button></div>
    <label>Due date (your local time)<input type="datetime-local" value={due} disabled={disabled} onChange={e => setDue(e.target.value)}/></label>
    <div className="actions"><button disabled={disabled} onClick={() => void act("defer")}>Defer review</button><button disabled={disabled || !due || !confirmed || !review?.eligible || review?.status !== "approved" || review.task_status !== "none"} onClick={() => void act("schedule")}>Schedule local follow-up task</button></div>
    {review?.task_status === "open" && <><label>Outcome already observed<select value={outcome} disabled={disabled} onChange={e => setOutcome(e.target.value as TaskOutcome)}>{taskOutcomes.map(v => <option key={v} value={v}>{v.replaceAll("_", " ")}</option>)}</select></label><div className="actions"><button disabled={disabled} onClick={() => void act("complete")}>Record task completion</button><button disabled={disabled} onClick={() => void act("cancel")}>Cancel task</button></div></>}
    <div className="actions"><button disabled={busy} onClick={() => void refresh()}>Refresh review</button>{pending && <button disabled={busy || !ready} onClick={() => void act()}>Retry saved action</button>}</div>
    {message && <p role="status">{message}</p>}
    <details><summary>Recent action history</summary>{review?.recent_events.length ? <ol>{review.recent_events.map(e => <li key={e.request_id}>{e.action} · {new Date(e.occurred_at).toLocaleString()} · version {e.version}</li>)}</ol> : <p>No review action recorded.</p>}</details>
  </div>;
}
