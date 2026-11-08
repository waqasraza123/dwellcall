"use client";
import { useEffect, useState } from "react";
import { callRequest } from "./api";

type Assessment = { disposition: string; summary: string; needs: string[]; timing: string | null; crm: string | null; follow_up_permission: boolean; permission_quote: string | null; evidence_quotes: string[]; unanswered_questions: string[]; next_step: string };
type Intelligence = { status: string; transcript: { role: "agent" | "user"; text: string }[]; assessment: Assessment | null; expires_at?: string; model?: string };
function isIntelligence(value: unknown): value is Intelligence {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  if (typeof v.status !== "string" || !Array.isArray(v.transcript) || !v.transcript.every(t => t && typeof t === "object" && ["user", "agent"].includes(t.role) && typeof t.text === "string")) return false;
  if (v.assessment === null) return true;
  if (!v.assessment || typeof v.assessment !== "object") return false;
  const a = v.assessment as Record<string, unknown>;
  return ["disposition", "summary", "next_step"].every(k => typeof a[k] === "string") && typeof a.follow_up_permission === "boolean" && ["needs", "evidence_quotes", "unanswered_questions"].every(k => Array.isArray(a[k]) && a[k].every((s: unknown) => typeof s === "string"));
}
export function CallIntelligencePanel({ callId, terminal }: { callId: string; terminal: boolean }) {
  const [data, setData] = useState<Intelligence | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void callRequest(`calls/${callId}/intelligence`, "GET", undefined, undefined, controller.signal).then(v => { if (!isIntelligence(v)) throw new Error("Call intelligence is unavailable."); if (!controller.signal.aborted) setData(v); }).catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Call intelligence is unavailable."); });
    return () => controller.abort();
  }, [callId, terminal]);
  async function load(analyze: boolean) {
    setBusy(true); setError("");
    try {
      const result = await callRequest(`calls/${callId}/${analyze ? "analyze" : "intelligence"}`, analyze ? "POST" : "GET", analyze ? {} : undefined);
      if (!isIntelligence(result)) throw new Error("Call intelligence is unavailable.");
      setData(result);
    } catch (e) { setError(e instanceof Error ? e.message : "Call intelligence is unavailable."); }
    finally { setBusy(false); }
  }
  const assessment = data?.assessment;
  return <section className="ops-card" aria-busy={busy}><h2>Transcript &amp; lead qualification</h2><p>Analysis: {data?.status.replaceAll("_", " ") ?? "Loading…"}. Suggestions require operator review before further contact.</p>{error && <p role="alert">{error}</p>}
    {assessment && <><h3>{assessment.disposition.replaceAll("_", " ")}</h3><p>{assessment.summary}</p><dl className="facts"><div><dt>Follow-up permission</dt><dd>{assessment.follow_up_permission ? "Expressed in this call; review evidence" : "Not established"}</dd></div><div><dt>Timing</dt><dd>{assessment.timing ?? "Unknown"}</dd></div><div><dt>CRM</dt><dd>{assessment.crm ?? "Unknown"}</dd></div></dl><p>{assessment.next_step}</p>{assessment.permission_quote && <blockquote>{assessment.permission_quote}</blockquote>}{assessment.needs.length > 0 && <><h4>Needs</h4><ul>{assessment.needs.map((s,i) => <li key={i}>{s}</li>)}</ul></>}{assessment.evidence_quotes.map((s,i) => <blockquote key={i}>{s}</blockquote>)}{assessment.unanswered_questions.length > 0 && <><h4>Questions for the next conversation</h4><ul>{assessment.unanswered_questions.map((s,i) => <li key={i}>{s}</li>)}</ul></>}</>}
    <div className="actions"><button disabled={busy} onClick={() => void load(false)}>Refresh analysis</button>{data && ["pending", "failed", "processing"].includes(data.status) && <button disabled={busy || !terminal} onClick={() => void load(true)}>Analyze retained transcript</button>}</div>
    {data?.transcript.length ? <details><summary>Read transcript</summary>{data.transcript.map((turn,i) => <p key={i}><strong>{turn.role === "agent" ? "DwellCall" : "Recipient"}:</strong> {turn.text}</p>)}</details> : <p>No retained transcript is available.</p>}
    {data?.expires_at && <p className="muted">Transcript access expires {new Date(data.expires_at).toLocaleDateString()}.</p>}
  </section>;
}
