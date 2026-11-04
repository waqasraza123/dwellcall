"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { type AuthIntent, authPageHref, authReturnHref } from "./auth-continuation";
import { AuthenticatorSetup } from "./authenticator-setup";
import { parseMfaSetup } from "./mfa-setup";
import type { MfaSetup } from "./mfa-setup";

type Stage = "loading" | "enroll" | "verify" | "recovery" | "codes";
type MfaState = { stage: "enroll"; setup: MfaSetup } | { stage: "verify" };

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function securityRequest(
  action: string,
  body?: object,
): Promise<unknown> {
  const response = await fetch(`/api/account/${action}`, {
    method: body === undefined ? "GET" : "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(20000),
  });
  const data: unknown = response.status === 204 ? null : await response.json();
  if (!response.ok) {
    throw new Error(
      record(data) &&
        record(data.error) &&
        typeof data.error.message === "string"
        ? data.error.message
        : "Verification could not be completed. Sign in again and retry.",
    );
  }
  return data;
}

async function loadMfa(): Promise<MfaState> {
  const status = await securityRequest("mfa-status");
  if (
    !record(status) ||
    !["enroll", "verify"].includes(String(status.next_action))
  ) {
    throw new Error("Sign in again to continue verification.");
  }
  if (status.next_action === "verify") return { stage: "verify" };
  return {
    stage: "enroll",
    setup: parseMfaSetup(await securityRequest("mfa-setup", {})),
  };
}

export function AccountMfaForm({ intent }: { intent?: AuthIntent }) {
  const router = useRouter();
  const leaving = useRef(false);
  const [stage, setStage] = useState<Stage>("loading");
  const [setup, setSetup] = useState<MfaSetup>();
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[]>([]);
  const [savedCodes, setSavedCodes] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    void loadMfa()
      .then((result) => {
        if (active && !leaving.current) {
          setSetup(result.stage === "enroll" ? result.setup : undefined);
          setStage(result.stage);
        }
      })
      .catch((failure: unknown) => {
        if (active && !leaving.current)
          setError(
            failure instanceof Error ? failure.message : "Sign in again.",
          );
      });
    return () => {
      active = false;
    };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await securityRequest(
        stage === "recovery" ? "mfa-recover" : "mfa-verify",
        { code },
      );
      setCode("");
      if (stage === "recovery") {
        const next = await loadMfa();
        setSetup(next.stage === "enroll" ? next.setup : undefined);
        setStage(next.stage);
      } else if (
        record(result) &&
        Array.isArray(result.recovery_codes) &&
        result.recovery_codes.length === 10 &&
        result.recovery_codes.every((item: unknown) => typeof item === "string")
      ) {
        setSetup(undefined);
        setCodes(result.recovery_codes);
        setSavedCodes(false);
        setStage("codes");
      } else {
        setSetup(undefined);
        router.replace(authReturnHref(intent));
        router.refresh();
      }
    } catch (failure) {
      setCode("");
      setError(
        failure instanceof Error
          ? failure.message
          : "Verification failed. Sign in again.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    leaving.current = true;
    setBusy(true);
    setSetup(undefined);
    setCode("");
    setCodes([]);
    await securityRequest("mfa-cancel", {}).catch(() => undefined);
    router.replace(authPageHref("/login", intent));
    router.refresh();
  }

  function changeStage(next: "verify" | "recovery") {
    setCode("");
    setError("");
    setSetup(undefined);
    setStage(next);
  }

  const recovering = stage === "recovery";
  return <div aria-live="polite"><p className="eyebrow">ACCOUNT SECURITY</p><h2>{stage === "enroll" ? "Set up your authenticator." : stage === "codes" ? "Save your recovery codes." : "Verify your sign-in."}</h2>
    {stage === "loading" && !error && <p role="status">Preparing verification…</p>}
    {stage === "enroll" && setup && <AuthenticatorSetup setup={setup}/>}
    {stage === "codes" ? <>
      <p>Save these codes somewhere private. Each code can replace a lost authenticator once. They are only shown once.</p>
      <ul aria-label="Recovery codes">{codes.map(item => <li key={item}><code>{item}</code></li>)}</ul>
      <label className="checkbox"><input type="checkbox" checked={savedCodes} onChange={event => setSavedCodes(event.target.checked)}/>I saved my recovery codes.</label>
      <button className="primary" disabled={!savedCodes} onClick={() => { setCodes([]); router.replace(authReturnHref(intent)); router.refresh(); }}>Continue →</button>
    </> : stage !== "loading" && <form className="access-form" onSubmit={event => void submit(event)} aria-busy={busy}>
      <label htmlFor="mfa-code">{recovering ? "Recovery code" : "Authenticator code"}</label>
      <input id="mfa-code" name="code" value={code} onChange={event => setCode(recovering ? event.target.value : event.target.value.replace(/\D/g, "").slice(0, 6))} autoComplete={recovering ? "off" : "one-time-code"} inputMode={recovering ? "text" : "numeric"} pattern={recovering ? "[A-Fa-f0-9]{8}(-[A-Fa-f0-9]{8}){3}" : "[0-9]{6}"} minLength={recovering ? 35 : 6} maxLength={recovering ? 35 : 6} autoCapitalize="none" spellCheck={false} disabled={busy} required/>
      <p className="muted">{recovering ? "After recovery, set up and verify your replacement authenticator." : "Enter the current six-digit code for DwellCall in your authenticator app."}</p>
      <button className="primary" disabled={busy}>{busy ? "Verifying…" : "Verify and continue →"}</button>
      {stage === "verify" && <button type="button" disabled={busy} onClick={() => changeStage("recovery")}>Use a recovery code</button>}
      {recovering && <button type="button" disabled={busy} onClick={() => changeStage("verify")}>Use my authenticator</button>}
    </form>}
    {error && <p className="notice error" role="alert">{error}</p>}
    {stage !== "codes" && <button type="button" disabled={busy} onClick={() => void cancel()}>Cancel and sign in again</button>}
  </div>;
}
