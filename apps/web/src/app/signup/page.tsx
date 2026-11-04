import { redirect } from "next/navigation";
import { LoginForm } from "@/features/intelligence/login-form";
import { AuthLayout } from "@/features/account/auth-layout";
import { authReturnHref, parseAuthIntent, type AuthPageProps } from "@/features/account/auth-continuation";
import { currentAccount } from "@/lib/account-session";
export const metadata = { title: "Create your account", robots: { index: false, follow: false } };
export const dynamic = "force-dynamic";
export default async function SignupPage({ searchParams }: AuthPageProps) {
  const returnTo = parseAuthIntent((await searchParams).returnTo);
  if ((await currentAccount()).status === "authenticated") redirect(authReturnHref(returnTo));
  return <AuthLayout><p className="eyebrow">JOIN DWELLCALL</p><h2>Create your account.</h2><p className="muted">Workspace access requires owner approval after signup.</p><LoginForm mode="signup" returnTo={returnTo}/></AuthLayout>;
}
