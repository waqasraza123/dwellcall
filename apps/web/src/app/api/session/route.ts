import { NextRequest } from "next/server";
import { POST as accountAction } from "../account/[action]/route";

export const runtime = "nodejs";
export function POST(request: NextRequest) {
  return accountAction(request, { params: Promise.resolve({ action: "login" }) });
}
export function DELETE(request: NextRequest) {
  return accountAction(new NextRequest(request.url, { method: "POST", headers: request.headers, body: "{}" }), { params: Promise.resolve({ action: "logout" }) });
}
