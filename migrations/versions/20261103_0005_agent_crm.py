"""Durable listing agent synchronization, independent of consultation exports."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261103_0005"
down_revision = "20261103_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = sa.Uuid(as_uuid=True)
    stamp = sa.DateTime(timezone=True)
    op.create_table(
        "agent_crm_destinations",
        sa.Column("destination", sa.Text(), primary_key=True),
        sa.Column("fields", JSONB(), nullable=False),
        sa.Column("capabilities", JSONB(), nullable=False),
        sa.Column("next_attempt_at", stamp, nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("configured_at", stamp),
    )
    op.create_table(
        "agent_crm_links",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("agent_id", uuid, sa.ForeignKey("listing_agents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("destination", sa.Text(), sa.ForeignKey("agent_crm_destinations.destination", ondelete="RESTRICT"), nullable=False),
        sa.Column("contact_id", sa.Text()), sa.Column("opportunity_id", sa.Text()),
        sa.Column("synced_fingerprint", sa.Text()), sa.Column("synced_at", stamp),
        sa.UniqueConstraint("agent_id", "destination", name="uq_agent_crm_link"),
        sa.UniqueConstraint("destination", "contact_id", name="uq_agent_crm_contact"),
    )
    op.create_index("ix_agent_crm_links_agent_id", "agent_crm_links", ["agent_id"])
    op.create_table(
        "agent_crm_jobs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("link_id", uuid, sa.ForeignKey("agent_crm_links.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(none_as_null=True)), sa.Column("fields", JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("attempt_id", uuid), sa.Column("attempted_at", stamp),
        sa.Column("created_at", stamp, nullable=False), sa.Column("next_attempt_at", stamp, nullable=False),
        sa.Column("retain_until", stamp, nullable=False), sa.Column("code", sa.Text()),
        sa.UniqueConstraint("link_id", "fingerprint", name="uq_agent_crm_job"),
        sa.CheckConstraint("status IN ('pending','sending','retry_wait','sent','unknown','failed','cancelled')", name="agent_job_status_valid"),
    )
    op.create_index("ix_agent_crm_jobs_due", "agent_crm_jobs", ["status", "next_attempt_at"])
    op.create_table(
        "agent_crm_audits", sa.Column("id", uuid, primary_key=True),
        sa.Column("job_id", uuid, sa.ForeignKey("agent_crm_jobs.id", ondelete="RESTRICT")),
        sa.Column("destination", sa.Text(), nullable=False), sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("evidence_reference", sa.Text()), sa.Column("occurred_at", stamp, nullable=False),
    )


def downgrade() -> None:
    raise RuntimeError("Retain CRM identity mappings, uncertain outcomes and audit evidence")
