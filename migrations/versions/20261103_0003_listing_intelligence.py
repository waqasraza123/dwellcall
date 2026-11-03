"""Listing intelligence foundation; no external integrations are activated."""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20261103_0003"
down_revision: str | None = "20261103_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def identifier() -> sa.Column:
    return sa.Column(
        "id", sa.Uuid(), primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def text(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.Text(), nullable=nullable)


def timestamp(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def document(name: str) -> sa.Column:
    return sa.Column(name, JSONB(), nullable=False)


def reference(name: str, target: str, *, cascade: bool = False) -> sa.Column:
    return sa.Column(
        name, sa.Uuid(),
        sa.ForeignKey(target, ondelete="CASCADE" if cascade else "RESTRICT"),
        nullable=False,
    )


def source_reference() -> sa.Column:
    return sa.Column(
        "source_key", sa.Text(),
        sa.ForeignKey("listing_sources.key", ondelete="RESTRICT"), nullable=False,
    )


def upgrade() -> None:
    sources = op.create_table(
        "listing_sources",
        sa.Column("key", sa.Text(), primary_key=True),
        document("permission"),
        sa.Column("permission_version", sa.Integer(), nullable=False),
        timestamp("created_at"), timestamp("last_attempt_at", nullable=True),
        timestamp("last_success_at", nullable=True), text("checkpoint", nullable=True),
        sa.CheckConstraint("permission_version > 0", name="permission_version_valid"),
    )
    op.create_table(
        "listing_import_runs", identifier(), source_reference(),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        text("request_fingerprint"),
        sa.Column("permission_version", sa.Integer(), nullable=False),
        timestamp("created_at"),
        sa.Column("received_count", sa.Integer(), nullable=False),
        document("filters"), text("status"), document("result"),
        sa.UniqueConstraint("source_key", "request_id", name="uq_listing_import_request"),
    )
    op.create_index("ix_listing_import_runs_created_at", "listing_import_runs", ["created_at"])
    op.create_table(
        "listing_entities", identifier(), text("data_mode"),
        text("listing_namespace", nullable=True), text("listing_reference", nullable=True),
        text("address_key", nullable=True), text("street_address", nullable=True),
        text("city", nullable=True), text("state", nullable=True),
        text("postal_code", nullable=True), sa.Column("price", sa.Numeric(16, 2)),
        text("currency", nullable=True), text("status", nullable=True),
        text("property_type", nullable=True), document("snapshot"), document("provenance"),
        text("winning_source"), timestamp("source_updated_at", nullable=True),
        timestamp("created_at"), timestamp("updated_at"),
        sa.UniqueConstraint("data_mode", "listing_namespace", "listing_reference", name="uq_listing_strong_identity"),
        sa.CheckConstraint("data_mode IN ('synthetic','live')", name="mode_valid"),
        sa.CheckConstraint("price > 0", name="price_valid"),
    )
    op.create_index("ix_listing_entities_address_key", "listing_entities", ["address_key"])
    op.create_index("ix_listing_entities_location", "listing_entities", ["state", "city"])
    op.create_table(
        "listing_observations", identifier(), source_reference(),
        text("source_listing_id"), reference("listing_id", "listing_entities.id", cascade=True),
        document("snapshot"), text("fingerprint"),
        sa.Column("permission_version", sa.Integer(), nullable=False),
        timestamp("source_updated_at", nullable=True), timestamp("collected_at"),
        sa.UniqueConstraint("source_key", "source_listing_id", name="uq_listing_source_identity"),
    )
    op.create_index("ix_listing_observations_source_key", "listing_observations", ["source_key"])
    op.create_index("ix_listing_observations_listing_id", "listing_observations", ["listing_id"])
    op.create_table(
        "listing_revisions", identifier(),
        reference("observation_id", "listing_observations.id", cascade=True),
        reference("run_id", "listing_import_runs.id"), text("fingerprint"),
        document("snapshot"), document("events"), document("provenance"),
        timestamp("collected_at"),
        sa.UniqueConstraint("observation_id", "fingerprint", name="uq_listing_revision_fingerprint"),
    )
    op.create_table(
        "listing_agents", identifier(), text("data_mode"), text("full_name"),
        text("normalized_name"), text("brokerage", nullable=True),
        text("normalized_brokerage", nullable=True),
        sa.Column("review_required", sa.Boolean(), nullable=False),
        timestamp("suppressed_at", nullable=True), timestamp("created_at"),
    )
    op.create_index("ix_listing_agents_normalized_name", "listing_agents", ["normalized_name"])
    op.create_table(
        "listing_agent_identities", identifier(),
        reference("agent_id", "listing_agents.id", cascade=True),
        text("data_mode"), text("namespace"), text("identifier"),
        sa.UniqueConstraint("data_mode", "namespace", "identifier", name="uq_agent_strong_identity"),
    )
    op.create_index("ix_listing_agent_identities_agent_id", "listing_agent_identities", ["agent_id"])
    op.create_table(
        "listing_agent_observations", identifier(),
        reference("observation_id", "listing_observations.id", cascade=True),
        text("agent_key"), reference("agent_id", "listing_agents.id", cascade=True),
        sa.Column("active", sa.Boolean(), nullable=False), document("snapshot"),
        document("provenance"), timestamp("collected_at"),
        sa.UniqueConstraint("observation_id", "agent_key", name="uq_agent_observation_key"),
    )
    op.create_index("ix_listing_agent_observations_agent_id", "listing_agent_observations", ["agent_id"])
    op.create_table(
        "listing_contact_evidence", identifier(),
        reference("agent_observation_id", "listing_agent_observations.id", cascade=True),
        reference("agent_id", "listing_agents.id", cascade=True), source_reference(),
        text("kind"), text("value"), sa.Column("direct", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False), text("fingerprint"),
        text("verification_status"), text("claimed_verification"),
        sa.Column("confidence", sa.Numeric(5, 4)), timestamp("verified_at", nullable=True),
        text("source_reference"), text("source_url", nullable=True),
        sa.Column("permission_version", sa.Integer(), nullable=False),
        timestamp("collected_at"),
        sa.UniqueConstraint("agent_observation_id", "fingerprint", name="uq_contact_evidence_fingerprint"),
    )
    op.create_index("ix_listing_contact_match", "listing_contact_evidence", ["kind", "value", "verification_status"])
    op.create_table(
        "listing_identity_reviews", identifier(), source_reference(),
        text("source_listing_id"), text("reason"), text("fingerprint"),
        document("candidate_ids"), document("snapshot"), timestamp("created_at"),
        sa.UniqueConstraint("source_key", "fingerprint", name="uq_listing_review_fingerprint"),
    )
    op.create_table(
        "listing_audit_events", identifier(), source_reference(),
        text("event_type"), document("details"), timestamp("occurred_at"),
    )
    # This grant covers only the bundled fictional data, never licensed/live data.
    op.bulk_insert(sources, [{
        "key": "synthetic-files", "permission_version": 1,
        "created_at": datetime.now(UTC),
        "permission": {
            "provider": "file", "data_mode": "synthetic", "enabled": True,
            "access_confirmed": True,
            "permission_reference": "bundled-synthetic-fixtures-v1",
            "retrieve_allowed": True, "store_allowed": True,
            "display_allowed": True, "export_allowed": False,
            "contacts_allowed": True, "trusted_verification": True,
            "countries": ["US"], "states": ["TX"], "cities": ["Austin"],
            "identifier_namespaces": ["demo-mls", "demo-members"],
            "url_hosts": ["example.com"], "retention_days": 30,
            "attribution": "DwellCall synthetic demonstration; not real listings or agents",
            "poll_interval_minutes": 60,
        },
    }])


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM listing_audit_events")) or op.get_bind().scalar(sa.text("SELECT count(*) FROM listing_import_runs")):
        raise RuntimeError("Retain listing permission, identity and import audit evidence")
    for name in (
        "listing_audit_events", "listing_identity_reviews", "listing_contact_evidence",
        "listing_agent_observations", "listing_agent_identities", "listing_agents",
        "listing_revisions", "listing_observations", "listing_entities",
        "listing_import_runs", "listing_sources",
    ):
        op.drop_table(name)
