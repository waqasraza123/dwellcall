"""DwellCall account subscriptions, checkout reservations and Stripe receipts."""
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision = "20261105_0011"
down_revision = "20261105_0010"
branch_labels = None
depends_on = None


def account(*, primary: bool = False) -> sa.Column[UUID]:
    return sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, primary_key=primary)


def upgrade() -> None:
    op.create_table(
        "billing_accounts", account(primary=True),
        sa.Column("customer_id", sa.Text(), unique=True),
        sa.Column("customer_started_at", sa.DateTime(timezone=True)),
        sa.Column("livemode", sa.Boolean(), nullable=False),
        sa.Column("subscription_id", sa.Text(), unique=True),
        sa.Column("price_id", sa.Text()),
        sa.Column("plan", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True)),
        sa.Column("period_end", sa.DateTime(timezone=True)),
        sa.Column("paid_through", sa.DateTime(timezone=True)),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("plan IN ('free','pro','team')", name="plan_valid"),
    )
    op.create_table(
        "billing_checkouts",
        sa.Column("id", sa.Uuid(), primary_key=True), account(),
        sa.Column("plan", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text(), unique=True),
        sa.Column("url", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("plan IN ('pro','team')", name="plan_valid"),
        sa.CheckConstraint("status IN ('creating','open','complete','expired')", name="status_valid"),
    )
    op.create_index("ix_billing_checkouts_account_created", "billing_checkouts", ["account_id", "created_at"])
    op.create_table(
        "billing_events",
        sa.Column("event_id", sa.Text(), primary_key=True), account(),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column("object_id", sa.Text(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_billing_events_pending", "billing_events", ["account_id", "processed_at"])


def downgrade() -> None:
    raise RuntimeError("Retain billing customer bindings, checkout reservations and Stripe receipts")
