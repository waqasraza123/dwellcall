import { platformExtensionsEnabled } from "@/lib/product-scope";
import { backendOrigin } from "@/lib/backend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function POST(request: Request): Promise<Response> {
  const headers = { "Cache-Control": "no-store" };
  if (!platformExtensionsEnabled()) return new Response(null, { status: 404, headers });
  const reader = request.body?.getReader();
  if (!reader) return new Response(null, { status: 400, headers });
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    while (true) {
      const result = await reader.read();
      if (result.done) break;
      length += result.value.byteLength;
      if (length > 1_048_576) { await reader.cancel(); return new Response(null, { status: 413, headers }); }
      chunks.push(result.value);
    }
    const body = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
    const response = await fetch(`${backendOrigin()}/api/v1/billing/webhook`, {
      method: "POST", body, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(20_000),
      headers: { "Content-Type": "application/json", "Stripe-Signature": request.headers.get("stripe-signature") ?? "" },
    });
    return new Response(await response.arrayBuffer(), { status: response.status, headers: { ...headers, "Content-Type": "application/json" } });
  } catch {
    return Response.json({ error: { message: "Webhook delivery is temporarily unavailable." } }, { status: 503, headers });
  }
}
