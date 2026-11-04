export type AuthIntent = "conversation" | undefined;
export type AuthPageProps = { searchParams: Promise<{ returnTo?: string | string[] }> };
export function parseAuthIntent(value: unknown): AuthIntent {
  return value === "conversation" ? "conversation" : undefined;
}
export function authPageHref(path: "/login" | "/signup" | "/mfa", intent?: AuthIntent): string {
  return intent ? `${path}?returnTo=conversation` : path;
}
export function authReturnHref(intent?: AuthIntent): string {
  return intent ? "/account?returnTo=conversation" : "/account";
}
