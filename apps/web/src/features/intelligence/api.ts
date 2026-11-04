import { useCallback, useEffect, useState } from "react";

export class OperationsApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "OperationsApiError";
  }
}
// Adapted from HVACLine's operations request helper. Authentication stays server-side.
export async function requestApi<T>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const serialized = body === undefined ? undefined : JSON.stringify(body);
  let key: string | undefined;
  let storageKey = "";
  if (method !== "GET") {
    const bytes = new TextEncoder().encode(
      `${method}:${path}:${serialized ?? ""}`,
    );
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    storageKey =
      "dwellcall-action:" +
      Array.from(new Uint8Array(digest))
        .map((x) => x.toString(16).padStart(2, "0"))
        .join("");
    key = sessionStorage.getItem(storageKey) ?? crypto.randomUUID();
    sessionStorage.setItem(storageKey, key);
  }
  const response = await fetch(`/api/ops/${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(key ? { "Idempotency-Key": key } : {}),
    },
    body: serialized,
    cache: "no-store",
    signal: signal
      ? AbortSignal.any([signal, AbortSignal.timeout(25_000)])
      : AbortSignal.timeout(method === "GET" ? 25_000 : 60_000),
  });
  let data: unknown;
  try {
    data = response.status === 204 ? undefined : await response.json();
  } catch {
    throw new OperationsApiError(
      502,
      "The service response was unavailable. Refresh before repeating the action.",
    );
  }
  if (!response.ok) {
    if (
      method !== "GET" &&
      response.status < 500 &&
      ![409, 429].includes(response.status)
    )
      sessionStorage.removeItem(storageKey);
    const message =
      typeof data === "object" &&
      data !== null &&
      "error" in data &&
      typeof data.error === "object" &&
      data.error !== null &&
      "message" in data.error &&
      typeof data.error.message === "string"
        ? data.error.message
        : "The request could not be completed.";
    throw new OperationsApiError(response.status, message);
  }
  if (storageKey) sessionStorage.removeItem(storageKey);
  return data as T;
}
export function useResource<T>(path: string | null) {
  const [state, setState] = useState<{
    path: string | null;
    version: number;
    data?: T;
    error?: string;
    loading: boolean;
  }>({ path, version: 0, loading: !!path });
  const [version, setVersion] = useState(0);
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    requestApi<T>(path, "GET", undefined, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted)
          setState({ path, version, data, loading: false });
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setState({
            path,
            version,
            error:
              error instanceof Error
                ? error.message
                : "This view is unavailable.",
            loading: false,
          });
      });
    return () => controller.abort();
  }, [path, version]);
  const currentState: typeof state =
    state.path === path && state.version === version
      ? state
      : { path, version, loading: !!path };

  return {
    ...currentState,
    refresh: useCallback(() => setVersion((v) => v + 1), []),
  };
}
export function params(
  values: Record<string, string | number | null | undefined>,
): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(values))
    if (value !== undefined && value !== null && value !== "")
      search.set(key, String(value));
  return search.toString();
}
export function clearPendingActions(): void {
  Object.keys(sessionStorage)
    .filter((k) => k.startsWith("dwellcall-action:"))
    .forEach((k) => sessionStorage.removeItem(k));
}
