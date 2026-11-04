from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from dwellcall.database.models.base import Base


class AudioAdmissionGuard(Base):
    __tablename__ = "audio_admission_guard"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    outbound_paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    transfer_paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class AudioSession(Base):
    __tablename__ = "audio_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('active','unknown','ended')", name="status_valid"),
        CheckConstraint("reserved_cost_cents >= 0", name="cost_valid"),
        Index("ix_audio_sessions_created", "created_at"),
    )

    call_id: Mapped[str] = mapped_column(Text, primary_key=True)
    agent_id: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reserved_cost_cents: Mapped[int] = mapped_column(Integer)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
