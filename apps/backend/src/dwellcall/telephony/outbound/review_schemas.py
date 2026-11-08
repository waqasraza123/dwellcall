from datetime import UTC, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ReviewAction = Literal["approve", "defer", "reject", "schedule", "complete", "cancel"]
TaskOutcome = Literal["contacted", "no_answer", "not_interested", "do_not_contact", "closed"]


class LeadReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    request_id: UUID
    expected_version: int = Field(ge=0, strict=True)
    action: ReviewAction
    evidence_reviewed: bool = Field(default=False, strict=True)
    due_at: datetime | None = None
    outcome: TaskOutcome | None = None

    @field_validator("due_at")
    @classmethod
    def utc_date(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Include the time zone for the due date")
            return value.astimezone(UTC)
        return None

    @model_validator(mode="after")
    def valid_action(self) -> Self:
        if self.action in {"approve", "schedule"} and not self.evidence_reviewed:
            raise ValueError("Review the transcript and explicit follow-up permission first")
        if self.action == "schedule" and self.due_at is None:
            raise ValueError("Choose a due date for the local follow-up task")
        if self.action not in {"schedule", "defer"} and self.due_at is not None:
            raise ValueError("A due date applies only to scheduling or deferral")
        if (self.action == "complete") != (self.outcome is not None):
            raise ValueError("A completed task requires a recorded outcome")
        return self


class ReviewEventRead(BaseModel):
    request_id: UUID
    version: int
    action: str
    occurred_at: datetime
    due_at: datetime | None
    outcome: TaskOutcome | None
    review_status: str
    task_status: str
    evidence_reviewed: bool


class LeadReviewRead(BaseModel):
    call_id: UUID
    status: Literal["unreviewed", "approved", "deferred", "rejected"]
    version: int
    eligible: bool
    blockers: list[str]
    reviewed_at: datetime | None
    task_status: Literal["none", "open", "completed", "cancelled"]
    task_actionable: bool
    due_at: datetime | None
    completed_at: datetime | None
    outcome: TaskOutcome | None
    recent_events: list[ReviewEventRead]
