import { redirect } from "next/navigation";
import { LoginForm } from "@/features/intelligence/login-form";
import { AuthLayout } from "@/features/account/auth-layout";
import { authReturnHref, parseAuthIntent, type AuthPageProps } from "@/features/account/auth-continuation";
import { currentAccount } from "@/lib/account-session";
export const metadata = { title: "Sign in", robots: { index: false, follow: false } };
export const dynamic = "force-dynamic";
export default async function LoginPage({ searchParams }: AuthPageProps) {
  const returnTo = parseAuthIntent((await searchParams).returnTo);
  if ((await currentAccount()).status === "authenticated") redirect(authReturnHref(returnTo));
  return <AuthLayout><p className="eyebrow">ACCOUNT ACCESS</p><h2>Welcome back.</h2><p className="muted">Your market intelligence starts here.</p><LoginForm returnTo={returnTo}/></AuthLayout>;
}
