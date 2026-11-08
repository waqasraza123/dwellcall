from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from dwellcall.database.models.base import Base, UuidPrimaryKeyMixin


class OutboundCall(UuidPrimaryKeyMixin, Base):
    __tablename__ = "outbound_calls"
    __table_args__ = (
        CheckConstraint("status IN ('reserved','dialing','ringing','in_progress','completed','rejected','unanswered','failed','unknown','transferred','transfer_unconfirmed')", name="status_valid"),
        CheckConstraint("transfer_status IN ('not_requested','requested','refer_accepted','failed','unconfirmed')", name="transfer_valid"),
        CheckConstraint("reserved_cost_cents > 0", name="cost_positive"),
        CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="duration_valid"),
        Index("ix_outbound_calls_created", "created_at"),
        Index("ix_outbound_calls_destination_created", "destination_hash", "created_at"),
    )
    call_purpose: Mapped[str] = mapped_column(Text, default="demonstration", server_default="demonstration")
    intelligence_consent: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    provider: Mapped[str] = mapped_column(Text, default="retell", server_default="retell")
    owner_hash: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[UUID] = mapped_column(unique=True)
    request_hash: Mapped[str] = mapped_column(Text)
    destination_hash: Mapped[str] = mapped_column(Text)
    audio_session_id: Mapped[str] = mapped_column(ForeignKey("audio_sessions.call_id", ondelete="RESTRICT"), unique=True)
    agent_id: Mapped[str] = mapped_column(Text)
    agent_version: Mapped[int] = mapped_column(Integer)
    caller_hash: Mapped[str] = mapped_column(Text)
    scenario: Mapped[str] = mapped_column(Text)
    consent_version: Mapped[str] = mapped_column(Text)
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    send_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_call_id: Mapped[str | None] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(Text)
    transfer_status: Mapped[str] = mapped_column(Text, default="not_requested")
    socket_admitted: Mapped[bool] = mapped_column(Boolean, default=False)
    carrier_end_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    mock: Mapped[bool] = mapped_column(Boolean, default=False)
    reserved_cost_cents: Mapped[int] = mapped_column(Integer)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(Text)
    transfer_confirmation_hash: Mapped[str | None] = mapped_column(Text)


class OutboundCallEvent(UuidPrimaryKeyMixin, Base):
    __tablename__ = "outbound_call_events"
    call_id: Mapped[UUID] = mapped_column(ForeignKey("outbound_calls.id", ondelete="RESTRICT"), index=True)
    fingerprint: Mapped[str] = mapped_column(Text, unique=True)
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OutboundSuppression(Base):
    __tablename__ = "outbound_suppressions"
    destination_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
