"""Reuse durable agent CRM links for HubSpot company associations."""
from alembic import op
import sqlalchemy as sa

revision = "20261104_0007"
down_revision = "20261103_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_crm_links", sa.Column("company_id", sa.Text(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Retain CRM company associations and uncertain outcome evidence")
