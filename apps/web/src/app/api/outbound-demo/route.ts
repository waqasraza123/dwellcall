import { NextRequest, NextResponse } from "next/server";
import { currentAccount } from "@/lib/account-session";
import { BackendError, operatorBackend } from "@/lib/backend";
import { forwardResponse, proxyFailure, requestBody, requireSameOrigin } from "@/lib/proxy";
import { UUID_PATTERN } from "@/features/outbound/contracts";

export const runtime = "nodejs";
async function handle(request: NextRequest) {
  try {
    if (request.headers.get("sec-fetch-site") === "cross-site") throw new BackendError(403, "Use DwellCall on this website.");
    if (request.method !== "GET") requireSameOrigin(request);
    const account = await currentAccount();
    if (account.status !== "authenticated" || !account.user.operator_access) {
      return NextResponse.json({ error: { code: "CALLBACK_SIGN_IN_REQUIRED", message: "Sign in with an approved account to request a call." } }, { status: 401, headers: { "Cache-Control": "no-store" } });
    }
    let path = "availability";
    let body: string | undefined;
    if (request.method === "GET") {
      const id = request.nextUrl.searchParams.get("request_id");
      if (id !== null) {
        if (!UUID_PATTERN.test(id)) throw new BackendError(422, "Invalid saved request.");
        path = `requests/${id}`;
      }
    } else {
      const data: unknown = JSON.parse(await requestBody(request, 4096));
      if (!data || typeof data !== "object" || Array.isArray(data)) throw new BackendError(422, "Invalid call request.");
      const { action, ...payload } = data as Record<string, unknown>;
      if (action === "send_code") path = "phone-verifications";
      else if (action === "verify_code") path = "phone-verifications/verify";
      else if (action === undefined) path = "calls";
      else throw new BackendError(422, "Invalid call action.");
      body = JSON.stringify(payload);
    }
    return await forwardResponse(await operatorBackend(`outbound-demo/${path}`, request.method, body, undefined, account.user.id));
  } catch (error) { return proxyFailure(error); }
}
export const GET = handle;
export const POST = handle;
