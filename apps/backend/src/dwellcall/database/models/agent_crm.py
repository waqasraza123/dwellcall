from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dwellcall.database.models.base import Base, UuidPrimaryKeyMixin


class AgentCrmDestination(Base):
    __tablename__ = "agent_crm_destinations"
    destination: Mapped[str] = mapped_column(Text, primary_key=True)
    fields: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    capabilities: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    configured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentCrmLink(UuidPrimaryKeyMixin, Base):
    __tablename__ = "agent_crm_links"
    __table_args__ = (
        UniqueConstraint("agent_id", "destination", name="uq_agent_crm_link"),
        UniqueConstraint("destination", "contact_id", name="uq_agent_crm_contact"),
    )
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("listing_agents.id", ondelete="RESTRICT"), index=True)
    destination: Mapped[str] = mapped_column(ForeignKey("agent_crm_destinations.destination", ondelete="RESTRICT"))
    contact_id: Mapped[str | None] = mapped_column(Text)
    opportunity_id: Mapped[str | None] = mapped_column(Text)
    company_id: Mapped[str | None] = mapped_column(Text)
    synced_fingerprint: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentCrmJob(UuidPrimaryKeyMixin, Base):
    __tablename__ = "agent_crm_jobs"
    __table_args__ = (
        UniqueConstraint("link_id", "fingerprint", name="uq_agent_crm_job"),
        CheckConstraint("status IN ('pending','sending','retry_wait','sent','unknown','failed','cancelled')", name="agent_job_status_valid"),
        Index("ix_agent_crm_jobs_due", "status", "next_attempt_at"),
    )
    link_id: Mapped[UUID] = mapped_column(ForeignKey("agent_crm_links.id", ondelete="RESTRICT"))
    fingerprint: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    fields: Mapped[dict[str, str]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    attempt_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    retain_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    code: Mapped[str | None] = mapped_column(Text)


class AgentCrmAudit(UuidPrimaryKeyMixin, Base):
    __tablename__ = "agent_crm_audits"
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_crm_jobs.id", ondelete="RESTRICT"))
    destination: Mapped[str] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(Text)
    evidence_reference: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
