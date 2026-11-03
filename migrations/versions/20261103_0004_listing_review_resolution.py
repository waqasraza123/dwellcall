"""Persist bounded operator identity decisions independently of import history."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261103_0004"
down_revision = "20261103_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("listing_identity_reviews", sa.Column("status", sa.Text(), nullable=False, server_default="pending"))
    op.add_column("listing_identity_reviews", sa.Column("resolution", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("listing_identity_reviews", sa.Column("resolved_at", sa.DateTime(timezone=True)))
    op.add_column("listing_identity_reviews", sa.Column("applied_at", sa.DateTime(timezone=True)))
    op.create_check_constraint("listing_review_status_valid", "listing_identity_reviews", "status IN ('pending','approved','rejected')")


def downgrade() -> None:
    raise RuntimeError("Retain listing review decisions and audit evidence")
