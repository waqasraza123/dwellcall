"""Operator discovery jobs, attempt history and duplicate action reservations."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261103_0006"
down_revision = "20261103_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    stamp = sa.DateTime(timezone=True)
    uuid = sa.Uuid(as_uuid=True)
    op.create_table("discovery_jobs",
        sa.Column("id", uuid, primary_key=True), sa.Column("name", sa.Text(), nullable=False),
        sa.Column("source_key", sa.Text(), sa.ForeignKey("listing_sources.key", ondelete="RESTRICT"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False), sa.Column("filters", JSONB(), nullable=False),
        sa.Column("poll_interval_minutes", sa.Integer(), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", stamp, nullable=False), sa.Column("updated_at", stamp, nullable=False))
    op.create_table("discovery_attempts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("job_id", uuid, sa.ForeignKey("discovery_jobs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_id", uuid, nullable=False, unique=True), sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", stamp, nullable=False), sa.Column("finished_at", stamp),
        sa.Column("code", sa.Text()), sa.Column("result", JSONB(), nullable=False))
    op.create_index("ix_discovery_attempts_job_id", "discovery_attempts", ["job_id"])
    op.create_table("operator_actions", sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("fingerprint", sa.Text(), nullable=False), sa.Column("created_at", stamp, nullable=False))


def downgrade() -> None:
    raise RuntimeError("Retain discovery history and duplicate action reservations")
