from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dwellcall.database.models.base import Base, UuidPrimaryKeyMixin


class DiscoveryJob(UuidPrimaryKeyMixin, Base):
    __tablename__ = "discovery_jobs"
    name: Mapped[str] = mapped_column(Text)
    source_key: Mapped[str] = mapped_column(ForeignKey("listing_sources.key", ondelete="RESTRICT"))
    enabled: Mapped[bool] = mapped_column(Boolean)
    filters: Mapped[dict[str, object]] = mapped_column(JSONB)
    poll_interval_minutes: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DiscoveryAttempt(UuidPrimaryKeyMixin, Base):
    __tablename__ = "discovery_attempts"
    job_id: Mapped[UUID] = mapped_column(ForeignKey("discovery_jobs.id", ondelete="RESTRICT"), index=True)
    request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), unique=True)
    status: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    code: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, object]] = mapped_column(JSONB)


class OperatorAction(Base):
    __tablename__ = "operator_actions"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
