"use client";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { authPageHref, type AuthIntent } from "@/features/account/auth-continuation";

export function LoginForm({ returnTo, mode = "login" }: { returnTo?: AuthIntent; mode?: "login" | "signup" } = {}) {
  const router = useRouter();
  const signup = mode === "signup";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/account/${mode}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store",
        body: JSON.stringify({ email: fields.get("email"), password: fields.get("password"), ...(signup ? { full_name: fields.get("full_name") } : {}) }),
        signal: AbortSignal.timeout(25_000),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body?.error?.message ?? "Sign in could not be completed.");
      if (body?.mfa_required !== true) throw new Error("Authenticator verification is required.");
      form.reset();
      router.replace(authPageHref("/mfa", returnTo)); router.refresh();
    } catch (failure) {
      setError(failure instanceof Error && !["TypeError", "TimeoutError"].includes(failure.name) ? failure.message : "Sign in is unavailable. Please try again.");
    } finally { setBusy(false); }
  }
  return <><form className="access-form" onSubmit={submit} aria-busy={busy}>
    {signup && <label htmlFor="full-name">Your name<input id="full-name" name="full_name" required maxLength={160} autoComplete="name" disabled={busy}/></label>}
    <label htmlFor="account-email">Email<input id="account-email" name="email" type="email" required maxLength={254} autoComplete="email" autoCapitalize="none" spellCheck={false} disabled={busy}/></label>
    <label htmlFor="account-password">Password<input id="account-password" type="password" name="password" required minLength={signup ? 15 : 1} maxLength={128} autoComplete={signup ? "new-password" : "current-password"} aria-describedby="login-help" disabled={busy}/></label>
    <p id="login-help" className="muted">{signup ? "Use at least 15 characters. Next, set up your required authenticator." : "Continue with your password, then your authenticator code."}</p>
    {error && <p className="notice error" role="alert">{error}</p>}
    <button className="primary" disabled={busy}>{busy ? "Please wait…" : signup ? "Create account →" : "Continue →"}</button>
  </form><p className="muted">{signup ? "Already registered?" : "New to DwellCall?"} <Link href={authPageHref(signup ? "/login" : "/signup", returnTo)}>{signup ? "Sign in" : "Create an account"}</Link></p></>;
}
