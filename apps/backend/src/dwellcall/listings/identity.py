from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from dwellcall.database.models import (
    ListingAgent, ListingAgentIdentity, ListingAgentObservation, ListingContactEvidence,
    ListingObservation, ListingReview, ListingSource,
)
from dwellcall.listings.normalization import fingerprint, text_key
from dwellcall.listings.permissions import permission, permitted_url, retained, verification_status
from dwellcall.listings.schemas import AgentRecord, SourcePermissionInput


def hold_review(
    session: Session, source: ListingSource, listing_reference: str,
    reason: str, snapshot: dict[str, object], candidates: set[UUID] | None = None,
) -> ListingReview:
    key = fingerprint({"listing": listing_reference, "reason": reason, "snapshot": snapshot})
    review = session.scalar(select(ListingReview).where(ListingReview.source_key == source.key, ListingReview.fingerprint == key))
    if review is None:
        review = ListingReview(
            id=uuid4(), source_key=source.key, source_listing_id=listing_reference,
            reason=reason, fingerprint=key, candidate_ids=sorted(str(value) for value in candidates or ()),
            snapshot=snapshot, created_at=datetime.now(UTC), status="pending", resolution={},
        )
        session.add(review)
    for candidate in candidates or ():
        agent = session.get(ListingAgent, candidate)
        if agent is not None:
            agent.review_required = True
    session.flush()
    return review


def evidence_key(source: ListingSource, subject: dict[str, object]) -> str:
    return fingerprint({"subject": subject, "permission_version": source.permission_version})


def reviewed_decision(session: Session, source: ListingSource, listing_id: str, key: str) -> ListingReview | None:
    return session.scalar(select(ListingReview).where(
        ListingReview.source_key == source.key, ListingReview.source_listing_id == listing_id,
        ListingReview.snapshot["evidence_key"].as_string() == key,
        ListingReview.status.in_(("approved", "rejected")),
    ).order_by(ListingReview.resolved_at.desc()).limit(1))


def local_identity(source: ListingSource, listing: ListingObservation, record: AgentRecord) -> tuple[str, str]:
    return "local:" + source.key, fingerprint([listing.source_listing_id, text_key(record.full_name), text_key(record.brokerage or ""), record.profile_url])


def suppression_aliases(source: ListingSource, listing: ListingObservation, record: AgentRecord) -> list[tuple[str, str]]:
    return [
        ("suppressed-local:" + source.key, fingerprint([listing.source_listing_id, text_key(record.full_name)])),
        *[("suppressed-contact:" + contact.kind, fingerprint(contact.value))
          for contact in record.contacts if contact.direct and contact.kind != "office_phone"],
    ]


def strong_identifiers(agent: AgentRecord, source: ListingSource, policy: SourcePermissionInput) -> list[tuple[str, str]]:
    values = [(value.namespace, value.value) for value in agent.identifiers if value.namespace in policy.identifier_namespaces]
    if agent.source_agent_id:
        values.append(("source:" + source.key, agent.source_agent_id))
    return values


def agent_key(agent: AgentRecord) -> str:
    if agent.source_agent_id:
        return "source:" + agent.source_agent_id
    return "local:" + fingerprint([text_key(agent.full_name), text_key(agent.brokerage or ""), agent.profile_url])


def resolve_agent(
    session: Session, source: ListingSource, listing: ListingObservation,
    record: AgentRecord, policy: SourcePermissionInput,
) -> tuple[ListingAgent | None, bool]:
    identifiers = strong_identifiers(record, source, policy)
    for namespace, identifier in suppression_aliases(source, listing, record):
        tombstone = session.scalar(select(ListingAgentIdentity).where(
            ListingAgentIdentity.data_mode == policy.data_mode,
            ListingAgentIdentity.namespace == namespace, ListingAgentIdentity.identifier == identifier,
        ))
        if tombstone is not None:
            owner = session.get(ListingAgent, tombstone.agent_id)
            if owner is not None and owner.suppressed_at is not None:
                return owner, False
    safe_snapshot: dict[str, object] = {
        "agent": record.model_dump(mode="json", exclude={"contacts"}, exclude_unset=True),
        "evidence_key": evidence_key(source, record.model_dump(mode="json", exclude_unset=True)),
        "subject_type": "agent", "agent_key": agent_key(record),
    }
    local_namespace, local_identifier = local_identity(source, listing, record)
    local = session.scalar(select(ListingAgentIdentity).where(
        ListingAgentIdentity.data_mode == policy.data_mode,
        ListingAgentIdentity.namespace == local_namespace,
        ListingAgentIdentity.identifier == local_identifier,
    ))
    local_agent = session.get(ListingAgent, local.agent_id) if local else None
    if local_agent is not None and local_agent.suppressed_at is not None:
        return local_agent, False
    if local_agent is not None and identifiers and not reviewed_decision(session, source, listing.source_listing_id, str(safe_snapshot["evidence_key"])):
        hold_review(session, source, listing.source_listing_id, "WEAK_IDENTITY_PROMOTION", safe_snapshot, {local_agent.id})
        return None, False
    if any(value.namespace not in policy.identifier_namespaces for value in record.identifiers):
        hold_review(session, source, listing.source_listing_id, "AGENT_NAMESPACE_UNAPPROVED", safe_snapshot)
        return None, False
    candidates: set[UUID] = set()
    found_identities = []
    for namespace, identifier in identifiers:
        identity = session.scalar(select(ListingAgentIdentity).where(
            ListingAgentIdentity.data_mode == policy.data_mode,
            ListingAgentIdentity.namespace == namespace, ListingAgentIdentity.identifier == identifier,
        ))
        if identity is not None:
            found_identities.append(identity)
            candidates.add(identity.agent_id)
    if policy.contacts_allowed:
        for contact in record.contacts:
            status = verification_status(contact, policy)
            if not contact.direct or contact.kind == "office_phone" or status == "unverified":
                continue
            rows = session.execute(
                select(ListingContactEvidence, ListingSource, ListingAgentObservation, ListingAgent)
                .join(ListingSource, ListingSource.key == ListingContactEvidence.source_key)
                .join(ListingAgentObservation, ListingAgentObservation.id == ListingContactEvidence.agent_observation_id)
                .join(ListingAgent, ListingAgent.id == ListingContactEvidence.agent_id)
                .where(
                    ListingContactEvidence.kind == contact.kind, ListingContactEvidence.value == contact.value,
                    ListingContactEvidence.direct.is_(True), ListingContactEvidence.active.is_(True),
                    ListingContactEvidence.verification_status == status,
                    ListingAgentObservation.active.is_(True), ListingAgent.data_mode == policy.data_mode,
                    ListingAgent.review_required.is_(False), ListingAgent.suppressed_at.is_(None),
                ).limit(20)
            ).all()
            if len(rows) == 20:
                hold_review(session, source, listing.source_listing_id, "AMBIGUOUS_CONTACT_IDENTITY", safe_snapshot)
                return None, False
            for evidence, evidence_source, evidence_observation, matched in rows:
                evidence_policy = permission(evidence_source)
                if (
                    retained(evidence_source, evidence.collected_at)
                    and retained(evidence_source, evidence_observation.collected_at) and evidence_policy.contacts_allowed
                    and evidence_policy.trusted_verification and evidence.verified_at is not None
                    and evidence.verified_at >= datetime.now(UTC) - timedelta(days=evidence_policy.retention_days)
                ):
                    if identifiers:
                        candidates.add(matched.id)
    for candidate in candidates:
        owner = session.get(ListingAgent, candidate)
        if owner is not None and owner.suppressed_at is not None:
            return owner, False
    decision = reviewed_decision(session, source, listing.source_listing_id, str(safe_snapshot["evidence_key"]))
    if decision is not None:
        if decision.status == "rejected":
            return None, False
        matched = session.get(ListingAgent, UUID(str(decision.resolution["candidate_id"])))
        if matched is None or matched.suppressed_at is not None:
            return None, False
        if decision.applied_at is None:
            from dwellcall.listings.service import audit

            audit(session, source, "LISTING_REVIEW_APPLIED", {"review_id": str(decision.id), "candidate_id": str(matched.id)})
            decision.applied_at = datetime.now(UTC)
        return matched, False
    if len(candidates) > 1:
        hold_review(session, source, listing.source_listing_id, "CONFLICTING_AGENT_IDENTITIES", safe_snapshot, candidates)
        return None, False
    matched = session.get(ListingAgent, next(iter(candidates))) if candidates else None
    if matched is not None and matched.suppressed_at is not None:
        return matched, False
    if matched is not None and matched.review_required:
        hold_review(session, source, listing.source_listing_id, "AGENT_REQUIRES_REVIEW", safe_snapshot, {matched.id})
        return None, False
    if matched is not None and matched.normalized_name != text_key(record.full_name):
        hold_review(session, source, listing.source_listing_id, "AGENT_NAME_CONFLICT", safe_snapshot, candidates)
        matched.review_required = True
        return None, False
    if matched is not None:
        for namespace, identifier in identifiers:
            existing = session.scalars(select(ListingAgentIdentity).where(
                ListingAgentIdentity.agent_id == matched.id, ListingAgentIdentity.namespace == namespace,
            )).all()
            if any(value.identifier != identifier for value in existing):
                hold_review(session, source, listing.source_listing_id, "AGENT_IDENTIFIER_CONFLICT", safe_snapshot, {matched.id})
                return None, False
    if matched is None and not identifiers:
        matched = local_agent
        if matched is not None:
            matched.review_required = True
    created = matched is None
    if matched is None:
        matched = ListingAgent(
            id=uuid4(), data_mode=policy.data_mode, full_name=record.full_name,
            normalized_name=text_key(record.full_name), brokerage=record.brokerage,
            normalized_brokerage=text_key(record.brokerage) if record.brokerage else None,
            review_required=not identifiers, created_at=datetime.now(UTC),
        )
        session.add(matched)
        session.flush()
    elif identifiers and matched.suppressed_at is None and "brokerage" in record.model_fields_set:
        matched.brokerage = record.brokerage
        matched.normalized_brokerage = text_key(record.brokerage) if record.brokerage else None
    if not identifiers and local is None:
        session.add(ListingAgentIdentity(id=uuid4(), agent_id=matched.id, data_mode=policy.data_mode,
                                        namespace=local_namespace, identifier=local_identifier))
    for namespace, identifier in identifiers:
        existing = next((value for value in found_identities if value.namespace == namespace and value.identifier == identifier), None)
        if existing is not None and existing.agent_id != matched.id:
            hold_review(session, source, listing.source_listing_id, "AGENT_IDENTITY_RETIRED", safe_snapshot, {existing.agent_id, matched.id})
            return None, created
        if existing is None:
            session.add(ListingAgentIdentity(id=uuid4(), agent_id=matched.id, data_mode=policy.data_mode, namespace=namespace, identifier=identifier))
    return matched, created


def update_agents(
    session: Session, source: ListingSource, listing: ListingObservation,
    records: tuple[AgentRecord, ...], policy: SourcePermissionInput,
) -> tuple[int, int]:
    now = datetime.now(UTC)
    previous = list(session.scalars(select(ListingAgentObservation).where(ListingAgentObservation.observation_id == listing.id)).all())
    for old in previous:
        old.active = False
    created, reviews = 0, 0
    keys = [agent_key(record) for record in records]
    for record in records:
        key = agent_key(record)
        if keys.count(key) != 1 or not permitted_url(record.profile_url, policy):
            hold_review(session, source, listing.source_listing_id, "AMBIGUOUS_AGENT_RECORD", {"agent_key": key})
            reviews += 1
            continue
        agent, is_new = resolve_agent(session, source, listing, record, policy)
        created += int(is_new)
        if agent is None:
            reviews += 1
            continue
        if agent.review_required:
            hold_review(session, source, listing.source_listing_id, "AGENT_WITHOUT_STRONG_IDENTITY", {
                "agent_key": key, "subject_type": "agent",
                "agent": record.model_dump(mode="json", exclude={"contacts"}, exclude_unset=True),
                "evidence_key": evidence_key(source, record.model_dump(mode="json", exclude_unset=True)),
            }, {agent.id})
            reviews += 1
        if agent.suppressed_at is not None:
            for old in previous:
                if old.agent_id == agent.id:
                    old.active = True
            continue
        observation = next((value for value in previous if value.agent_key == key), None)
        if observation is None:
            observation = ListingAgentObservation(id=uuid4(), observation_id=listing.id, agent_key=key, agent_id=agent.id)
            session.add(observation)
        elif observation.agent_id != agent.id:
            for old in session.scalars(select(ListingContactEvidence).where(ListingContactEvidence.agent_observation_id == observation.id)).all():
                old.active = False
            observation.agent_id = agent.id
        observation.active = True
        observation.snapshot = record.model_dump(mode="json", exclude={"contacts"}, exclude_unset=True)
        observation.collected_at = now
        observation.provenance = {
            name: {"source_key": source.key, "source_listing_id": listing.source_listing_id,
                   "permission_version": source.permission_version, "collected_at": now.isoformat(),
                   "verification_status": "source_reported_synthetic" if policy.data_mode == "synthetic" else "source_reported"}
            for name in record.model_fields_set if name != "contacts"
        }
        session.flush()
        if "contacts" not in record.model_fields_set and policy.contacts_allowed and agent.suppressed_at is None and not agent.review_required:
            continue
        evidence_rows = list(session.scalars(select(ListingContactEvidence).where(ListingContactEvidence.agent_observation_id == observation.id)).all())
        for old in evidence_rows:
            old.active = False
        if not policy.contacts_allowed or agent.suppressed_at is not None or agent.review_required:
            continue
        for contact in record.contacts:
            if not permitted_url(contact.source_url, policy):
                reviews += 1
                hold_review(session, source, listing.source_listing_id, "CONTACT_SOURCE_UNAPPROVED", {"agent_key": key, "kind": contact.kind})
                continue
            contact_key = fingerprint({"contact": contact.model_dump(mode="json"), "permission_version": source.permission_version, "agent_id": str(agent.id)})
            evidence = next((value for value in evidence_rows if value.fingerprint == contact_key), None)
            if evidence is None:
                evidence = ListingContactEvidence(
                    id=uuid4(), agent_observation_id=observation.id, agent_id=agent.id,
                    source_key=source.key, fingerprint=contact_key,
                )
                session.add(evidence)
            evidence.kind, evidence.value, evidence.direct = contact.kind, contact.value, contact.direct
            evidence.active = True
            evidence.verification_status = verification_status(contact, policy)
            evidence.claimed_verification = contact.verification
            evidence.confidence, evidence.verified_at = contact.confidence, contact.verified_at
            evidence.source_reference, evidence.source_url = contact.source_reference, contact.source_url
            evidence.permission_version, evidence.collected_at = source.permission_version, now
    return created, reviews
