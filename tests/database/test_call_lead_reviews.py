from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from dwellcall.database.models import Account, OutboundCall, OutboundSuppression
from dwellcall.database.models.call_intelligence import CallIntelligence
from dwellcall.database.models.call_lead_review import CallLeadReviewEvent
from dwellcall.errors import ApiError
from dwellcall.telephony.outbound.review_schemas import LeadReviewInput
from dwellcall.telephony.outbound.reviews import CallLeadReviewService
from tests.database.test_call_intelligence import assessment, prepare


def setup_review(sessions, outbound_settings):
    calls, result = prepare(sessions, outbound_settings)
    calls.intelligence.capture(result.id, [{"role": "user", "message": "Please contact me about DwellCall."}])
    with sessions() as session, session.begin():
        row = session.get(CallIntelligence, result.id)
        row.analysis_ciphertext = calls.intelligence._cipher().encrypt(assessment().model_dump_json().encode()).decode()
        row.status, row.disposition = "complete", "follow_up"
        operator_id = uuid4()
        session.add(Account(id=operator_id, full_name="Synthetic operator", email=f"{operator_id}@example.test", password_hash="synthetic-unused", operator_access=True, created_at=datetime.now(UTC)))
    return CallLeadReviewService(calls), result.id, operator_id


def action(name="approve", version=0, **updates):
    return LeadReviewInput.model_validate({"request_id": str(uuid4()), "expected_version": version, "action": name, "evidence_reviewed": True, **updates})


def test_approval_replay_is_idempotent_and_stale_decisions_are_fenced(sessions, outbound_settings):
    reviews, call_id, operator_id = setup_review(sessions, outbound_settings)
    request = action()
    approved = reviews.apply(call_id, operator_id, request)
    assert approved.status == "approved" and approved.version == 1
    assert reviews.apply(call_id, operator_id, request).version == 1
    with pytest.raises(ApiError) as caught:
        reviews.apply(call_id, operator_id, action("reject"))
    assert caught.value.code == "LEAD_REVIEW_CHANGED"
    with pytest.raises(ApiError) as caught:
        reviews.apply(call_id, operator_id, action("reject", request_id=request.request_id))
    assert caught.value.code == "LEAD_REVIEW_KEY_CONFLICT"
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(CallLeadReviewEvent)) == 1


def test_concurrent_identical_requests_record_one_event(sessions, outbound_settings):
    reviews, call_id, operator_id = setup_review(sessions, outbound_settings)
    request = action()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reviews.apply(call_id, operator_id, request), range(2)))
    assert [r.version for r in results] == [1, 1]


def test_schedule_completion_records_dnc_and_keeps_action_evidence(sessions, outbound_settings):
    reviews, call_id, operator_id = setup_review(sessions, outbound_settings)
    reviews.apply(call_id, operator_id, action())
    due = datetime.now(UTC) + timedelta(hours=1)
    task = reviews.apply(call_id, operator_id, action("schedule", 1, due_at=due))
    assert task.task_status == "open" and task.task_actionable
    assert len(reviews.tasks()) == 1
    complete = action("complete", 2, outcome="do_not_contact")
    result = reviews.apply(call_id, operator_id, complete)
    assert result.status == "rejected" and result.task_status == "completed"
    assert not result.eligible and not result.task_actionable
    assert reviews.apply(call_id, operator_id, complete).version == 3
    with sessions() as session:
        call = session.get(OutboundCall, call_id)
        assert session.get(OutboundSuppression, call.destination_hash)
        events = list(session.scalars(select(CallLeadReviewEvent).order_by(CallLeadReviewEvent.version)))
        assert events[1].due_at == due and events[2].outcome == "do_not_contact"


@pytest.mark.parametrize("change", ["suppressed", "expired", "demo", "disabled", "missing_permission"])
def test_ineligible_evidence_never_approves(sessions, outbound_settings, change):
    reviews, call_id, operator_id = setup_review(sessions, outbound_settings)
    with sessions() as session, session.begin():
        call = session.get(OutboundCall, call_id)
        row = session.get(CallIntelligence, call_id)
        if change == "suppressed":
            session.add(OutboundSuppression(destination_hash=call.destination_hash, created_at=datetime.now(UTC)))
        elif change == "expired":
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        elif change == "demo":
            call.call_purpose = "demonstration"
        elif change == "disabled":
            session.get(Account, operator_id).disabled_at = datetime.now(UTC)
        else:
            row.analysis_ciphertext = reviews.calls.intelligence._cipher().encrypt(assessment(permission_quote="Fabricated statement").model_dump_json().encode()).decode()
    with pytest.raises(ApiError) as caught:
        reviews.apply(call_id, operator_id, action())
    assert caught.value.code in {"LEAD_REVIEW_INELIGIBLE", "LEAD_REVIEW_OPERATOR_REQUIRED"}


def test_expired_evidence_blocks_open_task_and_defer_cancels_it(sessions, outbound_settings):
    reviews, call_id, operator_id = setup_review(sessions, outbound_settings)
    reviews.apply(call_id, operator_id, action())
    reviews.apply(call_id, operator_id, action("schedule", 1, due_at=datetime.now(UTC) + timedelta(hours=1)))
    with sessions() as session, session.begin():
        session.get(CallIntelligence, call_id).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert not reviews.get(call_id).task_actionable
    deferred = reviews.apply(call_id, operator_id, action("defer", 2, due_at=datetime.now(UTC) + timedelta(days=1)))
    assert deferred.status == "deferred" and deferred.task_status == "cancelled"
    assert reviews.tasks() == [] and len(reviews.tasks("deferred")) == 1


def test_schedule_requires_approval_and_due_before_evidence_expiry(sessions, outbound_settings):
    reviews, call_id, operator_id = setup_review(sessions, outbound_settings)
    with pytest.raises(ApiError):
        reviews.apply(call_id, operator_id, action("schedule", due_at=datetime.now(UTC) + timedelta(hours=1)))
    reviews.apply(call_id, operator_id, action())
    with sessions() as session, session.begin():
        session.get(CallIntelligence, call_id).expires_at = datetime.now(UTC) + timedelta(minutes=10)
    with pytest.raises(ApiError) as caught:
        reviews.apply(call_id, operator_id, action("schedule", 1, due_at=datetime.now(UTC) + timedelta(hours=1)))
    assert caught.value.code == "LEAD_REVIEW_EVIDENCE_EXPIRY"
