"""DwellCall accounts and authenticator authentication on Neon/PostgreSQL."""
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision = "20261105_0010"
down_revision = "20261104_0009"
branch_labels = None
depends_on = None


def account(*, primary: bool = False) -> sa.Column[UUID]:
    return sa.Column("account_id", sa.Uuid(), sa.ForeignKey(
        "accounts.id", ondelete="RESTRICT"
    ), nullable=False, primary_key=primary)


def identity() -> sa.Column[UUID]:
    return sa.Column("id", sa.Uuid(), primary_key=True,
                     server_default=sa.text("gen_random_uuid()"))


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("operator_access", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("disabled_at", sa.DateTime(timezone=True)),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "account_login_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_account_login_sessions_account_id", "account_login_sessions", ["account_id"])
    op.create_table(
        "account_auth_limits",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "account_mfa_factors", account(primary=True),
        sa.Column("secret_ciphertext", sa.Text()),
        sa.Column("enabled_at", sa.DateTime(timezone=True)),
        sa.Column("last_counter", sa.BigInteger()),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.CheckConstraint("version > 0", name="version_valid"),
        sa.CheckConstraint("last_counter IS NULL OR last_counter >= 0", name="counter_valid"),
        sa.CheckConstraint("failed_attempts BETWEEN 0 AND 5", name="attempts_valid"),
        sa.CheckConstraint(
            "(enabled_at IS NULL AND secret_ciphertext IS NULL AND last_counter IS NULL) OR "
            "(enabled_at IS NOT NULL AND secret_ciphertext IS NOT NULL AND last_counter IS NOT NULL)",
            name="enrollment_consistent",
        ),
    )
    op.create_table(
        "account_mfa_challenges", identity(), account(),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("secret_ciphertext", sa.Text()),
        sa.Column("factor_version", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("purpose IN ('ENROLL', 'VERIFY', 'REPLACE')", name="purpose_valid"),
        sa.CheckConstraint("attempts BETWEEN 0 AND 5", name="attempts_valid"),
        sa.CheckConstraint("factor_version > 0", name="version_valid"),
        sa.CheckConstraint(
            "(purpose = 'VERIFY' AND secret_ciphertext IS NULL) OR "
            "(purpose IN ('ENROLL', 'REPLACE') AND "
            "(secret_ciphertext IS NOT NULL OR consumed_at IS NOT NULL))",
            name="secret_consistent",
        ),
    )
    op.create_index("ix_account_mfa_challenges_account_expiry", "account_mfa_challenges", ["account_id", "expires_at"])
    op.create_table(
        "account_mfa_recovery_codes", identity(), account(),
        sa.Column("code_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_account_mfa_recovery_account", "account_mfa_recovery_codes", ["account_id"])
    op.add_column("account_login_sessions", sa.Column("mfa_verified_at", sa.DateTime(timezone=True)))
    op.add_column("account_login_sessions", sa.Column("mfa_version", sa.Integer()))
    op.create_check_constraint(
        "mfa_consistent", "account_login_sessions",
        "(mfa_verified_at IS NULL AND mfa_version IS NULL) OR "
        "(mfa_verified_at IS NOT NULL AND mfa_version IS NOT NULL AND mfa_version > 0)",
    )
    op.create_table(
        "account_auth_events", identity(), account(),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_account_auth_events_account_id", "account_auth_events", ["account_id"])


def downgrade() -> None:
    raise RuntimeError("Retain account credentials, revocations and MFA recovery evidence")
