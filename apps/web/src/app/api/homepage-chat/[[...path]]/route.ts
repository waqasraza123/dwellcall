import { randomBytes } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";
import { BackendError, operatorBackend } from "@/lib/backend";
import { authenticated } from "@/lib/operator-session";
import { proxyFailure, requestBody, requireSameOrigin } from "@/lib/proxy";

export const runtime = "nodejs";
const cookie = process.env.NODE_ENV === "production" ? "__Host-dwellcall-browser" : "dwellcall-browser";
const ownerPattern = /^[A-Za-z0-9_-]{43}$/;
const sessionPath = /^sessions\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
type Context = { params: Promise<{ path?: string[] }> };

async function handle(request: NextRequest, context: Context) {
  try {
    if (request.headers.get("sec-fetch-site") === "cross-site") throw new BackendError(403, "Use DwellCall on this website.");
    if (request.method !== "GET") requireSameOrigin(request);
    const path = (await context.params).path?.join("/") ?? "availability";
    const allowed = request.method === "GET" ? path === "availability" || sessionPath.test(path) : path === "sessions" || /\/(turn|end|refresh)$/.test(path) && sessionPath.test(path.replace(/\/(turn|end|refresh)$/, ""));
    if (!allowed) throw new BackendError(404, "This conversation action is unavailable.");
    if (!await authenticated()) {
      if (path === "availability") return NextResponse.json({ authenticated: false, voice: false, text: false, mock: false, max_seconds: 180 }, { headers: { "Cache-Control": "no-store" } });
      throw new BackendError(401, "Sign in to start your property conversation.");
    }
    const saved = request.cookies.get(cookie)?.value;
    const owner = saved && ownerPattern.test(saved) ? saved : randomBytes(32).toString("base64url");
    if (path !== "availability" && owner !== saved) throw new BackendError(409, "Refresh conversation availability before continuing.");
    const body = request.method === "GET" ? undefined : await requestBody(request, 65536);
    const upstream = await operatorBackend(`browser-conversations/${path}`, request.method, body, undefined, owner);
    const data: unknown = await upstream.json();
    if (!upstream.ok) {
      const code = data && typeof data === "object" && "error" in data && data.error && typeof data.error === "object" && "code" in data.error ? String(data.error.code) : "";
      const messages: Record<string, string> = {
        AUDIO_SESSION_LIMIT: "Another conversation is active or unresolved, or the daily call/spending limit was reached.",
        BROWSER_AGENT_INVALID: "Voice is awaiting the owner's published Retell agent and privacy configuration.",
        BROWSER_START_UNCONFIRMED: "The connection is unconfirmed. Check this saved request before starting another.",
        BROWSER_PROVIDER_REJECTED: "Retell rejected the connection. The owner must check agent access, account status and quota.",
        BROWSER_TURN_UNCONFIRMED: "The reply was interrupted. Your draft is kept; end this session before starting again.",
        BROWSER_CONVERSATION_DISABLED: "This conversation mode has not been enabled yet.",
        BROWSER_CONVERSATIONS_PAUSED: "Conversations have been paused by the operator.",
        BROWSER_CONVERSATION_BLOCKED: "This session is paused, interrupted, already used or expired. Check its status before continuing.",
        BROWSER_CONVERSATION_NOT_FOUND: "The saved conversation is not visible. Keep this request and check again.",
        BROWSER_RECOVERY_UNAVAILABLE: "Provider status is unavailable. Keep the saved request and check again.",
        BROWSER_STOP_UNCONFIRMED: "Your microphone is off. Provider completion is unconfirmed; check status.",
      };
      throw new BackendError(upstream.status, messages[code] ?? "The conversation is unavailable. Check its saved status before repeating an action.", code);
    }
    const response = NextResponse.json(path === "availability" && data && typeof data === "object" ? { ...data, authenticated: true } : data, { headers: { "Cache-Control": "no-store" } });
    if (saved !== owner) response.cookies.set(cookie, owner, { httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "strict", path: "/", maxAge: 8 * 60 * 60 });
    return response;
  } catch (error) { return proxyFailure(error); }
}
export const GET = handle;
export const POST = handle;
