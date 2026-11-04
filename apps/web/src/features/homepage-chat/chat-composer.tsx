"use client";

import { useId, type FormEvent } from "react";
import styles from "./homepage-chat.module.css";

export function ChatComposer({ draft, onChange, onSend, pending, connected }: { draft: string; onChange: (value: string) => void; onSend: () => void; pending: boolean; connected: boolean }) {
  const id = useId();
  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); if (connected && !pending && draft.trim()) onSend(); }
  return <form onSubmit={submit} className={styles.composer} aria-busy={pending}>
    <label className="sr-only" htmlFor={id}>Message your property consultant</label>
    <textarea id={id} rows={2} maxLength={1000} value={draft} onChange={event => onChange(event.target.value)} placeholder="A two-bedroom rental, around $2,500…" aria-describedby={`${id}-help`} onKeyDown={event => {
      if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); }
    }}/>
    <div><span id={`${id}-help`}>{pending ? "Considering your preferences…" : "Enter to send · Shift + Enter for a new line"}</span><button type="submit" disabled={!connected || pending || !draft.trim()} aria-label="Send message">Send <span aria-hidden="true">↗</span></button></div>
  </form>;
}
