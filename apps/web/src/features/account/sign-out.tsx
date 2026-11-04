"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
export function SignOut() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return <><button disabled={busy} onClick={async () => {
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/account/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}", cache: "no-store", signal: AbortSignal.timeout(25_000) });
      if (!response.ok) throw new Error("Sign out could not be confirmed. Please try again.");
      router.replace("/login"); router.refresh();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Sign out is unavailable."); }
    finally { setBusy(false); }
  }}>{busy ? "Signing out…" : "Sign out"}</button>{error && <p role="alert">{error}</p>}</>;
}
