from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from dwellcall.database.models.base import Base


class BillingAccount(Base):
    __tablename__ = "billing_accounts"
    __table_args__ = (CheckConstraint("plan IN ('free','pro','team')", name="plan_valid"),)

    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), primary_key=True)
    customer_id: Mapped[str | None] = mapped_column(Text, unique=True)
    customer_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    livemode: Mapped[bool] = mapped_column(Boolean, nullable=False)
    subscription_id: Mapped[str | None] = mapped_column(Text, unique=True)
    price_id: Mapped[str | None] = mapped_column(Text)
    plan: Mapped[str] = mapped_column(Text, nullable=False, default="free")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="none")
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_through: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BillingCheckout(Base):
    __tablename__ = "billing_checkouts"
    __table_args__ = (
        CheckConstraint("plan IN ('pro','team')", name="plan_valid"),
        CheckConstraint("status IN ('creating','open','complete','expired')", name="status_valid"),
        Index("ix_billing_checkouts_account_created", "account_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False)
    plan: Mapped[str] = mapped_column(Text, nullable=False)
    session_id: Mapped[str | None] = mapped_column(Text, unique=True)
    url: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="creating")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BillingEvent(Base):
    __tablename__ = "billing_events"
    __table_args__ = (Index("ix_billing_events_pending", "account_id", "processed_at"),)

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    customer_id: Mapped[str] = mapped_column(Text, nullable=False)
    object_id: Mapped[str] = mapped_column(Text, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
