from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from dwellcall.telephony.outbound.review_schemas import LeadReviewInput


def mutation(**updates):
    return LeadReviewInput.model_validate({"request_id": str(uuid4()), "expected_version": 0, "action": "approve", "evidence_reviewed": True, **updates})


@pytest.mark.parametrize("updates", [
    {"evidence_reviewed": False}, {"evidence_reviewed": "true"}, {"expected_version": True},
    {"action": "schedule"}, {"action": "complete"}, {"action": "reject", "outcome": "contacted"},
    {"action": "schedule", "due_at": "2026-12-01T10:00:00"}, {"actor_id": str(uuid4())},
])
def test_review_requires_explicit_evidence_and_action_specific_inputs(updates):
    with pytest.raises(ValidationError):
        mutation(**updates)


def test_due_date_keeps_one_canonical_timezone():
    value = mutation(action="schedule", due_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat())
    assert value.due_at.tzinfo == UTC
