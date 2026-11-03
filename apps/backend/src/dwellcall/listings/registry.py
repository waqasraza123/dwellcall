from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from dwellcall.database.models import (
    AgentCrmLink, ListingAgent, ListingAgentIdentity, ListingAgentObservation, ListingContactEvidence,
    ListingEntity, ListingObservation, ListingReview, ListingRevision, ListingSource,
)
from dwellcall.errors import ApiError
from dwellcall.listings.identity import local_identity, strong_identifiers, suppression_aliases
from dwellcall.listings.normalization import fingerprint
from dwellcall.listings.permissions import permission
from dwellcall.listings.schemas import AgentRecord, SourcePermissionInput
from dwellcall.listings.service import audit, ingestion_lock, materialize_listing

SYNTHETIC_SOURCE_KEY = "synthetic-files"
SYNTHETIC_PERMISSION: dict[str, object] = {
    "provider": "file", "data_mode": "synthetic", "enabled": True,
    "access_confirmed": True, "permission_reference": "bundled-synthetic-fixtures-v1",
    "retrieve_allowed": True, "store_allowed": True, "display_allowed": True,
    "export_allowed": False, "contacts_allowed": True, "trusted_verification": True,
    "countries": ["US"], "states": ["TX"], "cities": ["Austin"],
    "identifier_namespaces": ["demo-mls", "demo-members"], "url_hosts": ["example.com"],
    "retention_days": 30, "attribution": "DwellCall synthetic demonstration; not real listings or agents",
    "poll_interval_minutes": 60,
}


class SourceRegistryService:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def configure(self, key: str, config: SourcePermissionInput) -> dict[str, object]:
        with self.sessions() as session, session.begin():
            ingestion_lock(session)
            source = session.get(ListingSource, key, with_for_update=True)
            if source is None:
                source = ListingSource(key=key, permission=config.model_dump(mode="json"), permission_version=1, created_at=datetime.now(UTC))
                session.add(source)
            else:
                old = permission(source)
                if old.provider != config.provider or old.data_mode != config.data_mode:
                    raise ApiError(status_code=409, code="SOURCE_IDENTITY_IMMUTABLE", message="Use a new source key for a different provider or data mode")
                scopes = ("countries", "states", "cities", "identifier_namespaces", "url_hosts")
                if any(getattr(old, name) != getattr(config, name) for name in scopes) and session.scalar(select(ListingObservation.id).where(ListingObservation.source_key == key).limit(1)) is not None:
                    raise ApiError(status_code=409, code="SOURCE_SCOPE_HAS_DATA", message="Revoke display/storage rights immediately if necessary; purge source observations before changing geography, reference hosts or identity authorities")
                source.permission = config.model_dump(mode="json")
                source.permission_version += 1
            session.flush()
            audit(session, source, "SOURCE_PERMISSION_UPDATED", {"permission_version": source.permission_version, "enabled": config.enabled})
            return {"source_key": key, "permission_version": source.permission_version, "provider_implemented": config.provider == "file"}

    def suppress(self, agent_id: UUID) -> dict[str, bool]:
        with self.sessions() as session, session.begin():
            ingestion_lock(session)
            agent = session.get(ListingAgent, agent_id, with_for_update=True)
            if agent is None:
                raise ApiError(status_code=404, code="AGENT_NOT_FOUND", message="Agent was not found")
            agent.suppressed_at = agent.suppressed_at or datetime.now(UTC)
            records = session.execute(select(ListingAgentObservation, ListingObservation, ListingSource).join(
                ListingObservation, ListingObservation.id == ListingAgentObservation.observation_id,
            ).join(ListingSource, ListingSource.key == ListingObservation.source_key).where(
                ListingAgentObservation.agent_id == agent_id,
            )).all()
            for observed, listing, source in records:
                record = AgentRecord.model_validate(observed.snapshot)
                aliases = suppression_aliases(source, listing, record)
                for contact in session.scalars(select(ListingContactEvidence).where(
                    ListingContactEvidence.agent_observation_id == observed.id,
                    ListingContactEvidence.direct.is_(True), ListingContactEvidence.kind != "office_phone",
                )):
                    aliases.append(("suppressed-contact:" + contact.kind, fingerprint(contact.value)))
                for namespace, identifier in aliases:
                    if session.scalar(select(ListingAgentIdentity.id).where(
                        ListingAgentIdentity.data_mode == agent.data_mode,
                        ListingAgentIdentity.namespace == namespace, ListingAgentIdentity.identifier == identifier,
                    )) is None:
                        session.add(ListingAgentIdentity(id=uuid4(), agent_id=agent.id, data_mode=agent.data_mode,
                                                        namespace=namespace, identifier=identifier))
                        session.flush()
                if not strong_identifiers(record, source, permission(source)):
                    namespace, identifier = local_identity(source, listing, record)
                    if session.scalar(select(ListingAgentIdentity.id).where(
                        ListingAgentIdentity.data_mode == agent.data_mode,
                        ListingAgentIdentity.namespace == namespace, ListingAgentIdentity.identifier == identifier,
                    )) is None:
                        session.add(ListingAgentIdentity(id=uuid4(), agent_id=agent.id, data_mode=agent.data_mode,
                                                        namespace=namespace, identifier=identifier))
                        session.flush()
            for row in session.scalars(select(ListingContactEvidence).where(ListingContactEvidence.agent_id == agent_id)).all():
                row.active = False
            sources = session.scalars(select(ListingSource).join(ListingObservation, ListingObservation.source_key == ListingSource.key).join(ListingAgentObservation, ListingAgentObservation.observation_id == ListingObservation.id).where(ListingAgentObservation.agent_id == agent_id).distinct()).all()
            for source in sources:
                audit(session, source, "AGENT_SUPPRESSED", {"agent_id": str(agent_id)})
            return {"suppressed": True}

    def purge(self, key: str, *, expired_only: bool = True) -> dict[str, int | bool]:
        now = datetime.now(UTC)
        with self.sessions() as session, session.begin():
            ingestion_lock(session)
            source = session.get(ListingSource, key, with_for_update=True)
            if source is None:
                raise ApiError(status_code=404, code="SOURCE_NOT_FOUND", message="Source was not found")
            cutoff = now - timedelta(days=permission(source).retention_days)
            query = select(ListingObservation).where(ListingObservation.source_key == key)
            if expired_only:
                query = query.where(ListingObservation.collected_at <= cutoff)
            rows = list(session.scalars(query.order_by(ListingObservation.collected_at).with_for_update(skip_locked=True).limit(50)).all())
            affected = {row.listing_id for row in rows}
            for row in rows:
                session.delete(row)
            session.flush()
            for entity_id in affected:
                entity = session.get(ListingEntity, entity_id)
                if entity is None:
                    continue
                if (
                    session.scalar(select(ListingObservation.id).where(ListingObservation.listing_id == entity_id).limit(1)) is None
                    and session.scalar(select(ListingReview.id).where(ListingReview.candidate_ids.contains([str(entity_id)])).limit(1)) is None
                ):
                    session.delete(entity)
                else:
                    materialize_listing(session, entity)
            # History/contact retention is independent of a listing's newer price update.
            revision_ids = select(ListingRevision.id).join(ListingObservation, ListingRevision.observation_id == ListingObservation.id).where(ListingObservation.source_key == key, ListingRevision.collected_at <= cutoff).limit(100)
            session.execute(delete(ListingRevision).where(ListingRevision.id.in_(revision_ids)))
            contact_ids = select(ListingContactEvidence.id).where(ListingContactEvidence.source_key == key, ListingContactEvidence.collected_at <= cutoff).limit(100)
            session.execute(delete(ListingContactEvidence).where(ListingContactEvidence.id.in_(contact_ids)))
            review_query = select(ListingReview).where(ListingReview.source_key == key)
            if expired_only:
                review_query = review_query.where(ListingReview.created_at <= cutoff)
            for review in session.scalars(review_query.where(
                ~ListingReview.snapshot.has_key("redacted"),
            ).limit(100)):
                review.snapshot = {name: value for name, value in review.snapshot.items() if name in {"evidence_key", "subject_type", "agent_key"}} | {"redacted": True}
            observation_ids = select(ListingAgentObservation.id).join(ListingObservation, ListingObservation.id == ListingAgentObservation.observation_id).where(ListingObservation.source_key == key, ListingAgentObservation.collected_at <= cutoff).limit(100)
            session.execute(delete(ListingAgentObservation).where(ListingAgentObservation.id.in_(observation_ids)))
            orphans = session.scalars(select(ListingAgent).where(
                ~select(ListingAgentObservation.id).where(ListingAgentObservation.agent_id == ListingAgent.id).exists(),
            ).limit(100)).all()
            for agent in orphans:
                if agent.suppressed_at is None and session.scalar(select(AgentCrmLink.id).where(AgentCrmLink.agent_id == agent.id).limit(1)) is None and session.scalar(select(ListingReview.id).where(ListingReview.candidate_ids.contains([str(agent.id)])).limit(1)) is None:
                    session.delete(agent)
                else:
                    agent.full_name, agent.normalized_name = "[retained identity]", ""
                    agent.brokerage, agent.normalized_brokerage = None, None
            remaining = session.scalar(select(func.count()).select_from(ListingObservation).where(ListingObservation.source_key == key)) or 0
            audit(session, source, "SOURCE_RETENTION_PURGE", {"observations_removed": len(rows), "expired_only": expired_only})
            return {"observations_removed": len(rows), "remaining_source_observations": remaining, "bounded_batch": True}
