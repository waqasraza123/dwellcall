import { NextRequest, NextResponse } from "next/server";
import { BackendError, operatorBackend } from "@/lib/backend";
import { issueSession, SESSION_COOKIE, sessionOptions, validPassword } from "@/lib/operator-session";
import { proxyFailure, requestBody, requireSameOrigin } from "@/lib/proxy";

export const runtime = "nodejs";
let failed = 0; let windowStart = Date.now();
export async function POST(request: NextRequest) {
  try {
    requireSameOrigin(request);
    if (Date.now() - windowStart > 60_000) { windowStart = Date.now(); failed = 0; }
    if (failed >= 20) throw new BackendError(429, "Wait a minute before signing in again.");
    const body: unknown = JSON.parse(await requestBody(request, 4096));
    failed += 1;
    if (typeof body !== "object" || body === null || !("password" in body) || typeof body.password !== "string" || !validPassword(body.password)) throw new BackendError(401, "Operator access could not be confirmed.");
    const response = await operatorBackend("crm/ghl/status");
    if (!response.ok) throw new BackendError(503, "Backend operator access is unavailable.");
    const result = NextResponse.json({ authenticated: true }, { headers: { "Cache-Control": "no-store" } });
    result.cookies.set(SESSION_COOKIE, issueSession(), sessionOptions); failed = 0;
    return result;
  } catch (error) { return proxyFailure(error); }
}
export async function DELETE(request: NextRequest) {
  try { requireSameOrigin(request); const response = new NextResponse(null, { status: 204, headers: { "Cache-Control": "no-store" } }); response.cookies.set(SESSION_COOKIE, "", { ...sessionOptions, maxAge: 0 }); return response; } catch (error) { return proxyFailure(error); }
}
