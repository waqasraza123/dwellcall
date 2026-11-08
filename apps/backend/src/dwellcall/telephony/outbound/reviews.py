import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import UUID

from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from dwellcall.database.models import Account, OutboundCall, OutboundSuppression
from dwellcall.database.models.call_intelligence import CallIntelligence
from dwellcall.database.models.call_lead_review import CallLeadReview, CallLeadReviewEvent
from dwellcall.errors import ApiError
from dwellcall.telephony.outbound.intelligence import LeadAssessment
from dwellcall.telephony.outbound.review_schemas import LeadReviewInput, LeadReviewRead, ReviewEventRead, TaskOutcome
from dwellcall.telephony.outbound.service import OutboundCallService


def blocked(code: str, message: str) -> ApiError:
    return ApiError(status_code=409, code=code, message=message)


class CallLeadReviewService:
    def __init__(self, calls: OutboundCallService) -> None:
        self.calls, self.sessions = calls, calls.sessions

    def _eligibility(self, session: Session, call: OutboundCall) -> tuple[list[str], str | None]:
        blockers: list[str] = []
        if not self.calls.settings.outbound_intelligence_enabled:
            blockers.append("Call intelligence is disabled.")
        if call.mock or call.call_purpose != "qualification":
            blockers.append("Demonstrations and simulated calls cannot become platform leads.")
        if call.finalized_at is None or not call.intelligence_consent:
            blockers.append("A completed call with transcript-analysis permission is required.")
        number = next((number for number in self.calls.settings.allowed_numbers if self.calls._hash("destination", number) == call.destination_hash), None)
        if number is None:
            blockers.append("The recipient is no longer on the approved calling list.")
        elif self.calls._suppressed(session, number):
            blockers.append("The recipient is suppressed or restricted from calling.")
        row = session.get(CallIntelligence, call.id)
        if row is None or row.status != "complete" or row.expires_at <= datetime.now(UTC) or not row.transcript_ciphertext or not row.analysis_ciphertext:
            return [*blockers, "A retained, unexpired transcript and completed assessment are required."], None
        try:
            transcript = json.loads(self.calls.intelligence._cipher().decrypt(row.transcript_ciphertext.encode()))
            assessment = LeadAssessment.model_validate_json(self.calls.intelligence._cipher().decrypt(row.analysis_ciphertext.encode()))
            user_turns = [turn["text"] for turn in transcript if turn["role"] == "user"]
            if assessment.disposition != "follow_up" or not assessment.follow_up_permission:
                blockers.append("The assessment does not establish a follow-up lead with permission.")
            quote = assessment.permission_quote
            if not quote or not any(quote in turn for turn in user_turns):
                blockers.append("Explicit follow-up permission must be supported by recipient words.")
            if not assessment.evidence_quotes or any(not quote or not any(quote in turn for turn in user_turns) for quote in assessment.evidence_quotes):
                blockers.append("Recipient evidence supporting this assessment is missing.")
            fingerprint = self.calls._hash("lead-assessment", row.transcript_hash + ":" + assessment.model_dump_json())
            return blockers, fingerprint
        except (InvalidToken, ValueError, TypeError, KeyError, ApiError):
            return [*blockers, "The retained evidence could not be read; review the encryption configuration."], None

    def _read(self, session: Session, call: OutboundCall) -> LeadReviewRead:
        review = session.get(CallLeadReview, call.id)
        blockers, fingerprint = self._eligibility(session, call)
        events = list(session.scalars(select(CallLeadReviewEvent).where(CallLeadReviewEvent.call_id == call.id).order_by(CallLeadReviewEvent.version.desc()).limit(25)))
        return LeadReviewRead(
            call_id=call.id,
            status=cast(Literal["unreviewed", "approved", "deferred", "rejected"], review.status if review else "unreviewed"),
            version=review.version if review else 0, eligible=not blockers, blockers=blockers,
            reviewed_at=review.reviewed_at if review else None,
            task_status=cast(Literal["none", "open", "completed", "cancelled"], review.task_status if review else "none"),
            task_actionable=bool(review and review.status == "approved" and review.task_status == "open" and not blockers and fingerprint == review.assessment_fingerprint),
            due_at=review.due_at if review else None, completed_at=review.completed_at if review else None,
            outcome=cast(TaskOutcome | None, review.outcome if review else None),
            recent_events=[ReviewEventRead(request_id=event.request_id, version=event.version, action=event.action, occurred_at=event.occurred_at, due_at=event.due_at, outcome=cast(TaskOutcome | None, event.outcome), review_status=event.review_status, task_status=event.task_status, evidence_reviewed=event.evidence_reviewed) for event in events],
        )

    def get(self, call_id: UUID) -> LeadReviewRead:
        with self.sessions() as session:
            return self._read(session, self.calls._row(session, call_id))

    def apply(self, call_id: UUID, actor_id: UUID, data: LeadReviewInput) -> LeadReviewRead:
        digest = self.calls._hash("lead-review", str(call_id) + ":" + str(actor_id) + ":" + data.model_dump_json())
        with self.sessions() as session, session.begin():
            self.calls._lock(session)
            actor = session.get(Account, actor_id, with_for_update=True)
            if actor is None or not actor.operator_access or actor.disabled_at is not None:
                raise ApiError(status_code=403, code="LEAD_REVIEW_OPERATOR_REQUIRED", message="An approved operator account is required")
            call = self.calls._row(session, call_id)
            event = session.get(CallLeadReviewEvent, data.request_id)
            if event is not None:
                if not hmac.compare_digest(event.request_hash, digest):
                    raise blocked("LEAD_REVIEW_KEY_CONFLICT", "This action key belongs to a different operation")
                return self._read(session, call)
            review = session.get(CallLeadReview, call_id, with_for_update=True)
            version = review.version if review else 0
            if version != data.expected_version:
                raise blocked("LEAD_REVIEW_CHANGED", "The lead changed; refresh its review before acting")
            blockers, fingerprint = self._eligibility(session, call)
            if data.action in {"approve", "schedule"} and blockers:
                raise blocked("LEAD_REVIEW_INELIGIBLE", "Current recipient permission, retained evidence and calling eligibility are required")
            now = datetime.now(UTC)
            if data.due_at is not None and not now < data.due_at <= now + timedelta(days=90):
                raise ApiError(status_code=422, code="LEAD_REVIEW_DUE_INVALID", message="Choose a future due date within 90 days")
            if data.action == "schedule":
                evidence = session.get(CallIntelligence, call_id)
                if evidence is None or data.due_at is None or data.due_at >= evidence.expires_at:
                    raise ApiError(status_code=422, code="LEAD_REVIEW_EVIDENCE_EXPIRY", message="Schedule the task before retained evidence expires")
            if review is None:
                if data.action not in {"approve", "defer", "reject"}:
                    raise blocked("LEAD_REVIEW_REQUIRED", "Review this lead before scheduling or recording a task")
                review = CallLeadReview(call_id=call_id, status="deferred", version=0, task_status="none", reviewed_by=actor_id, reviewed_at=now)
                session.add(review)
            if data.action == "approve":
                if review.task_status == "open":
                    raise blocked("LEAD_TASK_OPEN", "Complete or cancel the existing task before approving again")
                review.status, review.assessment_fingerprint = "approved", fingerprint
                review.task_status, review.due_at, review.completed_at, review.outcome = "none", None, None, None
            elif data.action in {"defer", "reject"}:
                review.status = "deferred" if data.action == "defer" else "rejected"
                if review.task_status == "open":
                    review.task_status = "cancelled"
                    review.completed_at = now
                    review.outcome = None
                review.due_at = data.due_at
                review.assessment_fingerprint = None
            elif data.action == "schedule":
                if review.status != "approved" or review.assessment_fingerprint != fingerprint:
                    raise blocked("LEAD_REVIEW_REQUIRED", "Approve the current assessment before scheduling")
                if review.task_status != "none":
                    raise blocked("LEAD_REVIEW_REQUIRED", "Approve again before scheduling another task")
                review.task_status, review.due_at = "open", data.due_at
                review.completed_at, review.outcome = None, None
            elif data.action in {"complete", "cancel"}:
                if review.task_status != "open":
                    raise blocked("LEAD_TASK_NOT_OPEN", "Only an open task can be completed or cancelled")
                review.task_status = "completed" if data.action == "complete" else "cancelled"
                review.completed_at = now
                review.outcome = data.outcome
                if data.outcome in {"not_interested", "do_not_contact", "closed"}:
                    review.status, review.assessment_fingerprint = "rejected", None
                if data.outcome == "do_not_contact" and session.get(OutboundSuppression, call.destination_hash) is None:
                    session.add(OutboundSuppression(destination_hash=call.destination_hash, created_at=now))
            review.version, review.reviewed_by, review.reviewed_at = version + 1, actor_id, now
            session.add(CallLeadReviewEvent(request_id=data.request_id, call_id=call_id, actor_id=actor_id, request_hash=digest,
                version=review.version, action=data.action, occurred_at=now, review_status=review.status, task_status=review.task_status, due_at=review.due_at, outcome=review.outcome, evidence_reviewed=data.evidence_reviewed))
            session.flush()
            return self._read(session, call)

    def tasks(self, status: Literal["open", "completed", "cancelled", "deferred"] = "open") -> list[dict[str, object]]:
        with self.sessions() as session:
            query = select(OutboundCall).join(CallLeadReview, CallLeadReview.call_id == OutboundCall.id)
            query = query.where(CallLeadReview.status == "deferred") if status == "deferred" else query.where(CallLeadReview.task_status == status)
            calls = list(session.scalars(query.order_by(CallLeadReview.due_at.asc().nulls_last(), CallLeadReview.reviewed_at.desc()).limit(100)))
            return [{"call": self.calls._response(call).model_dump(mode="json"), "review": self._read(session, call).model_dump(mode="json")} for call in calls]
