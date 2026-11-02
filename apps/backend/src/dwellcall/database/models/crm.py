from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dwellcall.database.models.base import Base, UuidPrimaryKeyMixin


class CrmDispatchState(Base):
    __tablename__ = "crm_dispatch_state"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paused_destination: Mapped[str | None] = mapped_column(Text)


class CrmExport(UuidPrimaryKeyMixin, Base):
    __tablename__ = "crm_exports"
    __table_args__ = (
        UniqueConstraint("call_id", "snapshot_version", "provider", "destination", name="uq_crm_export_scope"),
        CheckConstraint("snapshot_version > 0", name="version_valid"),
        CheckConstraint("provider = 'followupboss'", name="provider_valid"),
        CheckConstraint("attempts >= 0", name="attempts_valid"),
        CheckConstraint("status IN ('pending','sending','retry_wait','sent','unknown','failed','ignored','cancelled')", name="status_valid"),
        Index("ix_crm_exports_due", "status", "next_attempt_at"),
    )

    call_id: Mapped[str] = mapped_column(ForeignKey("audio_sessions.call_id", ondelete="RESTRICT"))
    snapshot_version: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(Text)
    destination: Mapped[str] = mapped_column(Text)
    request_fingerprint: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    consent_version: Mapped[str] = mapped_column(Text)
    permission_reference: Mapped[str] = mapped_column(Text)
    permission_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    permission_revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retain_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_code: Mapped[str | None] = mapped_column(Text)
    person_id: Mapped[int | None] = mapped_column(Integer)


class CrmAuditEvent(UuidPrimaryKeyMixin, Base):
    __tablename__ = "crm_audit_events"

    export_id: Mapped[UUID | None] = mapped_column(ForeignKey("crm_exports.id", ondelete="RESTRICT"))
    event_type: Mapped[str] = mapped_column(Text)
    evidence_reference: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
