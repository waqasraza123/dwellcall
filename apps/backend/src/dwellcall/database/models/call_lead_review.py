from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from dwellcall.database.models.base import Base


class CallLeadReview(Base):
    __tablename__ = "call_lead_reviews"
    __table_args__ = (
        CheckConstraint("status IN ('approved','deferred','rejected')", name="status_valid"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("task_status IN ('none','open','completed','cancelled')", name="task_status_valid"),
        CheckConstraint("task_status != 'open' OR (status = 'approved' AND due_at IS NOT NULL)", name="open_task_consistent"),
        Index("ix_call_lead_reviews_task_due", "task_status", "due_at"),
    )
    call_id: Mapped[UUID] = mapped_column(ForeignKey("outbound_calls.id", ondelete="RESTRICT"), primary_key=True)
    status: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    reviewed_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    assessment_fingerprint: Mapped[str | None] = mapped_column(Text)
    task_status: Mapped[str] = mapped_column(Text, default="none")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CallLeadReviewEvent(Base):
    __tablename__ = "call_lead_review_events"
    __table_args__ = (Index("ix_call_lead_review_events_call_version", "call_id", "version", unique=True),)
    request_id: Mapped[UUID] = mapped_column(primary_key=True)
    call_id: Mapped[UUID] = mapped_column(ForeignKey("outbound_calls.id", ondelete="RESTRICT"))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    request_hash: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    review_status: Mapped[str] = mapped_column(Text)
    task_status: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(Text)
    evidence_reviewed: Mapped[bool] = mapped_column(Boolean)
