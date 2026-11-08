from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from dwellcall.database.models.base import Base


class CallIntelligence(Base):
    __tablename__ = "call_intelligence"
    call_id: Mapped[UUID] = mapped_column(ForeignKey("outbound_calls.id", ondelete="RESTRICT"), primary_key=True)
    transcript_ciphertext: Mapped[str | None] = mapped_column(Text)
    transcript_hash: Mapped[str] = mapped_column(Text)
    analysis_ciphertext: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="pending")
    disposition: Mapped[str | None] = mapped_column(Text)
    analysis_model: Mapped[str | None] = mapped_column(Text)
    attempt_id: Mapped[UUID | None]
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
