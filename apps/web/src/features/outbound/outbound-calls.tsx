"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ConfirmActionDialog, type ConfirmAction } from "@/components/confirm-dialog";
import { date, Status, Table } from "@/features/intelligence/ui";
import { CallApiError, callRequest, pendingRequest, recoverCall, requestCall, unresolvedCall, STORAGE_KEY } from "./api";
import { isAvailability, isOutboundCall, scenarios, type Availability, type OutboundCall, type Scenario } from "./contracts";

import { LeadTaskInbox } from "./lead-task-inbox";
import { LeadInbox } from "./lead-inbox";
import { CallIntelligencePanel } from "./intelligence-panel";

export function OutboundCalls() {
  const [availability, setAvailability] = useState<Availability | null>(null);
  const [history, setHistory] = useState<OutboundCall[]>([]);
  const [call, setCall] = useState<OutboundCall | null>(null);
  const [phone, setPhone] = useState("");
  const [scenario, setScenario] = useState<Scenario>("renting");
  const [consent, setConsent] = useState(false);
  const [dnc, setDnc] = useState(false);
  const [ready, setReady] = useState(false);
  const [locked, setLocked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [now, setNow] = useState(0);
  const [bindId, setBindId] = useState("");
  const [confirmation, setConfirmation] = useState<{ action: ConfirmAction; task: () => Promise<void> } | null>(null);
  const requestId = useRef<string | null>(null);
  const submitting = useRef(false);
  const reading = useRef(false);
  const mutationVersion = useRef(0);
  const availabilityVersion = useRef(0);

  const refreshWorkspace = useCallback(async () => {
    const version = ++availabilityVersion.current;
    const [available, rows] = await Promise.all([callRequest("availability"), callRequest("calls")]);
    if (!isAvailability(available) || !Array.isArray(rows) || !rows.every(isOutboundCall)) throw new Error("Calling status is unavailable. Recover your request before calling again.");
    if (version === availabilityVersion.current) {
      const unresolved = unresolvedCall(rows);
      if (!requestId.current && unresolved) {
        setLocked(true);
        try {
          sessionStorage.setItem(STORAGE_KEY, unresolved.request_id);
          requestId.current = unresolved.request_id;
          setCall(unresolved);
        } catch { setReady(false); throw new Error("Recovery storage is unavailable. Calling is blocked; inspect history."); }
      }
      setAvailability(available); setHistory(rows);
    }
  }, []);
  const checkStatus = useCallback(async (signal?: AbortSignal) => {
    const id = requestId.current;
    if (!id || submitting.current || reading.current) return;
    const version = mutationVersion.current;
    reading.current = true;
    try {
      const result = await recoverCall(id, signal);
      if (!signal?.aborted && requestId.current === id && version === mutationVersion.current) {
        setCall(result); setError("");
        setHistory(rows => rows.some(row => row.id === result.id) ? rows.map(row => row.id === result.id ? result : row) : [result, ...rows].slice(0, 25));
      }
    } catch (e) {
      if (!signal?.aborted) setError(e instanceof Error ? e.message : "Status is unavailable. Do not submit another call.");
    } finally { reading.current = false; }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    try {
      requestId.current = pendingRequest(sessionStorage);
      setLocked(requestId.current !== null); setReady(true);
      void checkStatus(controller.signal);
    } catch (e) { setLocked(true); setError(e instanceof Error ? e.message : "Recovery storage is unavailable. Calling is blocked."); }
    void refreshWorkspace().catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Calling is unavailable."); });
    return () => { controller.abort(); availabilityVersion.current += 1; };
  }, [checkStatus, refreshWorkspace]);
  useEffect(() => {
    if (!locked || call?.terminal) return;
    const controller = new AbortController();
    const timer = setInterval(() => void checkStatus(controller.signal), 5000);
    return () => { clearInterval(timer); controller.abort(); };
  }, [locked, call?.terminal, checkStatus]);
  useEffect(() => {
    if (!call?.started_at || call.terminal) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [call?.started_at, call?.terminal]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current || locked || !ready || !availability?.available || !consent || !dnc) return;
    submitting.current = true; setBusy(true); setError(""); setMessage("");
    mutationVersion.current += 1;
    const id = crypto.randomUUID();
    let accepted = false;
    try {
      sessionStorage.setItem(STORAGE_KEY, id);
      requestId.current = id; setLocked(true);
      const result = await requestCall(id, phone, scenario);
      accepted = true;
      setCall(result); setPhone("");
      await refreshWorkspace();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The connection was interrupted. Recover this request before calling again.");
      if (!accepted && e instanceof CallApiError && ["VALIDATION_FAILED", "OUTBOUND_DESTINATION_UNSUPPORTED", "OUTBOUND_RECIPIENT_NOT_APPROVED", "OUTBOUND_RECIPIENT_SUPPRESSED", "OUTBOUND_CALL_LOOP", "OUTBOUND_CALL_LIMIT", "AUDIO_SESSION_LIMIT"].includes(e.code)) {
        sessionStorage.removeItem(STORAGE_KEY); requestId.current = null; setLocked(false); setConsent(false); setDnc(false);
      }
    } finally { submitting.current = false; setBusy(false); }
  }
  async function act(task: () => Promise<void>) {
    if (submitting.current) return;
    submitting.current = true; setBusy(true); setError(""); setMessage("");
    mutationVersion.current += 1;
    try { await task(); await refreshWorkspace(); } catch (e) { setError(e instanceof Error ? e.message : "The operation is unconfirmed. Check status."); }
    finally { submitting.current = false; setBusy(false); setConfirmation(null); }
  }
  function confirm(title: string, description: string, label: string, task: () => Promise<void>) {
    setConfirmation({ action: { title, description, label, path: title }, task });
  }
  async function callAction(action: string, body: unknown = {}) {
    if (!call) return;
    const result = await callRequest(`calls/${call.id}/${action}`, "POST", body);
    if (!isOutboundCall(result) || result.id !== call.id) throw new Error("The call result is unconfirmed. Recover the saved request.");
    setCall(result);
  }
  function selectCall(row: OutboundCall) {
    if (busy || (requestId.current && !call?.terminal && row.request_id !== requestId.current)) return;
    try { sessionStorage.setItem(STORAGE_KEY, row.request_id); requestId.current = row.request_id; setCall(row); setLocked(true); setReady(true); setError(""); }
    catch { setError("Recovery storage is unavailable. Calling is blocked."); setReady(false); }
  }
  const elapsed = call?.started_at && !call.terminal ? Math.max(0, Math.floor(((now || Date.now()) - Date.parse(call.started_at)) / 1000)) : call?.duration_seconds ?? null;

  return <>
    <div className="section-heading"><div><p className="eyebrow">PRIVATE DEMONSTRATION</p><h1>Outbound AI Calls</h1><p>Requested AI conversations through {availability?.provider === "retell" ? "Retell" : "ElevenLabs"} and Telnyx, with optional transcript qualification.</p></div><button disabled={busy} onClick={() => void act(async () => {})}>Refresh history</button></div>
    <p className="notice">{availability?.mock ? "SIMULATION MODE — no telephone calls or paid provider requests." : availability?.available ? `Calling enabled for approved recipients in ${availability.countries.join(", ")}. Up to ${availability.max_duration_seconds} seconds and ${availability.daily_limit} attempts per UTC day.` : "Telephone calling is disabled. Configure the private demonstration before activation."} Listing discovery never initiates calls.</p>
    {error && <p role="alert" className="notice error">{error}</p>}{message && <p role="status" className="notice success">{message}</p>}
    <div className="detail-grid"><section className="ops-card"><h2>Request one call</h2><form onSubmit={submit} aria-busy={busy}>
      <div className="form-grid"><label>Scenario<select value={scenario} disabled={locked || busy} onChange={e => setScenario(e.target.value as Scenario)}>{Object.entries(scenarios).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label>Approved recipient<input type="tel" autoComplete="off" placeholder="Include + and country code" value={phone} onChange={e => setPhone(e.target.value)} maxLength={64} required disabled={locked || busy}/></label></div>
      <label className="call-consent"><input type="checkbox" required checked={consent} disabled={locked || busy} onChange={e => setConsent(e.target.checked)}/><span>I confirm this recipient controls the number and explicitly agreed to one DwellCall AI property demonstration via the configured voice provider and Telnyx. When call intelligence is enabled, the transcript is retained securely and analyzed by OpenAI for platform interest and possible follow-up. No audio recording, marketing or automatic redial. I have permission to request it on their behalf.</span></label>
      <label className="call-consent"><input type="checkbox" required checked={dnc} disabled={locked || busy} onChange={e => setDnc(e.target.checked)}/><span>I checked applicable do-not-call restrictions and the recipient has not withdrawn permission.</span></label>
      <button type="submit" className="primary" disabled={!ready || !availability?.available || !consent || !dnc || locked || busy}>{busy ? "Please wait…" : locked ? "Call already requested" : availability?.mock ? "Simulate Call" : "Start Call"}</button>
    </form></section>
    <section className="ops-card" aria-live="polite"><h2>Call progress</h2>{call ? <><Status value={call.status}/><p>{call.message}</p><dl className="facts"><div><dt>Request</dt><dd><code>{call.request_id}</code></dd></div><div><dt>Provider receipt</dt><dd><code>{call.provider_call_id ?? "Awaiting verified receipt"}</code></dd></div><div><dt>Created (UTC)</dt><dd>{date(call.created_at)}</dd></div><div><dt>Duration</dt><dd>{elapsed === null ? "Not confirmed" : `${elapsed}s${!call.terminal ? " elapsed · awaiting final evidence" : " reported by provider"}`}</dd></div><div><dt>Human transfer</dt><dd>{call.transfer_status.replaceAll("_", " ")}</dd></div><div><dt>Final outcome</dt><dd>{call.terminal ? call.status : "Awaiting final evidence"}</dd></div></dl></> : <p>{locked ? "Recovering the saved request. Do not request another call." : "No call requested in this session."}</p>}
      {locked && <button disabled={busy} onClick={() => void checkStatus()}>Check saved request</button>}
      {call && <div className="actions"><button disabled={busy} onClick={() => void act(() => callAction("refresh"))}>Reconcile provider status</button>{!call.terminal && <button disabled={busy} onClick={() => confirm("Stop this call?", "Request call termination. For ElevenLabs, end the active SIP call in Telnyx and reconcile it here. Carrier transfer legs require separate confirmation before releasing the reservation.", "Request stop", () => callAction("stop"))}>Stop call</button>}</div>}
      {call?.terminal && <button disabled={busy} onClick={() => confirm("Prepare a new request?", "The previous call is final. Daily, recipient, cooldown and spending limits still apply. Fresh recipient permission is required.", "Prepare form", async () => { sessionStorage.removeItem(STORAGE_KEY); requestId.current = null; setCall(null); setLocked(false); setConsent(false); setDnc(false); })}>Prepare another call</button>}
    </section></div>
    {call && <CallIntelligencePanel key={call.id} callId={call.id} terminal={call.terminal}/>}
    <section className="ops-card"><h2>Operator controls</h2><p className="muted">Human transfers are permanently unavailable. DwellCall is operated only by AI agents.</p><div className="actions">
      <button disabled={busy || !availability} onClick={() => void act(async () => { const result = await callRequest("preflight", "POST", {}); setMessage(result && typeof result === "object" && "mock" in result && result.mock ? "Mock configuration is ready. No provider request was made." : "Voice provider configuration preflight passed. A real call has not been tested."); })}>Check provider configuration</button>
      <button disabled={busy || !availability} onClick={() => confirm("Pause new calling?", "Block new requests and further AI turns. Use Stop call for an active call and verify carrier legs separately.", "Pause calling", async () => { await callRequest("controls", "POST", { calls_paused: true, transfers_paused: true }); })}>Emergency pause</button>
      <button disabled={busy || !availability?.calls_paused} onClick={() => confirm("Resume authorized calling?", "Backend activation, consent, allowlist and all quotas remain required. Human transfers are permanently unavailable.", "Resume calling", async () => { await callRequest("controls", "POST", { calls_paused: false, transfers_paused: true }); })}>Resume calling</button>
    </div>
    {call && !call.terminal && <details><summary>Recover an uncertain call</summary><p>Lookup and binding only attach a verified existing provider call. An empty lookup never authorizes redial.</p><label>Existing provider call ID<input value={bindId} maxLength={200} onChange={e => setBindId(e.target.value)} pattern="[A-Za-z0-9_-]+"/></label><button disabled={busy || !/^[A-Za-z0-9_-]{1,200}$/.test(bindId)} onClick={() => void act(() => callAction("bind", { provider_call_id: bindId }))}>Verify and bind receipt</button><button disabled={busy} onClick={() => confirm("Confirm every carrier leg ended?", "Check the voice provider and Telnyx records first, including every transferred leg. This records your confirmation and releases the unresolved reservation. Transfer initiation does not establish that a human answered.", "I verified all carrier legs ended", () => callAction("carrier-ended", { all_carrier_legs_ended: true }))}>Confirm carrier completion</button></details>}
    <details><summary>Suppress a recipient</summary><form onSubmit={e => { e.preventDefault(); const number = String(new FormData(e.currentTarget).get("number") ?? ""); confirm("Suppress this number?", "Block future calls to this recipient. This does not stop a call already in progress.", "Suppress recipient", async () => { await callRequest("suppress", "POST", { phone_number: number }); setMessage("The recipient is suppressed."); }); }}><label>Phone number<input type="tel" name="number" required maxLength={64} autoComplete="off"/></label><button disabled={busy}>Suppress number</button></form></details></section>
    <LeadTaskInbox onSelect={selectCall}/>
    <LeadInbox onSelect={selectCall}/>
    <section className="ops-card"><h2>Recent calls</h2>{history.length ? <Table label="Outbound call history" headers={["Created (UTC)", "Scenario", "Status", "Transfer", "Action"]}>{history.map(row => <tr key={row.id}><td>{date(row.created_at)}{row.mock && <small>Simulation</small>}</td><td>{row.scenario}</td><td><Status value={row.status}/></td><td>{row.transfer_status.replaceAll("_", " ")}</td><td><button disabled={busy || (!!requestId.current && !call?.terminal && row.request_id !== requestId.current)} onClick={() => selectCall(row)}>Open request</button></td></tr>)}</Table> : <p>No call requests recorded.</p>}</section>
    {confirmation && <ConfirmActionDialog action={confirmation.action} busy={busy} onClose={() => setConfirmation(null)} onConfirm={() => void act(confirmation.task)}/>}
  </>;
}
