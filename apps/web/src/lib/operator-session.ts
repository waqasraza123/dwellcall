import { currentAccount } from "./account-session";

export async function authenticated(): Promise<boolean> {
  const account = await currentAccount();
  return account.status === "authenticated" && account.user.operator_access;
}
