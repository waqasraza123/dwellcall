"use client";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
export function LoginForm() {
  const router = useRouter(); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); if (busy) return; const form = event.currentTarget; const password = String(new FormData(form).get("password")); setBusy(true); setError(""); try { const response = await fetch("/api/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password }), cache: "no-store", signal: AbortSignal.timeout(25_000) }); form.reset(); if (!response.ok) { const body = await response.json(); throw new Error(body?.error?.message ?? "Operator access could not be confirmed."); } router.replace("/dashboard"); router.refresh(); } catch (error) { setError(error instanceof Error ? error.message : "Sign in is unavailable."); } finally { setBusy(false); } }
  return <form className="access-form" onSubmit={submit}><label htmlFor="operator-password">Operator password</label><input id="operator-password" type="password" name="password" required maxLength={1024} autoComplete="current-password" aria-describedby="login-help" disabled={busy}/><p id="login-help" className="muted">Use the operator password configured for this DwellCall workspace.</p>{error && <p className="notice error" role="alert">{error}</p>}<button className="primary" disabled={busy}>{busy ? "Opening workspace…" : "Open workspace →"}</button></form>;
}
