"""Reviewed platform leads and local follow-up task evidence."""
import sqlalchemy as sa
from alembic import op

revision = "20261108_0013"
down_revision = "20261108_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("call_lead_reviews",
        sa.Column("call_id", sa.Uuid(), sa.ForeignKey("outbound_calls.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assessment_fingerprint", sa.Text()),
        sa.Column("task_status", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("outcome", sa.Text()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('approved','deferred','rejected')", name="status_valid"),
        sa.CheckConstraint("version > 0", name="version_positive"),
        sa.CheckConstraint("task_status IN ('none','open','completed','cancelled')", name="task_status_valid"),
        sa.CheckConstraint("task_status != 'open' OR (status = 'approved' AND due_at IS NOT NULL)", name="open_task_consistent"))
    op.create_index("ix_call_lead_reviews_task_due", "call_lead_reviews", ["task_status", "due_at"])
    op.create_table("call_lead_review_events",
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        sa.Column("call_id", sa.Uuid(), sa.ForeignKey("outbound_calls.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_status", sa.Text(), nullable=False),
        sa.Column("task_status", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("outcome", sa.Text()),
        sa.Column("evidence_reviewed", sa.Boolean(), nullable=False))
    op.create_index("ix_call_lead_review_events_call_version", "call_lead_review_events", ["call_id", "version"], unique=True)


def downgrade() -> None:
    raise RuntimeError("Retain lead decisions and task history; use a reviewed retention procedure")
