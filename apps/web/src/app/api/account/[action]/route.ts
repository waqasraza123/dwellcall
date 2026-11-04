import { NextRequest, NextResponse } from "next/server";
import {
  ACCOUNT_COOKIE,
  MFA_COOKIE,
  completeAccountLogout,
  accountBackend,
  parseAccount,
} from "@/lib/account-session";
import {
  forwardResponse,
  proxyFailure,
  requestBody,
  requireSameOrigin,
} from "@/lib/proxy";

import { BackendError } from "@/lib/backend";

export const runtime = "nodejs";
type Context = { params: Promise<{ action: string }> };

async function handle(request: NextRequest, context: Context) {
  try {
    const { action } = await context.params;
    if (
      (request.method === "GET" && !["me", "mfa-status"].includes(action)) ||
      (request.method === "POST" &&
        !["signup", "login", "logout", "mfa-setup", "mfa-verify", "mfa-recover", "mfa-cancel"].includes(action))
    )
      throw new BackendError(404, "Page not found.");
    if (request.method === "POST") requireSameOrigin(request);
    const body =
      request.method === "POST" ? await requestBody(request, 4096) : undefined;
    if (action === "logout") {
      const response = await completeAccountLogout(
        Promise.all([
          accountBackend("auth/logout", request.method, body),
          accountBackend("auth/mfa/cancel", "POST", "{}", "mfa").catch(() => undefined),
        ]).then(([revocation]) => revocation),
      );
      return response;
    }
    if (action === "mfa-cancel") {
      const upstream = await accountBackend("auth/mfa/cancel", "POST", "{}", "mfa");
      if (!upstream.ok) return forwardResponse(upstream);
      const response = new NextResponse(null, { status: 204, headers: { "Cache-Control": "no-store" } });
      response.cookies.set(MFA_COOKIE, "", { httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "strict", path: "/", maxAge: 0 });
      return response;
    }
    const mfa = action.startsWith("mfa-");
    const upstream = await accountBackend(
      mfa ? `auth/mfa/${action.slice(4)}` : `auth/${action}`,
      request.method,
      body,
      mfa ? "mfa" : "session",
    );
    if (!upstream.ok) return forwardResponse(upstream);
    const data: unknown = await upstream.json();
    if (action === "me")
      return NextResponse.json(parseAccount(data), {
        headers: { "Cache-Control": "no-store" },
      });
    if (action === "mfa-status" || action === "mfa-setup") {
      return NextResponse.json(data, { headers: { "Cache-Control": "no-store" } });
    }
    if (action === "signup" || action === "login" || action === "mfa-recover") {
      if (typeof data !== "object" || data === null || !("mfa_required" in data) ||
          data.mfa_required !== true || !("challenge_token" in data) ||
          typeof data.challenge_token !== "string" ||
          !/^[A-Za-z0-9_-]{32,128}$/.test(data.challenge_token) ||
          !("next_action" in data) || !["enroll", "verify"].includes(String(data.next_action)) ||
          !("expires_in" in data) || typeof data.expires_in !== "number" ||
          !Number.isInteger(data.expires_in) || data.expires_in < 1 || data.expires_in > 600 ||
          "session_token" in data) {
        throw new BackendError(502, "Authenticator sign-in could not be started. Try again.");
      }
      const response = NextResponse.json(
        { mfa_required: true, next_action: data.next_action },
        { status: upstream.status, headers: { "Cache-Control": "no-store" } },
      );
      response.cookies.set(ACCOUNT_COOKIE, "", {
        httpOnly: true, secure: process.env.NODE_ENV === "production",
        sameSite: "strict", path: "/", maxAge: 0,
      });
      response.cookies.set(MFA_COOKIE, data.challenge_token, {
        httpOnly: true, secure: process.env.NODE_ENV === "production",
        sameSite: "strict", path: "/", maxAge: data.expires_in,
      });
      return response;
    }
    if (
      action !== "mfa-verify" ||
      typeof data !== "object" ||
      data === null ||
      !("mfa_verified" in data) || data.mfa_verified !== true ||
      !("user" in data) ||
      !("session_token" in data) ||
      typeof data.session_token !== "string" ||
      data.session_token.length < 32 ||
      data.session_token.length > 128 ||
      /[^A-Za-z0-9_-]/.test(data.session_token) ||
      !("expires_in" in data) ||
      typeof data.expires_in !== "number" ||
      !Number.isInteger(data.expires_in) ||
      data.expires_in < 1 ||
      data.expires_in > 28800
    )
      throw new BackendError(
        502,
        "We could not finish signing you in. Please try again.",
      );
    const recoveryCodes = "recovery_codes" in data ? data.recovery_codes : undefined;
    if (recoveryCodes !== undefined && recoveryCodes !== null &&
        (!Array.isArray(recoveryCodes) || recoveryCodes.length !== 10 ||
          !recoveryCodes.every((item: unknown) => typeof item === "string" &&
            /^[a-f0-9]{8}(-[a-f0-9]{8}){3}$/.test(item)))) {
      throw new BackendError(502, "Recovery codes could not be read. Sign in again.");
    }
    const response = NextResponse.json(
      { user: parseAccount(data.user), recovery_codes: recoveryCodes ?? null },
      { status: upstream.status, headers: { "Cache-Control": "no-store" } },
    );
    response.cookies.set(ACCOUNT_COOKIE, data.session_token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "strict",
      path: "/",
      maxAge: data.expires_in,
    });
    response.cookies.set(MFA_COOKIE, "", {
      httpOnly: true, secure: process.env.NODE_ENV === "production",
      sameSite: "strict", path: "/", maxAge: 0,
    });
    return response;
  } catch (error) {
    return proxyFailure(error);
  }
}

export const GET = handle;
export const POST = handle;
