import { UUID_PATTERN } from "./contracts";

export const reviewActions = ["approve", "defer", "reject", "schedule", "complete", "cancel"] as const;
export const taskOutcomes = ["contacted", "no_answer", "not_interested", "do_not_contact", "closed"] as const;
export type ReviewAction = typeof reviewActions[number];
export type TaskOutcome = typeof taskOutcomes[number];
export type ReviewMutation = {
  request_id: string; expected_version: number; action: ReviewAction; evidence_reviewed: boolean;
  due_at: string | null; outcome: TaskOutcome | null;
};
export type LeadReview = {
  call_id: string; status: "unreviewed" | "approved" | "deferred" | "rejected"; version: number;
  eligible: boolean; blockers: string[]; reviewed_at: string | null;
  task_status: "none" | "open" | "completed" | "cancelled"; task_actionable: boolean;
  due_at: string | null; completed_at: string | null; outcome: TaskOutcome | null;
  recent_events: { request_id: string; version: number; action: string; occurred_at: string }[];
};
const timestamp = (value: unknown): value is string => typeof value === "string" && Number.isFinite(Date.parse(value));
const nullableTime = (value: unknown) => value === null || timestamp(value);
export function isLeadReview(value: unknown): value is LeadReview {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return typeof v.call_id === "string" && UUID_PATTERN.test(v.call_id)
    && typeof v.status === "string" && ["unreviewed", "approved", "deferred", "rejected"].includes(v.status)
    && Number.isSafeInteger(v.version) && Number(v.version) >= 0
    && typeof v.eligible === "boolean" && Array.isArray(v.blockers) && v.blockers.every(s => typeof s === "string")
    && typeof v.task_status === "string" && ["none", "open", "completed", "cancelled"].includes(v.task_status)
    && typeof v.task_actionable === "boolean" && nullableTime(v.reviewed_at) && nullableTime(v.due_at) && nullableTime(v.completed_at)
    && (v.outcome === null || taskOutcomes.some(s => s === v.outcome))
    && Array.isArray(v.recent_events) && v.recent_events.every(e => e && typeof e === "object" && typeof e.request_id === "string" && UUID_PATTERN.test(e.request_id) && Number.isSafeInteger(e.version) && e.version > 0 && reviewActions.includes(e.action) && timestamp(e.occurred_at));
}
export function isReviewMutation(value: unknown): value is ReviewMutation {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return typeof v.request_id === "string" && UUID_PATTERN.test(v.request_id)
    && Number.isSafeInteger(v.expected_version) && Number(v.expected_version) >= 0
    && reviewActions.some(s => s === v.action) && typeof v.evidence_reviewed === "boolean"
    && nullableTime(v.due_at) && (v.outcome === null || taskOutcomes.some(s => s === v.outcome));
}
