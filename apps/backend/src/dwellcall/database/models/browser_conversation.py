from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from dwellcall.database.models.base import Base, UuidPrimaryKeyMixin


class BrowserConversation(UuidPrimaryKeyMixin, Base):
    __tablename__ = "browser_conversations"
    __table_args__ = (
        CheckConstraint("mode IN ('voice','text')", name="mode_valid"),
        CheckConstraint("scenario IN ('renting','buying','luxury')", name="scenario_valid"),
        CheckConstraint("turn_count >= 0", name="turn_count_valid"),
    )
    owner_hash: Mapped[str] = mapped_column(Text, index=True)
    audio_session_id: Mapped[str] = mapped_column(ForeignKey("audio_sessions.call_id", ondelete="RESTRICT"), unique=True)
    mode: Mapped[str] = mapped_column(Text)
    scenario: Mapped[str] = mapped_column(Text)
    agent_id: Mapped[str] = mapped_column(Text)
    agent_version: Mapped[int] = mapped_column(Integer)
    mock: Mapped[bool] = mapped_column(Boolean)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    turn_in_flight: Mapped[bool] = mapped_column(Boolean, default=False)
    socket_admitted: Mapped[bool] = mapped_column(Boolean, default=False)
    send_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_call_id: Mapped[str | None] = mapped_column(Text, unique=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
