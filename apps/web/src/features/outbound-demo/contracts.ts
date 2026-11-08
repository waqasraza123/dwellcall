export { scenarios, UUID_PATTERN, isOutboundCall as isDemoCall } from "@/features/outbound/contracts";
export type { Scenario as DemoScenario, OutboundCall as DemoCall } from "@/features/outbound/contracts";
import { UUID_PATTERN } from "@/features/outbound/contracts";

export type SmsChallenge = {
  challenge_id: string;
  expires_at: string;
  verified: boolean;
};

export function isSmsChallenge(value: unknown): value is SmsChallenge {
  if (typeof value !== "object" || value === null) return false;
  const challenge = value as Record<string, unknown>;
  return (
    typeof challenge.challenge_id === "string" &&
    UUID_PATTERN.test(challenge.challenge_id) &&
    typeof challenge.expires_at === "string" &&
    Number.isFinite(Date.parse(challenge.expires_at)) &&
    typeof challenge.verified === "boolean"
  );
}

