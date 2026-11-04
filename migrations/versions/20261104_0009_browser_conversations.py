"""Browser voice and text admission evidence without stored transcripts or grants."""
from alembic import op
import sqlalchemy as sa

revision = "20261104_0009"
down_revision = "20261104_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "browser_conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_hash", sa.Text(), nullable=False),
        sa.Column("audio_session_id", sa.Text(), sa.ForeignKey("audio_sessions.call_id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("scenario", sa.Text(), nullable=False),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("agent_version", sa.Integer(), nullable=False),
        sa.Column("mock", sa.Boolean(), nullable=False),
        sa.Column("turn_count", sa.Integer(), nullable=False),
        sa.Column("turn_in_flight", sa.Boolean(), nullable=False),
        sa.Column("socket_admitted", sa.Boolean(), nullable=False),
        sa.Column("send_started_at", sa.DateTime(timezone=True)),
        sa.Column("provider_call_id", sa.Text(), unique=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("mode IN ('voice','text')", name="mode_valid"),
        sa.CheckConstraint("scenario IN ('renting','buying','luxury')", name="scenario_valid"),
        sa.CheckConstraint("turn_count >= 0", name="turn_count_valid"),
    )
    op.create_index("ix_browser_conversations_owner_hash", "browser_conversations", ["owner_hash"])


def downgrade() -> None:
    raise RuntimeError("Retain browser admission and unresolved provider evidence")
