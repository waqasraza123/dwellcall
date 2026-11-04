import Link from "next/link";
import { redirect } from "next/navigation";
import { AuthLayout } from "@/features/account/auth-layout";
import { SignOut } from "@/features/account/sign-out";
import { parseAuthIntent, authPageHref, authReturnHref, type AuthPageProps } from "@/features/account/auth-continuation";
import { currentAccount } from "@/lib/account-session";
export const metadata = { title: "Your account", robots: { index: false, follow: false } };
export const dynamic = "force-dynamic";
export default async function AccountPage({ searchParams }: AuthPageProps) {
  const intent = parseAuthIntent((await searchParams).returnTo);
  const account = await currentAccount();
  if (account.status === "anonymous") redirect(authPageHref("/login", intent));
  if (account.status === "unavailable") return <AuthLayout><h2>Account temporarily unavailable.</h2><p>Your session could not be checked. Please try again shortly.</p><Link href="/account">Try again</Link></AuthLayout>;
  if (account.status !== "authenticated") return null;
  if (account.user.operator_access) redirect(intent?.startsWith("billing") ? authReturnHref(intent) : intent === "conversation" ? "/#try-dwellcall" : "/dashboard");
  return <AuthLayout><p className="eyebrow">ACCOUNT CREATED</p><h2>You’re signed in.</h2><p>Workspace access is awaiting owner approval.</p><p className="muted">Account reference: <code>{account.user.id}</code></p><Link href={intent ? `/account?returnTo=${intent}` : "/account"}>Refresh access</Link><SignOut/></AuthLayout>;
}
