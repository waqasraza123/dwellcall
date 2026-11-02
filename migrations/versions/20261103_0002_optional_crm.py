from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261103_0002"
down_revision: str | None = "20261103_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    throttle = op.create_table(
        "crm_dispatch_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paused_destination", sa.Text()),
        sa.CheckConstraint("id = 1", name="singleton"),
    )
    op.bulk_insert(throttle, [{"id": 1, "next_attempt_at": datetime(1970, 1, 1, tzinfo=UTC)}])
    op.create_table(
        "crm_exports",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("call_id", sa.Text(), sa.ForeignKey("audio_sessions.call_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("destination", sa.Text(), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(none_as_null=True)),
        sa.Column("consent_version", sa.Text(), nullable=False),
        sa.Column("permission_reference", sa.Text(), nullable=False),
        sa.Column("permission_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("permission_revoked_at", sa.DateTime(timezone=True)),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True)),
        sa.Column("attempt_id", sa.Uuid()),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
        sa.Column("last_code", sa.Text()),
        sa.Column("person_id", sa.Integer()),
        sa.UniqueConstraint("call_id", "snapshot_version", "provider", "destination", name="uq_crm_export_scope"),
        sa.CheckConstraint("snapshot_version > 0", name="version_valid"),
        sa.CheckConstraint("provider = 'followupboss'", name="provider_valid"),
        sa.CheckConstraint("attempts >= 0", name="attempts_valid"),
        sa.CheckConstraint("status IN ('pending','sending','retry_wait','sent','unknown','failed','ignored','cancelled')", name="status_valid"),
    )
    op.create_index("ix_crm_exports_due", "crm_exports", ["status", "next_attempt_at"])
    op.create_table(
        "crm_audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("export_id", sa.Uuid(), sa.ForeignKey("crm_exports.id", ondelete="RESTRICT")),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("evidence_reference", sa.Text()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM crm_exports")):
        raise RuntimeError("CRM consent and delivery evidence must be retained")
    op.drop_table("crm_audit_events")
    op.drop_table("crm_exports")
    op.drop_table("crm_dispatch_state")
