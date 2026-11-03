import { createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";

export const SESSION_COOKIE = process.env.NODE_ENV === "production" ? "__Host-dwellcall-operator" : "dwellcall-operator";
const ttl = 8 * 60 * 60;

function signingKey(): string {
  const key = process.env.DWELLCALL_SESSION_SECRET;
  if (!key || key.length < 32) throw new Error("Operator access is unavailable.");
  return key;
}
function equal(a: string, b: string): boolean {
  const first = createHash("sha256").update(a).digest();
  const second = createHash("sha256").update(b).digest();
  return timingSafeEqual(first, second);
}
export function validPassword(password: string): boolean {
  const expected = process.env.DWELLCALL_OPERATOR_PASSWORD;
  return !!expected && expected.length >= 32 && equal(password, expected);
}
export function issueSession(): string {
  const payload = Buffer.from(JSON.stringify({ expires: Math.floor(Date.now() / 1000) + ttl, nonce: randomBytes(24).toString("hex") })).toString("base64url");
  return payload + "." + createHmac("sha256", signingKey()).update(payload).digest("base64url");
}
export function verifySession(value: string | undefined): boolean {
  if (!value || value.length > 1024) return false;
  try {
    const [payload, signature, extra] = value.split(".");
    if (!payload || !signature || extra || !equal(signature, createHmac("sha256", signingKey()).update(payload).digest("base64url"))) return false;
    const data: unknown = JSON.parse(Buffer.from(payload, "base64url").toString());
    return typeof data === "object" && data !== null && "expires" in data && typeof data.expires === "number" && data.expires > Date.now() / 1000 && data.expires <= Date.now() / 1000 + ttl && "nonce" in data && typeof data.nonce === "string";
  } catch { return false; }
}
export async function authenticated(): Promise<boolean> {
  return verifySession((await cookies()).get(SESSION_COOKIE)?.value);
}
export const sessionOptions = { httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "strict" as const, path: "/", maxAge: ttl };
