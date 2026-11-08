"""Provider selection, SMS verification and encrypted call intelligence."""
import sqlalchemy as sa
from alembic import op

revision = "20261108_0012"
down_revision = "20261105_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("outbound_calls", sa.Column("provider", sa.Text(), nullable=False, server_default="retell"))
    op.add_column("outbound_calls", sa.Column("owner_hash", sa.Text()))
    op.add_column("outbound_calls", sa.Column("call_purpose", sa.Text(), nullable=False, server_default="demonstration"))
    op.add_column("outbound_calls", sa.Column("intelligence_consent", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table("outbound_phone_verifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_hash", sa.Text(), nullable=False),
        sa.Column("destination_hash", sa.Text(), nullable=False),
        sa.Column("consent_version", sa.Text(), nullable=False),
        sa.Column("provider_verification_id", sa.Text(), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("consumed_by_request_id", sa.Uuid()),
        sa.CheckConstraint("attempts BETWEEN 0 AND 5", name="attempts_valid"))
    op.create_index("ix_outbound_phone_verifications_created", "outbound_phone_verifications", ["created_at"])
    op.create_table("call_intelligence",
        sa.Column("call_id", sa.Uuid(), sa.ForeignKey("outbound_calls.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("transcript_ciphertext", sa.Text()),
        sa.Column("transcript_hash", sa.Text(), nullable=False),
        sa.Column("analysis_ciphertext", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("disposition", sa.Text()),
        sa.Column("analysis_model", sa.Text()),
        sa.Column("attempt_id", sa.Uuid()),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    raise RuntimeError("Retain authorization and call evidence; use the explicit transcript purge operation")
