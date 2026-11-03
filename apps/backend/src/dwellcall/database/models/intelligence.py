from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dwellcall.database.models.base import Base, UuidPrimaryKeyMixin


class ListingSource(Base):
    __tablename__ = "listing_sources"
    __table_args__ = (CheckConstraint("permission_version > 0", name="permission_version_valid"),)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    permission: Mapped[dict[str, object]] = mapped_column(JSONB)
    permission_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checkpoint: Mapped[str | None] = mapped_column(Text)


class ListingImportRun(UuidPrimaryKeyMixin, Base):
    __tablename__ = "listing_import_runs"
    __table_args__ = (UniqueConstraint("source_key", "request_id", name="uq_listing_import_request"),)
    source_key: Mapped[str] = mapped_column(ForeignKey("listing_sources.key", ondelete="RESTRICT"))
    request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    request_fingerprint: Mapped[str] = mapped_column(Text)
    permission_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_count: Mapped[int] = mapped_column(Integer)
    filters: Mapped[dict[str, object]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text)
    result: Mapped[dict[str, object]] = mapped_column(JSONB)


class ListingEntity(UuidPrimaryKeyMixin, Base):
    __tablename__ = "listing_entities"
    __table_args__ = (
        UniqueConstraint("data_mode", "listing_namespace", "listing_reference", name="uq_listing_strong_identity"),
        Index("ix_listing_entities_location", "state", "city"),
        CheckConstraint("data_mode IN ('synthetic','live')", name="mode_valid"),
        CheckConstraint("price > 0", name="price_valid"),
    )
    data_mode: Mapped[str] = mapped_column(Text)
    listing_namespace: Mapped[str | None] = mapped_column(Text)
    listing_reference: Mapped[str | None] = mapped_column(Text)
    address_key: Mapped[str | None] = mapped_column(Text, index=True)
    street_address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(Text)
    postal_code: Mapped[str | None] = mapped_column(Text)
    price: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    currency: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    property_type: Mapped[str | None] = mapped_column(Text)
    snapshot: Mapped[dict[str, object]] = mapped_column(JSONB)
    provenance: Mapped[dict[str, object]] = mapped_column(JSONB)
    winning_source: Mapped[str] = mapped_column(Text)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ListingObservation(UuidPrimaryKeyMixin, Base):
    __tablename__ = "listing_observations"
    __table_args__ = (UniqueConstraint("source_key", "source_listing_id", name="uq_listing_source_identity"),)
    source_key: Mapped[str] = mapped_column(ForeignKey("listing_sources.key", ondelete="RESTRICT"), index=True)
    source_listing_id: Mapped[str] = mapped_column(Text)
    listing_id: Mapped[UUID] = mapped_column(ForeignKey("listing_entities.id", ondelete="CASCADE"), index=True)
    snapshot: Mapped[dict[str, object]] = mapped_column(JSONB)
    fingerprint: Mapped[str] = mapped_column(Text)
    permission_version: Mapped[int] = mapped_column(Integer)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ListingRevision(UuidPrimaryKeyMixin, Base):
    __tablename__ = "listing_revisions"
    __table_args__ = (UniqueConstraint("observation_id", "fingerprint", name="uq_listing_revision_fingerprint"),)
    observation_id: Mapped[UUID] = mapped_column(ForeignKey("listing_observations.id", ondelete="CASCADE"))
    run_id: Mapped[UUID] = mapped_column(ForeignKey("listing_import_runs.id", ondelete="RESTRICT"))
    fingerprint: Mapped[str] = mapped_column(Text)
    snapshot: Mapped[dict[str, object]] = mapped_column(JSONB)
    events: Mapped[list[str]] = mapped_column(JSONB)
    provenance: Mapped[dict[str, object]] = mapped_column(JSONB)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ListingAgent(UuidPrimaryKeyMixin, Base):
    __tablename__ = "listing_agents"
    data_mode: Mapped[str] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(Text, index=True)
    brokerage: Mapped[str | None] = mapped_column(Text)
    normalized_brokerage: Mapped[str | None] = mapped_column(Text)
    review_required: Mapped[bool] = mapped_column(Boolean, default=False)
    suppressed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ListingAgentIdentity(UuidPrimaryKeyMixin, Base):
    __tablename__ = "listing_agent_identities"
    __table_args__ = (UniqueConstraint("data_mode", "namespace", "identifier", name="uq_agent_strong_identity"),)
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("listing_agents.id", ondelete="CASCADE"), index=True)
    data_mode: Mapped[str] = mapped_column(Text)
    namespace: Mapped[str] = mapped_column(Text)
    identifier: Mapped[str] = mapped_column(Text)


class ListingAgentObservation(UuidPrimaryKeyMixin, Base):
    __tablename__ = "listing_agent_observations"
    __table_args__ = (UniqueConstraint("observation_id", "agent_key", name="uq_agent_observation_key"),)
    observation_id: Mapped[UUID] = mapped_column(ForeignKey("listing_observations.id", ondelete="CASCADE"))
    agent_key: Mapped[str] = mapped_column(Text)
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("listing_agents.id", ondelete="CASCADE"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    snapshot: Mapped[dict[str, object]] = mapped_column(JSONB)
    provenance: Mapped[dict[str, object]] = mapped_column(JSONB)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ListingContactEvidence(UuidPrimaryKeyMixin, Base):
    __tablename__ = "listing_contact_evidence"
    __table_args__ = (
        UniqueConstraint("agent_observation_id", "fingerprint", name="uq_contact_evidence_fingerprint"),
        Index("ix_listing_contact_match", "kind", "value", "verification_status"),
    )
    agent_observation_id: Mapped[UUID] = mapped_column(ForeignKey("listing_agent_observations.id", ondelete="CASCADE"))
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("listing_agents.id", ondelete="CASCADE"))
    source_key: Mapped[str] = mapped_column(ForeignKey("listing_sources.key", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(Text)
    value: Mapped[str] = mapped_column(Text)
    direct: Mapped[bool] = mapped_column(Boolean)
    active: Mapped[bool] = mapped_column(Boolean)
    fingerprint: Mapped[str] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(Text)
    claimed_verification: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_reference: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    permission_version: Mapped[int] = mapped_column(Integer)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ListingReview(UuidPrimaryKeyMixin, Base):
    __tablename__ = "listing_identity_reviews"
    __table_args__ = (
        UniqueConstraint("source_key", "fingerprint", name="uq_listing_review_fingerprint"),
        CheckConstraint("status IN ('pending','approved','rejected')", name="listing_review_status_valid"),
    )
    source_key: Mapped[str] = mapped_column(ForeignKey("listing_sources.key", ondelete="RESTRICT"))
    source_listing_id: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(Text)
    candidate_ids: Mapped[list[str]] = mapped_column(JSONB)
    snapshot: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, default="pending")
    resolution: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ListingAuditEvent(UuidPrimaryKeyMixin, Base):
    __tablename__ = "listing_audit_events"
    source_key: Mapped[str] = mapped_column(ForeignKey("listing_sources.key", ondelete="RESTRICT"))
    event_type: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, object]] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
