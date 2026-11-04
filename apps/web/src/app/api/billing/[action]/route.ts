import { NextRequest, NextResponse } from "next/server";
import { accountBackend } from "@/lib/account-session";
import { BackendError } from "@/lib/backend";
import { forwardResponse, proxyFailure, requestBody, requireSameOrigin } from "@/lib/proxy";
import { stripeRedirect } from "@/features/billing/contracts";
import { publicCatalog } from "@/features/billing/server";

export const runtime = "nodejs";
type Context = { params: Promise<{ action: string }> };
async function handle(request: NextRequest, context: Context) {
  try {
    const { action } = await context.params;
    const allowed = request.method === "GET" ? ["plans", "status"] : ["checkout", "portal", "refresh"];
    if (!allowed.includes(action)) throw new BackendError(404, "This billing action is unavailable.");
    if (request.method !== "GET") requireSameOrigin(request);
    if (action === "plans") {
      const data = await publicCatalog();
      if (!data) throw new BackendError(503, "Pricing is temporarily unavailable.");
      return NextResponse.json(data, { headers: { "Cache-Control": "no-store" } });
    }
    const body = request.method === "GET" ? undefined : await requestBody(request, 4096);
    const upstream = await accountBackend(`billing/${action}`, request.method, body);
    if (!upstream.ok) return forwardResponse(upstream);
    if (action === "checkout" || action === "portal") {
      let url: string;
      try { url = stripeRedirect(await upstream.json(), action); }
      catch { throw new BackendError(502, "Stripe returned an invalid redirect."); }
      return NextResponse.json({ url }, { headers: { "Cache-Control": "no-store" } });
    }
    return forwardResponse(upstream);
  } catch (failure) { return proxyFailure(failure); }
}
export const GET = handle;
export const POST = handle;
