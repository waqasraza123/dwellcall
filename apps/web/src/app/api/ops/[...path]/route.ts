import { platformExtensionsEnabled } from "@/lib/product-scope";
import { NextRequest } from "next/server";
import { authenticated } from "@/lib/operator-session";
import { BackendError, operatorBackend } from "@/lib/backend";
import { bridgeAllowed } from "@/lib/bridge-policy";
import { forwardResponse, proxyFailure, requestBody, requireSameOrigin } from "@/lib/proxy";

export const runtime = "nodejs";
type Context = { params: Promise<{ path: string[] }> };
async function handle(request: NextRequest, context: Context) {
  try {
    if (!await authenticated()) throw new BackendError(401, "Sign in to open this workspace.");
    const path = (await context.params).path.join("/");
    if (!bridgeAllowed(request.method, path, platformExtensionsEnabled())) throw new BackendError(404, "This action is unavailable.");
    let body: string | undefined; let key: string | undefined;
    if (request.method !== "GET") {
      requireSameOrigin(request); key = request.headers.get("Idempotency-Key") ?? "";
      if (!/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(key)) throw new BackendError(422, "Start a new deliberate action.");
      body = await requestBody(request);
    }
    const search = request.nextUrl.searchParams.toString();
    return await forwardResponse(await operatorBackend(path + (search ? `?${search}` : ""), request.method, body, key));
  } catch (error) { return proxyFailure(error); }
}
export const GET = handle;
export const POST = handle;
export const PUT = handle;
