from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261103_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    guard = op.create_table(
        "audio_admission_guard",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.CheckConstraint("id = 1", name="singleton"),
    )
    op.bulk_insert(guard, [{"id": 1}])
    op.create_table(
        "audio_sessions",
        sa.Column("call_id", sa.Text(), primary_key=True),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reserved_cost_cents", sa.Integer(), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('active','unknown','ended')", name="status_valid"),
        sa.CheckConstraint("reserved_cost_cents >= 0", name="cost_valid"),
    )
    op.create_index("ix_audio_sessions_created", "audio_sessions", ["created_at"])


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM audio_sessions")):
        raise RuntimeError("Private audio admission evidence must be retained")
    op.drop_table("audio_sessions")
    op.drop_table("audio_admission_guard")
