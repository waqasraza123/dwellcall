"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import type { RetellWebClient } from "retell-client-js-sdk";
import { ConversationApiError, conversationRequest, conversationStatus } from "./api";
import { ChatComposer } from "./chat-composer";
import { isAvailability, isConversation, isGrant, REQUEST_KEY, UUID, type Availability, type Conversation, type Mode, type Scenario, type Turn } from "./contracts";
import styles from "./homepage-chat.module.css";

const scenarios: Record<Scenario, string> = { renting: "Renting", buying: "Buying", luxury: "Luxury" };
const suggestions = ["A rental with room for my dog", "Help me compare buying options", "What makes a home feel luxurious?"];

function ModeIcon({ mode }: { mode: Mode }) {
  return <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">{mode === "voice" ? <><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3m-4 0h8"/></> : <path d="M20 15a3 3 0 0 1-3 3H9l-5 3V6a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3Zm-12-7h8M8 12h5"/>}</svg>;
}

export function HomepageChat() {
  const [mode, setMode] = useState<Mode>("voice");
  const [scenario, setScenario] = useState<Scenario>("renting");
  const [availability, setAvailability] = useState<Availability | null>(null);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [savedId, setSavedId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [pendingMessage, setPendingMessage] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [voicePhase, setVoicePhase] = useState<"idle" | "connecting" | "active" | "ended">("idle");
  const [muted, setMuted] = useState(false);
  const [now, setNow] = useState(0);
  const activeId = useRef<string | null>(null);
  const stateToken = useRef<string | null>(null);
  const client = useRef<RetellWebClient | null>(null);
  const mounted = useRef(false);
  const sending = useRef(false);
  const ending = useRef(false);
  const reading = useRef(false);
  const messages = useRef<HTMLDivElement>(null);
  const epoch = useRef(0);
  const connectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const microphone = useRef<MediaStream | null>(null);

  const updateConversation = useCallback((value: Conversation) => {
    setConversation(value); setMode(value.mode); setScenario(value.scenario);
    if (value.status === "ended") { client.current?.removeAllListeners(); client.current?.stopCall(); client.current = null; setVoicePhase("ended"); }
  }, []);

  const recover = useCallback(async (signal?: AbortSignal) => {
    const id = activeId.current;
    if (!id || sending.current || reading.current) return;
    const version = epoch.current;
    reading.current = true;
    try {
      const value = await conversationStatus(id, signal);
      if (mounted.current && !signal?.aborted && activeId.current === id && version === epoch.current) updateConversation(value);
    } catch (failure) { if (mounted.current && !signal?.aborted) setError(failure instanceof Error ? failure.message : "Check this saved conversation before starting another."); }
    finally { reading.current = false; }
  }, [updateConversation]);

  const refreshAvailability = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await conversationRequest("", "GET", undefined, signal);
      if (!isAvailability(data)) throw new Error("Conversation availability could not be read.");
      if (mounted.current && !signal?.aborted) setAvailability(data);
    } catch (failure) { if (mounted.current && !signal?.aborted) setError(failure instanceof Error ? failure.message : "Conversations are unavailable."); }
  }, []);

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    try {
      const id = sessionStorage.getItem(REQUEST_KEY);
      if (id && !UUID.test(id)) throw new Error("The saved request is invalid. Ask the owner to inspect active conversations.");
      activeId.current = id; setSavedId(id); setReady(true);
      void refreshAvailability(controller.signal).then(() => recover(controller.signal));
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Recovery storage is unavailable. Conversation start is blocked."); }
    const focus = () => { if (!sending.current) { void refreshAvailability(controller.signal); void recover(controller.signal); } };
    window.addEventListener("focus", focus);
    return () => {
      mounted.current = false; controller.abort(); epoch.current += 1;
      window.removeEventListener("focus", focus);
      if (connectTimer.current) clearTimeout(connectTimer.current);
      client.current?.removeAllListeners(); client.current?.stopCall(); client.current = null;
      microphone.current?.getTracks().forEach(track => track.stop()); microphone.current = null;
    };
  }, [recover, refreshAvailability]);

  useEffect(() => {
    if (!savedId || conversation?.status === "ended") return;
    const controller = new AbortController();
    const interval = setInterval(() => void recover(controller.signal), 4000);
    return () => { clearInterval(interval); controller.abort(); };
  }, [savedId, conversation?.status, recover]);

  useEffect(() => {
    if (conversation?.status !== "active") return;
    setNow(Date.now());
    const interval = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, [conversation?.status]);

  useEffect(() => { if (messages.current) messages.current.scrollTop = messages.current.scrollHeight; }, [turns, pendingMessage]);

  async function endConversation() {
    const id = activeId.current;
    if (!id || ending.current) return;
    ending.current = true; epoch.current += 1;
    if (connectTimer.current) clearTimeout(connectTimer.current);
    client.current?.stopCall(); client.current?.removeAllListeners(); client.current = null;
    microphone.current?.getTracks().forEach(track => track.stop()); microphone.current = null;
    setVoicePhase("ended"); setMuted(false);
    try {
      const result = await conversationRequest(`sessions/${id}/end`, "POST", {});
      if (!isConversation(result) || result.id !== id) throw new Error("Completion is unconfirmed. Check the saved request.");
      if (mounted.current && activeId.current === id) updateConversation(result);
    } catch (failure) { if (mounted.current) setError(failure instanceof Error ? failure.message : "Completion is unconfirmed. Check status."); }
    finally { ending.current = false; }
  }

  const expired = conversation?.status === "active" && now > 0 && Date.parse(conversation.expires_at) <= now;
  useEffect(() => { if (expired) void endConversation(); }, [expired]);

  async function start() {
    if (sending.current || activeId.current || !ready || !availability?.authenticated || !availability[mode] || !consent) return;
    sending.current = true; setBusy(true); setError("");
    const version = ++epoch.current;
    let id: string | null = null;
    try {
      if (mode === "voice" && !availability.mock) {
        if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) throw new Error("Voice needs a secure HTTPS page and microphone support. You can use Text chat instead.");
        microphone.current = await navigator.mediaDevices.getUserMedia({ audio: true });
        microphone.current.getTracks().forEach(track => track.stop()); microphone.current = null;
        if (!mounted.current) return;
      }
      id = crypto.randomUUID();
      sessionStorage.setItem(REQUEST_KEY, id); activeId.current = id; setSavedId(id);
      const result = await conversationRequest("sessions", "POST", { request_id: id, mode, scenario, ai_consent: true, fictional_data_only: true });
      if (!mounted.current || activeId.current !== id || epoch.current !== version) return;
      if (!result || typeof result !== "object" || !("conversation" in result) || !isConversation(result.conversation) || result.conversation.id !== id || !("greeting" in result) || typeof result.greeting !== "string") throw new Error("The conversation receipt could not be confirmed. Check this saved request.");
      updateConversation(result.conversation); setTurns([{ role: "agent", content: result.greeting }]);
      if (mode === "text") {
        if (!("state_token" in result) || typeof result.state_token !== "string") throw new Error("The text session is unconfirmed. End it before starting another.");
        stateToken.current = result.state_token;
      } else if (result.conversation.mock) setVoicePhase("active");
      else {
        if (!("grant" in result) || !isGrant(result.grant)) throw new Error("Voice connection details are invalid. End this request before starting another.");
        const { RetellWebClient } = await import("retell-client-js-sdk");
        if (!mounted.current || activeId.current !== id || epoch.current !== version || ending.current) return;
        const current = new RetellWebClient({ defaultTransport: "gateway" });
        client.current = current; setVoicePhase("connecting");
        current.on("call_started", () => {
          if (client.current !== current || !mounted.current) return;
          if (connectTimer.current) clearTimeout(connectTimer.current);
          setVoicePhase("active");
        });
        current.on("call_ended", () => { if (client.current === current && mounted.current && !ending.current) void endConversation(); });
        current.on("error", () => {
          if (client.current !== current || !mounted.current) return;
          setError("Voice could not connect. Your microphone is being released; check session status before trying again.");
          void endConversation();
        });
        connectTimer.current = setTimeout(() => {
          if (client.current === current && mounted.current) { setError("The voice connection timed out. Check session status before trying again."); void endConversation(); }
        }, 20_000);
        await current.startCall({ accessToken: result.grant.access_token, transport: result.grant.transport, callId: result.grant.call_id, iceServers: result.grant.ice_servers });
      }
    } catch (failure) {
      if (mounted.current) {
        setError(failure instanceof Error ? failure.message : "The conversation could not start. Check microphone permissions and session status.");
        if (id && failure instanceof ConversationApiError && (["AUDIO_SESSION_LIMIT", "BROWSER_CONVERSATION_DISABLED", "BROWSER_CONVERSATIONS_PAUSED", "VALIDATION_FAILED"].includes(failure.code) || failure.status === 401)) {
          sessionStorage.removeItem(REQUEST_KEY); activeId.current = null; setSavedId(null);
        }
      }
    } finally { sending.current = false; if (mounted.current) setBusy(false); }
  }

  async function sendText() {
    const id = activeId.current, token = stateToken.current, message = draft.trim();
    if (sending.current || !id || !token || !message || conversation?.status !== "active") return;
    sending.current = true; setBusy(true); setError(""); setPendingMessage(message);
    const version = ++epoch.current;
    const transcript: Turn[] = [...turns, { role: "user", content: message }];
    try {
      const data = await conversationRequest(`sessions/${id}/turn`, "POST", { transcript, state_token: token });
      if (!mounted.current || activeId.current !== id || version !== epoch.current) return;
      if (!data || typeof data !== "object" || !("reply" in data) || typeof data.reply !== "string" || !data.reply.trim() || data.reply.length > 4000 || !("state_token" in data) || typeof data.state_token !== "string" || !("conversation" in data) || !isConversation(data.conversation) || data.conversation.id !== id) throw new Error("The reply is unconfirmed. End this session before starting another.");
      setTurns([...transcript, { role: "agent", content: data.reply }]);
      stateToken.current = data.state_token; updateConversation(data.conversation);
      setDraft(value => value.trim() === message ? "" : value);
    } catch (failure) {
      if (mounted.current) { stateToken.current = null; setError(failure instanceof Error ? failure.message : "The reply was interrupted. Your draft is kept."); }
    } finally { sending.current = false; if (mounted.current) { setBusy(false); setPendingMessage(""); } }
  }

  function reset() {
    if (conversation?.status !== "ended" || sending.current || ending.current) return;
    try {
      sessionStorage.removeItem(REQUEST_KEY); activeId.current = null; stateToken.current = null; epoch.current += 1;
      setSavedId(null); setConversation(null); setTurns([]); setConsent(false); setError(""); setVoicePhase("idle");
    } catch { setReady(false); setError("Recovery storage is unavailable. Conversation start is blocked."); }
  }

  const remaining = conversation ? Math.max(0, Math.ceil((Date.parse(conversation.expires_at) - (now || Date.now())) / 1000)) : availability?.max_seconds ?? 180;
  const timer = `${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, "0")}`;
  const locked = savedId !== null;
  const live = conversation?.status === "active" && (mode === "text" ? !!stateToken.current : voicePhase === "active");
  return <section id="try-dwellcall" className={styles.panel} aria-labelledby="consultant-title">
    <header className={styles.header}>
      <div className={styles.monogram} aria-hidden="true"><svg viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="1.3"><path d="m5 15 11-9 11 9v12H5ZM12 27v-9h8v9M16 6V3"/></svg></div>
      <div><p className={styles.eyebrow}>A PLACE TO BEGIN</p><h2 id="consultant-title">Your next chapter,<br/><em>talked through.</em></h2></div>
      <span className={styles.badge}><i data-live={live}/>{live ? "Connected" : availability?.mock ? "Simulation" : "AI consultant"}</span>
    </header>
    <div className={styles.controls}>
      <div className={styles.modes} role="group" aria-label="Conversation mode">{(["voice", "text"] as const).map(value => <button key={value} type="button" aria-pressed={mode === value} disabled={locked || busy} onClick={() => { setMode(value); setError(""); }}><ModeIcon mode={value}/>{value === "voice" ? "Voice chat" : "Text chat"}</button>)}</div>
      <label className="sr-only" htmlFor="consultation-scenario">Property scenario</label><select id="consultation-scenario" value={scenario} disabled={locked || busy} onChange={event => setScenario(event.target.value as Scenario)}>{Object.entries(scenarios).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
    </div>
    {mode === "voice" ? <div className={styles.voice}>
      <div className={styles.voiceArtwork} data-active={live} aria-hidden="true"><span/><span/><span/><div className={styles.wave}>{[1,2,3,4,5,6,7,8,9].map(value => <i key={value}/>)}</div><svg viewBox="0 0 280 150" fill="none"><path d="M20 142h240M55 142V73l50-32 50 32v69M105 41v101M155 142V89l35-20 35 20v53M105 88h24v54M68 90h20v18M171 99h16v16M199 99h13v16"/></svg></div>
      <p className={styles.eyebrow}>{availability?.mock ? "SIMULATED SESSION · NO MICROPHONE" : "LESS SEARCHING. MORE UNDERSTANDING."}</p>
      <h3>{voicePhase === "connecting" ? "Making the connection…" : live ? "Tell us what home means to you." : conversation?.status === "ended" ? "A little closer to home." : <>A home starts<br/>with a conversation.</>}</h3>
      <p>{live ? availability?.mock ? "A synthetic voice session is active. No audio or paid services are connected." : "You're speaking with DwellCall's AI. Explore your preferences at your own pace." : "Talk through your budget, compare possibilities, and find what matters to you."}</p>
      {live && <div className={styles.liveControls}><span className={styles.timer} aria-label={`${remaining} seconds remaining`}>{timer}</span>{!conversation?.mock && <><button onClick={() => { if (muted) client.current?.unmute(); else client.current?.mute(); setMuted(!muted); }} aria-pressed={muted}>{muted ? "Unmute" : "Mute mic"}</button><button onClick={() => void client.current?.startAudioPlayback()}>Enable sound</button></>}</div>}
    </div> : <div className={styles.text}>
      <div ref={messages} role="log" aria-live="polite" aria-relevant="additions text" aria-label="Property conversation" className={styles.messages}>
        {(turns.length ? turns : [{ role: "agent", content: "Hi, I'm DwellCall's AI property consultant. Looking to rent, buy, or explore something exceptional? Let's start with what matters to you." } satisfies Turn]).map((turn, index) => <div key={index} className={turn.role === "agent" ? styles.agentMessage : styles.userMessage}><span>{turn.role === "agent" ? "DWELLCALL" : "YOU"}</span><p>{turn.content}</p></div>)}
        {pendingMessage && <><div className={styles.userMessage}><span>YOU</span><p>{pendingMessage}</p></div><div className={styles.thinking} role="status"><i/><i/><i/><span>Considering your preferences…</span></div></>}
      </div>
      {!turns.length && <div className={styles.suggestions} aria-label="Conversation starters">{suggestions.map(suggestion => <button key={suggestion} onClick={() => setDraft(suggestion)}>{suggestion}<span aria-hidden="true">↗</span></button>)}</div>}
      <ChatComposer draft={draft} onChange={setDraft} onSend={() => void sendText()} pending={busy} connected={live && !!stateToken.current}/>
    </div>}
    <div className={styles.session}>
      {error && <p className={styles.error} role="alert">{error}</p>}
      {locked && !live && conversation?.status !== "ended" && <p className={styles.help} role="status">{busy ? "Preparing your conversation…" : "A conversation is reserved. Check its status or end it before beginning again. Refresh does not reconnect your microphone or replay a message."}</p>}
      {!locked && <><label className={styles.consent}><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} disabled={busy}/><span>I agree to AI processing{mode === "voice" ? " of microphone audio" : " of my messages"} and will use fictional property details.</span></label>
        {availability?.authenticated === false ? <Link href="/login?returnTo=conversation" className={styles.start}><ModeIcon mode={mode}/>Sign in to {mode === "voice" ? "talk" : "chat"}<span aria-hidden="true">↗</span></Link> : <button className={styles.start} disabled={!ready || busy || !consent || !availability?.[mode]} onClick={() => void start()}><ModeIcon mode={mode}/>{busy ? "Getting ready…" : availability?.mock ? "Start simulation" : mode === "voice" ? "Start voice conversation" : "Start text conversation"}<span aria-hidden="true">↗</span></button>}
        <p className={styles.help}>{availability === null ? "Checking availability…" : !availability.authenticated ? "Private preview. Use your existing operator sign-in to begin." : !availability[mode] ? "This mode is awaiting owner activation." : `Up to ${Math.floor(availability.max_seconds / 60)} minutes. ${mode === "voice" ? "Your microphone starts only after you choose to connect." : "Text chat is silent. Your microphone stays off."}`}</p>
      </>}
      {locked && <div className={styles.actions}>{conversation?.status === "ended" ? <button className={styles.start} disabled={busy} onClick={reset}>Begin a new conversation <span aria-hidden="true">↗</span></button> : <><button className={styles.end} disabled={ending.current} onClick={() => void endConversation()}>{mode === "voice" ? "End voice chat" : "End conversation"}</button><button disabled={busy} onClick={() => void recover()}>Check status</button><button disabled={busy} onClick={() => {
        const id = activeId.current;
        if (id) void conversationRequest(`sessions/${id}/refresh`, "POST", {}).then(value => { if (!isConversation(value) || value.id !== id) throw new Error("The recovered identity is invalid."); if (mounted.current && activeId.current === id) updateConversation(value); }).catch(failure => { if (mounted.current) setError(failure instanceof Error ? failure.message : "Provider status is unavailable."); });
      }}>Reconcile</button></>}</div>}
    </div>
    <footer className={styles.footer}><span><i/>US property conversations</span><span>Fictional homes · No bookings or outreach</span></footer>
  </section>;
}
