export type AuthIntent = "conversation" | "billing" | "billing-pro" | "billing-team" | undefined;
export type AuthPageProps = { searchParams: Promise<{ returnTo?: string | string[] }> };
export function parseAuthIntent(value: unknown): AuthIntent {
  return value === "conversation" || value === "billing" || value === "billing-pro" || value === "billing-team" ? value : undefined;
}
export function authPageHref(path: "/login" | "/signup" | "/mfa", intent?: AuthIntent): string {
  return intent ? `${path}?returnTo=${intent}` : path;
}
export function authReturnHref(intent?: AuthIntent): string {
  if (intent === "billing-pro" || intent === "billing-team") return `/billing?plan=${intent.slice(8)}`;
  if (intent === "billing") return "/billing";
  return intent ? "/account?returnTo=conversation" : "/account";
}
