import { cache } from "react";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { backendOrigin, BackendError } from "./backend";

export type Account = Readonly<{ id: string; full_name: string; email: string; operator_access: boolean }>;
export const ACCOUNT_COOKIE = process.env.NODE_ENV === "production" ? "__Host-dwellcall-session" : "dwellcall-session";
export const MFA_COOKIE = process.env.NODE_ENV === "production" ? "__Host-dwellcall-mfa" : "dwellcall-mfa";
export const accountCookieOptions = { httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "strict" as const, path: "/" };

export function parseAccount(value: unknown): Account {
  if (typeof value !== "object" || value === null || !("id" in value) || typeof value.id !== "string" || !("full_name" in value) || typeof value.full_name !== "string" || !("email" in value) || typeof value.email !== "string" || !("operator_access" in value) || typeof value.operator_access !== "boolean") throw new BackendError(502, "Your account could not be loaded. Please try again.");
  return { id: value.id, full_name: value.full_name, email: value.email, operator_access: value.operator_access };
}

export async function accountBackend(path: string, method = "GET", body?: string, scope: "session" | "mfa" = "session"): Promise<Response> {
  const key = process.env.DWELLCALL_ACCOUNT_PORTAL_SECRET;
  if (!key || key.length < 32) throw new BackendError(503, "Account access is not configured.");
  const token = (await cookies()).get(scope === "mfa" ? MFA_COOKIE : ACCOUNT_COOKIE)?.value;
  return fetch(`${backendOrigin()}/api/v1/account/${path}`, {
    method, body, cache: "no-store", redirect: "error",
    headers: { "Content-Type": "application/json", "X-Account-Portal-Key": key, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    signal: AbortSignal.timeout(path.startsWith("billing/") && method !== "GET" ? 55_000 : 20_000),
  });
}

export const currentAccount = cache(async (): Promise<{ status: "authenticated"; user: Account } | { status: "anonymous" | "unavailable" }> => {
  if (!(await cookies()).has(ACCOUNT_COOKIE)) return { status: "anonymous" };
  try {
    const response = await accountBackend("auth/me");
    if (response.status === 401) return { status: "anonymous" };
    if (!response.ok) return { status: "unavailable" };
    return { status: "authenticated", user: parseAccount(await response.json()) };
  } catch { return { status: "unavailable" }; }
});

export async function completeAccountLogout(revocation: Promise<Response>): Promise<NextResponse> {
  const upstream = await revocation;
  if (!upstream.ok) throw new BackendError(503, "Sign out could not be confirmed. Please try again.");
  const response = new NextResponse(null, { status: 204, headers: { "Cache-Control": "no-store" } });
  for (const cookie of [ACCOUNT_COOKIE, MFA_COOKIE]) response.cookies.set(cookie, "", { ...accountCookieOptions, maxAge: 0 });
  return response;
}
