import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { AuthLayout } from "@/features/account/auth-layout";
import { AccountMfaForm } from "@/features/account/mfa-form";
import { authPageHref, parseAuthIntent, type AuthPageProps } from "@/features/account/auth-continuation";
import { MFA_COOKIE } from "@/lib/account-session";
export const metadata = { title: "Authenticator verification", robots: { index: false, follow: false } };
export const dynamic = "force-dynamic";
export default async function MfaPage({ searchParams }: AuthPageProps) {
  const intent = parseAuthIntent((await searchParams).returnTo);
  if (!(await cookies()).has(MFA_COOKIE)) redirect(authPageHref("/login", intent));
  return <AuthLayout><AccountMfaForm intent={intent}/></AuthLayout>;
}
