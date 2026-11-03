import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from dwellcall.crm.agent_schemas import AgentContactSnapshot, AgentProperty
from dwellcall.crm.settings import CrmSettings
from dwellcall.database.models import (
    ListingAgent, ListingAgentIdentity, ListingAgentObservation, ListingContactEvidence,
    ListingObservation, ListingReview, ListingSource,
)
from dwellcall.listings.normalization import fingerprint
from dwellcall.listings.permissions import permission, retained


class AgentIneligible(ValueError):
    pass


def optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def export_snapshot(session: Session, agent_id: UUID) -> AgentContactSnapshot:
    try:
        return _export_snapshot(session, agent_id)
    except AgentIneligible:
        raise
    except (ValidationError, KeyError, TypeError, ValueError):
        raise AgentIneligible("AGENT_EXPORT_DATA_INVALID") from None


def _export_snapshot(session: Session, agent_id: UUID) -> AgentContactSnapshot:
    agent = session.get(ListingAgent, agent_id)
    if agent is None:
        raise AgentIneligible("AGENT_NOT_FOUND")
    if agent.data_mode != "live":
        raise AgentIneligible("SYNTHETIC_EXPORT_FORBIDDEN")
    if agent.suppressed_at is not None or agent.review_required:
        raise AgentIneligible("AGENT_SUPPRESSED_OR_AMBIGUOUS")
    unresolved = (ListingReview.status != "approved") | ListingReview.applied_at.is_(None)
    if session.scalar(select(ListingReview.id).where(ListingReview.candidate_ids.contains([str(agent_id)]), unresolved).limit(1)):
        raise AgentIneligible("AGENT_REVIEW_UNRESOLVED")
    rows = session.execute(select(ListingAgentObservation, ListingObservation, ListingSource).join(
        ListingObservation, ListingObservation.id == ListingAgentObservation.observation_id,
    ).join(ListingSource, ListingSource.key == ListingObservation.source_key).where(
        ListingAgentObservation.agent_id == agent_id, ListingAgentObservation.active.is_(True),
    ).order_by(ListingAgentObservation.collected_at.desc(), ListingAgentObservation.id).limit(101)).all()
    if len(rows) > 100:
        raise AgentIneligible("AGENT_ASSOCIATION_LIMIT")
    identities = list(session.scalars(select(ListingAgentIdentity).where(ListingAgentIdentity.agent_id == agent_id)))
    eligible = []
    for observed, listing, source in rows:
        if session.scalar(select(ListingReview.id).where(
            ListingReview.source_key == source.key, ListingReview.source_listing_id == listing.source_listing_id, unresolved,
        ).limit(1)):
            raise AgentIneligible("LISTING_REVIEW_UNRESOLVED")
        policy = permission(source)
        if not (policy.data_mode == "live" and policy.enabled and policy.access_confirmed and policy.export_allowed
                and policy.contacts_allowed and retained(source, observed.collected_at, display=True)
                and retained(source, listing.collected_at, display=True)
                and listing.permission_version == source.permission_version):
            continue
        if not any(identity.namespace == "source:" + source.key or identity.namespace in policy.identifier_namespaces for identity in identities):
            continue
        eligible.append((observed, listing, source))
    if not eligible:
        raise AgentIneligible("EXPORT_PERMISSION_OR_IDENTITY_REQUIRED")
    contacts: dict[str, set[str]] = {"email": set(), "phone": set()}
    references: list[dict[str, str | int]] = []
    now = datetime.now(UTC)
    for observed, _, source in eligible:
        policy = permission(source)
        if not policy.trusted_verification:
            continue
        for evidence in session.scalars(select(ListingContactEvidence).where(
            ListingContactEvidence.agent_observation_id == observed.id,
            ListingContactEvidence.agent_id == agent_id, ListingContactEvidence.active.is_(True),
            ListingContactEvidence.direct.is_(True), ListingContactEvidence.kind != "office_phone",
            ListingContactEvidence.verification_status == "verified",
            ListingContactEvidence.permission_version == source.permission_version,
        )):
            if not retained(source, evidence.collected_at, display=True) or evidence.verified_at is None or not now - timedelta(days=policy.retention_days) <= evidence.verified_at <= now:
                continue
            if session.scalar(select(ListingContactEvidence.id).join(
                ListingAgentObservation, ListingAgentObservation.id == ListingContactEvidence.agent_observation_id,
            ).where(
                ListingContactEvidence.value == evidence.value, ListingContactEvidence.agent_id != agent_id,
                ListingContactEvidence.active.is_(True), ListingAgentObservation.active.is_(True),
            ).limit(1)):
                raise AgentIneligible("SHARED_CONTACT_IDENTITY")
            if session.scalar(select(ListingAgentIdentity.id).join(ListingAgent, ListingAgent.id == ListingAgentIdentity.agent_id).where(
                ListingAgentIdentity.data_mode == "live", ListingAgent.suppressed_at.is_not(None),
                ListingAgentIdentity.namespace == "suppressed-contact:" + evidence.kind,
                ListingAgentIdentity.identifier == fingerprint(evidence.value),
            ).limit(1)):
                raise AgentIneligible("CONTACT_SUPPRESSED")
            contacts["email" if evidence.kind == "business_email" else "phone"].add(evidence.value)
            references.append({"source_key": source.key, "source_reference": evidence.source_reference,
                               "source_url": evidence.source_url or "", "permission_version": source.permission_version})
    if len(references) > 100:
        raise AgentIneligible("AGENT_CONTACT_EVIDENCE_LIMIT")
    if not any(contacts.values()):
        raise AgentIneligible("VERIFIED_DIRECT_CONTACT_REQUIRED")
    if any(len(values) > 1 for values in contacts.values()):
        raise AgentIneligible("CONTACT_IDENTITY_AMBIGUOUS")
    properties = [AgentProperty(
        listing_id=listing.listing_id, source_key=source.key, source_listing_id=listing.source_listing_id,
        listing_url=optional_text(listing.snapshot.get("listing_url")), street_address=optional_text(listing.snapshot.get("street_address")),
        status=optional_text(listing.snapshot.get("status")), price=str(listing.snapshot["price"]) if listing.snapshot.get("price") is not None else None,
        currency=optional_text(listing.snapshot.get("currency")), permission_version=source.permission_version,
    ) for _, listing, source in eligible]
    newest = eligible[0][0]
    return AgentContactSnapshot(
        agent_id=agent_id, full_name=str(newest.snapshot["full_name"]), brokerage=optional_text(newest.snapshot.get("brokerage")),
        email=next(iter(contacts["email"]), None), phone=next(iter(contacts["phone"]), None),
        properties=sorted(properties, key=lambda item: (str(item.listing_id), item.source_key, item.source_listing_id)),
        contact_references=sorted(references, key=lambda item: json.dumps(item, sort_keys=True)),
    )


def snapshot_fingerprint(settings: CrmSettings, snapshot: AgentContactSnapshot, fields: dict[str, str]) -> str:
    return settings.fingerprint("agent-export", json.dumps({
        "snapshot": snapshot.model_dump(mode="json"), "fields": fields,
        "tags": settings.ghl_tags, "source": settings.ghl_lead_source,
        "opportunities": settings.ghl_opportunities_enabled, "pipeline": settings.ghl_pipeline_id,
        "stage": settings.ghl_pipeline_stage_id, "qualifying_statuses": settings.ghl_qualifying_statuses, "qualified_min": settings.ghl_qualified_min_listings,
    }, sort_keys=True, separators=(",", ":")))
