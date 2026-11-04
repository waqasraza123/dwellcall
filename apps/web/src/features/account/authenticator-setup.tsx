"use client";
import { QRCodeSVG } from "qrcode.react";
import type { MfaSetup } from "./mfa-setup";
export function AuthenticatorSetup({ setup }: { setup: MfaSetup }) {
  return <div><p>Add DwellCall in your authenticator app by scanning this code.</p><QRCodeSVG value={setup.otpauthUri} size={208} level="M" marginSize={4} bgColor="#ffffff" fgColor="#18181b" role="img" title="Scan to add DwellCall to your authenticator"/><details><summary>Enter a setup key instead</summary><p>Choose manual entry, name the account DwellCall, and select a time-based key.</p><code aria-label="Authenticator setup key">{setup.secret}</code><p className="muted">Keep this key private, just like your password.</p></details></div>;
}
