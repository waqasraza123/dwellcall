from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from dwellcall.database.models.base import Base, UuidPrimaryKeyMixin


class Account(UuidPrimaryKeyMixin, Base):
    __tablename__ = "accounts"

    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    operator_access: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AccountLoginSession(UuidPrimaryKeyMixin, Base):
    __tablename__ = "account_login_sessions"
    __table_args__ = (CheckConstraint(
        "(mfa_verified_at IS NULL AND mfa_version IS NULL) OR "
        "(mfa_verified_at IS NOT NULL AND mfa_version IS NOT NULL AND mfa_version > 0)",
        name="mfa_consistent",
    ),)

    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_version: Mapped[int | None] = mapped_column(Integer)


class AccountAuthLimit(Base):
    __tablename__ = "account_auth_limits"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AccountAuthEvent(UuidPrimaryKeyMixin, Base):
    __tablename__ = "account_auth_events"

    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
