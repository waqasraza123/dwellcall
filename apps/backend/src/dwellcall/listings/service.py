import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from dwellcall.crm.settings import CrmSettings
from dwellcall.crm.job_execution import check_job_deadline, job_budget
from dwellcall.database.models import (
    ListingAuditEvent, ListingEntity, ListingImportRun, ListingObservation, ListingReview, ListingRevision, ListingSource,
)
from dwellcall.errors import ApiError
from dwellcall.listings.contracts import ListingProvider
from dwellcall.listings.identity import evidence_key, hold_review, reviewed_decision, update_agents
from dwellcall.listings.normalization import address_key, fingerprint, matches_filters, text_key
from dwellcall.listings.permissions import permission, permitted_geography, permitted_url, retained
from dwellcall.listings.providers import FileListingProvider
from dwellcall.listings.schemas import DiscoveryFilters, ListingRecord, SourcePermissionInput
from dwellcall.listings.settings import ListingSettings


def record_provenance(source: ListingSource, source_id: str, collected: datetime) -> dict[str, object]:
    return {
        "source_key": source.key, "source_listing_id": source_id,
        "permission_version": source.permission_version, "collected_at": collected.isoformat(),
        "data_mode": permission(source).data_mode, "attribution": permission(source).attribution,
    }


def current_listing_data(session: Session, entity_id: UUID) -> tuple[dict[str, Any], dict[str, object]]:
    rows = list(session.execute(
        select(ListingObservation, ListingSource).join(ListingSource, ListingSource.key == ListingObservation.source_key)
        .where(ListingObservation.listing_id == entity_id)
    ).all())
    rows = [(row, source) for row, source in rows if retained(source, row.collected_at, display=True)]
    rows.sort(key=lambda item: (
        item[0].source_updated_at or datetime.min.replace(tzinfo=UTC),
        item[0].collected_at, item[1].key,
    ), reverse=True)
    data: dict[str, Any] = {}
    provenance: dict[str, object] = {}
    for row, source in rows:
        for name, value in row.snapshot.items():
            if name not in data:
                data[name] = value
                provenance[name] = record_provenance(source, row.source_listing_id, row.collected_at)
    return data, provenance


def materialize_listing(session: Session, entity: ListingEntity) -> None:
    data, provenance = current_listing_data(session, entity.id)
    entity.snapshot, entity.provenance = data, provenance
    entity.address_key = address_key(data)
    for name in ("street_address", "city", "state", "postal_code", "currency", "status", "property_type"):
        setattr(entity, name, data.get(name))
    entity.price = Decimal(str(data["price"])) if data.get("price") is not None else None
    entity.source_updated_at = datetime.fromisoformat(str(data["source_updated_at"])) if data.get("source_updated_at") is not None else None
    winning = provenance.get("source_updated_at") or next(iter(provenance.values()), None)
    if isinstance(winning, dict):
        entity.winning_source = str(winning["source_key"])
    entity.updated_at = datetime.now(UTC)


def audit(session: Session, source: ListingSource, event: str, details: dict[str, object]) -> None:
    session.add(ListingAuditEvent(id=uuid4(), source_key=source.key, event_type=event, details=details, occurred_at=datetime.now(UTC)))


def ingestion_lock(session: Session) -> None:
    acquired = session.scalar(text("SELECT pg_try_advisory_xact_lock(hashtextextended(:name, 0))"), {"name": "dwellcall.listing-ingestion"})
    if not acquired:
        raise ApiError(status_code=429, code="INGESTION_BUSY", message="Another bounded import or maintenance operation is running")
    session.execute(text("SET LOCAL statement_timeout = '5000ms'"))
    session.execute(text("SET LOCAL lock_timeout = '250ms'"))


class ListingIngestionService:
    def __init__(self, sessions: sessionmaker[Session], settings: ListingSettings, crm_settings: CrmSettings | None = None) -> None:
        self.sessions, self.settings, self.crm_settings = sessions, settings, crm_settings

    @staticmethod
    def _source(session: Session, key: str) -> ListingSource:
        source = session.get(ListingSource, key, with_for_update=True)
        if source is None:
            raise ApiError(status_code=404, code="SOURCE_NOT_FOUND", message="Register source permissions before ingestion")
        return source

    def ingest(
        self, source_key: str, content: bytes, format: Literal["csv", "json"],
        request_id: UUID, filters: DiscoveryFilters | None = None,
    ) -> dict[str, object]:
        if not self.settings.listing_intelligence_enabled:
            raise ApiError(status_code=404, code="INTELLIGENCE_DISABLED", message="Listing ingestion is disabled")
        filters = filters or DiscoveryFilters()
        request_hash = fingerprint({"content": hashlib.sha256(content).hexdigest(), "format": format, "filters": filters.model_dump(mode="json")})
        now = datetime.now(UTC)
        today = datetime.combine(now.date(), datetime.min.time(), tzinfo=UTC)
        with job_budget(20), self.sessions() as session, session.begin():
            ingestion_lock(session)
            source = self._source(session, source_key)
            policy = permission(source)
            if not (policy.enabled and policy.access_confirmed and policy.retrieve_allowed and policy.store_allowed):
                raise ApiError(status_code=403, code="SOURCE_PERMISSION_REQUIRED", message="Confirmed retrieval/storage rights and activation are required")
            if policy.provider != "file":
                raise ApiError(status_code=409, code="PROVIDER_UNAVAILABLE", message="Only permission-scoped local file ingestion is implemented")
            existing = session.scalar(select(ListingImportRun).where(ListingImportRun.source_key == source.key, ListingImportRun.request_id == request_id))
            if existing is not None:
                if existing.request_fingerprint != request_hash:
                    raise ApiError(status_code=409, code="IDEMPOTENCY_KEY_REUSED", message="The request ID was used for different content or filters")
                return {**existing.result, "replayed": True}
            try:
                provider: ListingProvider = FileListingProvider(content, format, self.settings, synthetic=policy.data_mode == "synthetic")
                batch = provider.fetch(source.checkpoint, filters)
            except ValueError:
                raise ApiError(status_code=422, code="IMPORT_FORMAT_INVALID", message="Provide a bounded CSV or JSON document matching the registered source data mode") from None
            runs = session.scalar(select(func.count()).select_from(ListingImportRun).where(ListingImportRun.created_at >= today)) or 0
            received = session.scalar(select(func.sum(ListingImportRun.received_count)).where(ListingImportRun.created_at >= today)) or 0
            if runs >= self.settings.listing_daily_run_limit or received + batch.received > self.settings.listing_daily_record_limit:
                raise ApiError(status_code=429, code="INGESTION_DAILY_LIMIT", message="The configured daily file-ingestion limit has been reached")
            run = ListingImportRun(
                id=uuid4(), source_key=source.key, request_id=request_id, request_fingerprint=request_hash,
                permission_version=source.permission_version, created_at=now, received_count=batch.received,
                status="processing", result={},
                filters=filters.model_dump(mode="json"),
            )
            session.add(run)
            session.flush()
            counters = {name: 0 for name in ("new_listings", "linked_sources", "updated", "duplicates", "stale", "filtered", "reviews", "new_agents")}
            errors = [{"row": error.row, "code": error.code} for error in batch.errors]
            for number, record in batch.records:
                check_job_deadline()
                outcome, agents, reviews = self._record(session, source, policy, record, run, filters)
                counters[outcome] += 1
                counters["new_agents"] += agents
                counters["reviews"] += reviews
                if outcome == "filtered" and reviews:
                    errors.append({"row": number, "code": "SOURCE_SCOPE_REJECTED"})
            crm_summary: dict[str, object] = {"queued": 0}
            if self.crm_settings is not None and self.crm_settings.ghl_auto_queue and self.crm_settings.dispatch_enabled and policy.data_mode == "live":
                from dwellcall.crm.agent_service import queue_import_agents

                crm_summary = queue_import_agents(session, self.crm_settings, source.key, [record.source_listing_id for _, record in batch.records])
            source.last_attempt_at = now
            check_job_deadline()
            status = "failed" if batch.received and len(batch.errors) == batch.received else "partial" if errors or counters["reviews"] else "completed"
            if status == "completed":
                source.checkpoint = fingerprint({"file": batch.checkpoint, "filters": filters.model_dump(mode="json"), "permission_version": source.permission_version})
                source.last_success_at = now
            result: dict[str, object] = {
                "run_id": str(run.id), "source_key": source.key, "data_mode": policy.data_mode, "crm": crm_summary,
                "status": status, "received": batch.received, **counters, "errors": errors,
                "checkpoint": source.checkpoint, "replayed": False,
            }
            run.status, run.result = status, result
            audit(session, source, "LISTING_IMPORT_COMPLETED", {"run_id": str(run.id), "status": status, **counters})
            session.flush()
            check_job_deadline()
            return result

    def _record(
        self, session: Session, source: ListingSource, policy: SourcePermissionInput,
        record: ListingRecord, run: ListingImportRun, filters: DiscoveryFilters,
    ) -> tuple[str, int, int]:
        now = datetime.now(UTC)
        patch = record.model_dump(mode="json", exclude={"agents", "source_listing_id"}, exclude_unset=True)
        observation = session.scalar(select(ListingObservation).where(
            ListingObservation.source_key == source.key, ListingObservation.source_listing_id == record.source_listing_id,
        ))
        data = {**(observation.snapshot if observation else {}), **patch}
        if not permitted_geography(data, policy) or not permitted_url(data.get("listing_url"), policy):
            return "filtered", 0, 1
        raw = record.model_dump(mode="json", exclude_unset=True)
        if not policy.contacts_allowed and "agents" in raw:
            raw["agents"] = [agent.model_dump(mode="json", exclude={"contacts"}, exclude_unset=True) for agent in record.agents]
        record_hash = fingerprint({"record": raw, "permission_version": source.permission_version})
        approved_unapplied = session.scalar(select(ListingReview.id).where(
            ListingReview.source_key == source.key,
            ListingReview.source_listing_id == record.source_listing_id,
            ListingReview.status == "approved", ListingReview.applied_at.is_(None),
        ).limit(1))
        if observation is not None and observation.fingerprint == record_hash and approved_unapplied is None:
            return "duplicates", 0, 0
        listing_evidence: dict[str, object] = {
            "subject_type": "listing", "property": data,
            "evidence_key": evidence_key(source, raw),
        }
        decision = reviewed_decision(session, source, record.source_listing_id, str(listing_evidence["evidence_key"]))
        if decision is not None and decision.status == "rejected":
            return "reviews", 0, 0
        if record.source_updated_at is not None and record.source_updated_at > now + timedelta(minutes=5):
            hold_review(session, source, record.source_listing_id, "FUTURE_SOURCE_TIMESTAMP", {"source_listing_id": record.source_listing_id})
            return "reviews", 0, 0
        if record.listing_namespace and record.listing_namespace not in policy.identifier_namespaces:
            hold_review(session, source, record.source_listing_id, "LISTING_NAMESPACE_UNAPPROVED", {"namespace": record.listing_namespace})
            return "reviews", 0, 0
        previous = observation.snapshot if observation else {}
        facts_changed = fingerprint({key: value for key, value in previous.items() if key != "source_updated_at"}) != fingerprint({key: value for key, value in data.items() if key != "source_updated_at"})
        if observation is not None:
            if record.source_updated_at is not None and observation.source_updated_at is not None and record.source_updated_at < observation.source_updated_at:
                return "stale", 0, 0
            if facts_changed and (record.source_updated_at is None or (observation.source_updated_at is not None and record.source_updated_at <= observation.source_updated_at)):
                hold_review(session, source, record.source_listing_id, "AMBIGUOUS_UPDATE_ORDER", {"source_listing_id": record.source_listing_id})
                return "reviews", 0, 0
        if observation is None and not matches_filters(data, filters):
            return "filtered", 0, 0
        entity = session.get(ListingEntity, observation.listing_id) if observation else None
        approved_match = decision is not None and decision.status == "approved"
        if approved_match:
            entity = session.get(ListingEntity, UUID(str(decision.resolution["candidate_id"])))
            if entity is None or entity.data_mode != policy.data_mode:
                raise ApiError(status_code=409, code="REVIEW_CANDIDATE_UNAVAILABLE", message="The approved listing is no longer available")
        if entity is None and record.listing_namespace:
            entity = session.scalar(select(ListingEntity).where(
                ListingEntity.data_mode == policy.data_mode,
                ListingEntity.listing_namespace == record.listing_namespace,
                ListingEntity.listing_reference == record.listing_reference,
            ))
        if entity is not None:
            old_key, new_key = entity.address_key, address_key(data)
            prior_observations = session.execute(
                select(ListingObservation, ListingSource)
                .join(ListingSource, ListingSource.key == ListingObservation.source_key)
                .where(ListingObservation.listing_id == entity.id)
            ).all()
            conflicting_address = any(
                prior.snapshot.get(name) and data.get(name)
                and text_key(str(prior.snapshot[name])) != text_key(str(data[name]))
                for prior, prior_source in prior_observations
                if retained(prior_source, prior.collected_at)
                for name in ("street_address", "city", "state", "postal_code", "country")
            )
            if not approved_match and (conflicting_address or (old_key and new_key and old_key != new_key) or (
                observation is not None and "listing_reference" in patch and
                (data.get("listing_namespace"), data.get("listing_reference")) != (entity.listing_namespace, entity.listing_reference)
            )):
                hold_review(session, source, record.source_listing_id, "LISTING_IDENTITY_CONFLICT", listing_evidence, {entity.id})
                return "reviews", 0, 0
        created = entity is None
        identity_reviews = 0
        if entity is None:
            entity = ListingEntity(
                id=uuid4(), data_mode=policy.data_mode, listing_namespace=record.listing_namespace,
                listing_reference=record.listing_reference, snapshot={}, provenance={},
                winning_source=source.key, created_at=now, updated_at=now,
            )
            session.add(entity)
            session.flush()
            key = address_key(data)
            candidates = set(session.scalars(select(ListingEntity.id).where(
                ListingEntity.address_key == key, ListingEntity.id != entity.id,
                ListingEntity.data_mode == policy.data_mode,
            ).limit(20)).all()) if key else set()
            if candidates:
                hold_review(session, source, record.source_listing_id, "ADDRESS_ONLY_NOT_MERGED", listing_evidence, candidates | {entity.id})
                identity_reviews += 1
        linked = observation is None
        if observation is None:
            observation = ListingObservation(id=uuid4(), source_key=source.key, source_listing_id=record.source_listing_id, listing_id=entity.id)
            session.add(observation)
        old_entity_id = observation.listing_id
        observation.listing_id = entity.id
        if approved_match and decision is not None and decision.applied_at is None:
            audit(session, source, "LISTING_REVIEW_APPLIED", {"review_id": str(decision.id), "candidate_id": str(entity.id)})
            decision.applied_at = now
        observation.snapshot, observation.fingerprint = data, record_hash
        observation.permission_version, observation.collected_at = source.permission_version, now
        if record.source_updated_at is not None:
            observation.source_updated_at = record.source_updated_at
        session.flush()
        agents, reviews = update_agents(session, source, observation, record.agents, policy) if "agents" in record.model_fields_set else (0, 0)
        events = ["new" if created else "source_linked" if linked else "updated"]
        if previous.get("price") is not None and previous.get("price") != data.get("price"):
            events.append("price_changed")
        if data.get("status") in {"pending", "sold", "removed"} and previous.get("status") != data.get("status"):
            events.append(str(data["status"]))
        if session.scalar(select(ListingRevision.id).where(ListingRevision.observation_id == observation.id, ListingRevision.fingerprint == record_hash)) is None:
            session.add(ListingRevision(
                id=uuid4(), observation_id=observation.id, run_id=run.id, fingerprint=record_hash,
                snapshot=data,
                events=events, provenance=record_provenance(source, record.source_listing_id, now), collected_at=now,
            ))
        materialize_listing(session, entity)
        if old_entity_id != entity.id:
            old_entity = session.get(ListingEntity, old_entity_id)
            if old_entity is not None:
                materialize_listing(session, old_entity)
        return "new_listings" if created else "linked_sources" if linked else "updated", agents, reviews + identity_reviews
