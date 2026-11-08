import { platformExtensionsEnabled } from "@/lib/product-scope";
import { NextRequest } from "next/server";
import { accountBackend, currentAccount } from "@/lib/account-session";
import { BackendError } from "@/lib/backend";
import { forwardResponse, proxyFailure, requestBody, requireSameOrigin } from "@/lib/proxy";
import { UUID_PATTERN } from "@/features/outbound/contracts";

export const runtime = "nodejs";
type Context = { params: Promise<{ path?: string[] }> };
async function handle(request: NextRequest, context: Context) {
  try {
    if (!platformExtensionsEnabled()) throw new BackendError(404, "This extension is disabled.");
    if (request.headers.get("sec-fetch-site") === "cross-site") throw new BackendError(403, "Use this workspace on DwellCall.");
    if (request.method !== "GET") requireSameOrigin(request);
    const account = await currentAccount();
    if (account.status !== "authenticated" || !account.user.operator_access) throw new BackendError(401, "Sign in with an approved account to review leads.");
    const parts = (await context.params).path ?? [];
    let path: string;
    let body: string | undefined;
    if (request.method === "GET" && parts.length === 1 && parts[0] === "tasks") {
      const status = request.nextUrl.searchParams.get("status") ?? "open";
      if (!["open", "completed", "cancelled", "deferred"].includes(status)) throw new BackendError(422, "Choose a valid task status.");
      path = `tasks?status=${status}`;
    } else if (parts.length === 1 && UUID_PATTERN.test(parts[0]) && request.method === "GET") {
      path = parts[0];
    } else if (parts.length === 2 && UUID_PATTERN.test(parts[0]) && parts[1] === "actions" && request.method === "POST") {
      path = `${parts[0]}/actions`;
      body = await requestBody(request, 4096);
      const data: unknown = JSON.parse(body);
      if (!data || typeof data !== "object" || !("request_id" in data) || typeof data.request_id !== "string" || !UUID_PATTERN.test(data.request_id)) throw new BackendError(422, "A saved action key is required.");
    } else throw new BackendError(404, "This lead review action is unavailable.");
    return await forwardResponse(await accountBackend(`call-leads/${path}`, request.method, body));
  } catch (error) { return proxyFailure(error); }
}
export const GET = handle;
export const POST = handle;
