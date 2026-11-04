export class BackendError extends Error {
  constructor(readonly status: number, message: string, readonly code?: string) { super(message); this.name = "BackendError"; }
}
export function backendOrigin(): string {
  const raw = process.env.DWELLCALL_API_BASE_URL;
  if (!raw) throw new BackendError(503, "Backend access is not configured.");
  let base: URL;
  try { base = new URL(raw); } catch { throw new BackendError(503, "Backend access is not configured."); }
  if (!["http:", "https:"].includes(base.protocol) || (process.env.NODE_ENV === "production" && base.protocol !== "https:") || base.username || base.password || base.search || base.hash || base.pathname !== "/") throw new BackendError(503, "Backend access is not configured.");
  return base.origin;
}
export async function operatorBackend(path: string, method = "GET", body?: string, key?: string, browserSession?: string): Promise<Response> {
  const token = process.env.DWELLCALL_BACKEND_ADMIN_TOKEN;
  if (!token || token.length < 32) throw new BackendError(503, "Operator access is not configured.");
  return fetch(`${backendOrigin()}/api/v1/${path}`, {
    method, body, cache: "no-store", redirect: "error",
    headers: { "Content-Type": "application/json", "X-Admin-Token": token, ...(key ? { "Idempotency-Key": key, "X-Operator-Action": "reserve" } : {}), ...(browserSession ? { "X-Browser-Session": browserSession } : {}) },
    signal: AbortSignal.timeout(method === "GET" ? 20_000 : 55_000),
  });
}
