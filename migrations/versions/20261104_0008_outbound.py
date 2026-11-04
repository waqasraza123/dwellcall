"""Durable outbound reservations on the shared audio admission guard."""
from alembic import op
import sqlalchemy as sa

revision = "20261104_0008"
down_revision = "20261104_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audio_admission_guard", sa.Column("outbound_paused", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("audio_admission_guard", sa.Column("transfer_paused", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "outbound_calls",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("request_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("destination_hash", sa.Text(), nullable=False),
        sa.Column("audio_session_id", sa.Text(), sa.ForeignKey("audio_sessions.call_id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("agent_version", sa.Integer(), nullable=False),
        sa.Column("caller_hash", sa.Text(), nullable=False),
        sa.Column("scenario", sa.Text(), nullable=False),
        sa.Column("consent_version", sa.Text(), nullable=False),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("send_started_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
        sa.Column("provider_call_id", sa.Text(), unique=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("transfer_status", sa.Text(), nullable=False),
        sa.Column("socket_admitted", sa.Boolean(), nullable=False),
        sa.Column("carrier_end_confirmed", sa.Boolean(), nullable=False),
        sa.Column("mock", sa.Boolean(), nullable=False),
        sa.Column("reserved_cost_cents", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Integer()),
        sa.Column("error_code", sa.Text()),
        sa.Column("transfer_confirmation_hash", sa.Text()),
        sa.CheckConstraint("status IN ('reserved','dialing','ringing','in_progress','completed','rejected','unanswered','failed','unknown','transferred','transfer_unconfirmed')", name="status_valid"),
        sa.CheckConstraint("transfer_status IN ('not_requested','requested','refer_accepted','failed','unconfirmed')", name="transfer_valid"),
        sa.CheckConstraint("reserved_cost_cents > 0", name="cost_positive"),
        sa.CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="duration_valid"),
    )
    op.create_index("ix_outbound_calls_created", "outbound_calls", ["created_at"])
    op.create_index("ix_outbound_calls_destination_created", "outbound_calls", ["destination_hash", "created_at"])
    op.create_table(
        "outbound_call_events",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("call_id", sa.Uuid(), sa.ForeignKey("outbound_calls.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False, unique=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_outbound_call_events_call_id", "outbound_call_events", ["call_id"])
    op.create_table(
        "outbound_suppressions",
        sa.Column("destination_hash", sa.Text(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    raise RuntimeError("Retain calling consent, suppression, spending and unresolved carrier evidence")
