from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Numeric, cast, func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from dwellcall.database.models import (
    ListingAgent, ListingAgentObservation, ListingContactEvidence, ListingEntity,
    ListingImportRun, ListingObservation, ListingReview, ListingSource,
)
from dwellcall.crm.settings import CrmSettings
from dwellcall.listings.permissions import permission, retained
from dwellcall.listings.service import current_listing_data


def visible_source_condition() -> ColumnElement[bool]:
    return (
        ListingSource.permission["store_allowed"].as_boolean().is_(True)
        & ListingSource.permission["display_allowed"].as_boolean().is_(True)
        & (ListingObservation.collected_at > func.now() - ListingSource.permission["retention_days"].as_integer() * text("INTERVAL '1 day'"))
    )


def visible_listing_ids(mode: str):
    return select(ListingObservation.listing_id).join(
        ListingSource, ListingSource.key == ListingObservation.source_key,
    ).join(ListingEntity, ListingEntity.id == ListingObservation.listing_id).where(
        visible_source_condition(), ListingEntity.data_mode == mode,
    )


def current_field(name: str):
    return select(ListingObservation.snapshot[name].astext).join(
        ListingSource, ListingSource.key == ListingObservation.source_key,
    ).where(
        ListingObservation.listing_id == ListingEntity.id,
        visible_source_condition(), ListingObservation.snapshot.has_key(name),
    ).order_by(ListingObservation.source_updated_at.desc().nulls_last(),
               ListingObservation.collected_at.desc(), ListingSource.key.desc()).limit(1).correlate(ListingEntity).scalar_subquery()


def quality(data: dict[str, object]) -> dict[str, object]:
    fields = ("street_address", "city", "state", "postal_code", "price", "currency", "listing_date", "source_updated_at", "bedrooms", "bathrooms", "interior_sqft", "property_type", "listing_url", "status")
    missing = [name for name in fields if data.get(name) is None]
    return {"missing_fields": missing, "known_field_count": len(fields) - len(missing), "expected_field_count": len(fields), "facts_verified_by_dwellcall": False}


class ListingQueries:
    def __init__(self, sessions: sessionmaker[Session], crm_settings: CrmSettings | None = None) -> None:
        self.sessions, self.crm_settings = sessions, crm_settings

    def sources(self) -> list[dict[str, object]]:
        with self.sessions() as session:
            return [{
                "source_key": source.key, "permission_version": source.permission_version,
                "permissions": source.permission, "last_attempt_at": source.last_attempt_at,
                "last_success_at": source.last_success_at, "checkpoint": source.checkpoint,
                "scheduling_active": False, "live_verified": False,
            } for source in session.scalars(select(ListingSource).order_by(ListingSource.key)).all()]

    def listings(self, page: int, page_size: int, mode: str, *, q: str = "",
                 min_price: Decimal | None = None, max_price: Decimal | None = None,
                 property_type: str | None = None, status: str | None = None,
                 source: str | None = None, since: date | None = None, until: date | None = None,
                 sort: str = "newest", listing_id: UUID | None = None, agent_id: UUID | None = None) -> dict[str, object]:
        with self.sessions() as session:
            query = select(ListingEntity).where(ListingEntity.id.in_(visible_listing_ids(mode)))
            if listing_id:
                query = query.where(ListingEntity.id == listing_id)
            if agent_id:
                query = query.where(ListingEntity.id.in_(select(ListingObservation.listing_id).join(
                    ListingAgentObservation, ListingAgentObservation.observation_id == ListingObservation.id,
                ).join(ListingSource, ListingSource.key == ListingObservation.source_key).where(
                    ListingAgentObservation.agent_id == agent_id, ListingAgentObservation.active.is_(True),
                    visible_source_condition(),
                    ListingAgentObservation.collected_at > func.now() - ListingSource.permission["retention_days"].as_integer() * text("INTERVAL '1 day'"),
                )))
            if q:
                pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                query = query.where(or_(*(current_field(name).ilike(pattern, escape="\\") for name in ("street_address", "city", "state", "postal_code"))))
            if min_price is not None:
                query = query.where(cast(current_field("price"), Numeric) >= min_price)
            if max_price is not None:
                query = query.where(cast(current_field("price"), Numeric) <= max_price)
            for name, value in (("property_type", property_type), ("status", status)):
                if value:
                    query = query.where(current_field(name) == value)
            if since:
                query = query.where(current_field("listing_date") >= since.isoformat())
            if until:
                query = query.where(current_field("listing_date") <= until.isoformat())
            if source:
                query = query.where(ListingEntity.id.in_(select(ListingObservation.listing_id).join(
                    ListingSource, ListingSource.key == ListingObservation.source_key,
                ).where(ListingSource.key == source, visible_source_condition())))
            ordering = {
                "price_asc": cast(current_field("price"), Numeric).asc().nulls_last(),
                "price_desc": cast(current_field("price"), Numeric).desc().nulls_last(),
                "listing_date": current_field("listing_date").desc().nulls_last(),
                "updated": current_field("source_updated_at").desc().nulls_last(),
                "newest": ListingEntity.created_at.desc(),
            }
            total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
            entities = session.scalars(query.order_by(ordering.get(sort, ordering["newest"]), ListingEntity.id).offset((page - 1) * page_size).limit(page_size)).all()
            items = []
            for entity in entities:
                data, provenance = current_listing_data(session, entity.id)
                agents = session.scalars(select(ListingAgent.id).join(ListingAgentObservation, ListingAgentObservation.agent_id == ListingAgent.id).join(ListingObservation, ListingObservation.id == ListingAgentObservation.observation_id).join(ListingSource, ListingSource.key == ListingObservation.source_key).where(
                    ListingObservation.listing_id == entity.id, ListingAgentObservation.active.is_(True), visible_source_condition(),
                    ListingAgentObservation.collected_at > func.now() - ListingSource.permission["retention_days"].as_integer() * text("INTERVAL '1 day'"),
                ).distinct()).all()
                items.append({"id": str(entity.id), "data_mode": entity.data_mode, "property": data, "field_provenance": provenance, "agent_ids": [str(value) for value in agents], "data_quality": quality(data), "first_seen_at": entity.created_at, "updated_at": entity.updated_at, "review_required": self._listing_held(session, entity), "crm_export_eligible": False})
            return {"items": items, "total": total, "page": page, "page_size": page_size, "data_mode": mode}

    def agents(self, page: int, page_size: int, mode: str, *, reveal_contacts: bool, q: str = "", agent_id: UUID | None = None, state: str | None = None) -> dict[str, object]:
        with self.sessions() as session:
            query = select(ListingAgent).join(ListingAgentObservation, ListingAgentObservation.agent_id == ListingAgent.id).join(ListingObservation, ListingObservation.id == ListingAgentObservation.observation_id).join(ListingSource, ListingSource.key == ListingObservation.source_key).where(
                ListingAgent.data_mode == mode, ListingAgentObservation.active.is_(True), visible_source_condition(),
                ListingAgentObservation.collected_at > func.now() - ListingSource.permission["retention_days"].as_integer() * text("INTERVAL '1 day'"),
            ).distinct()
            if agent_id:
                query = query.where(ListingAgent.id == agent_id)
            if q:
                pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                query = query.where(or_(ListingAgentObservation.snapshot["full_name"].astext.ilike(pattern, escape="\\"), ListingAgentObservation.snapshot["brokerage"].astext.ilike(pattern, escape="\\")))
            if state == "suppressed":
                query = query.where(ListingAgent.suppressed_at.is_not(None))
            elif state == "review":
                query = query.where(ListingAgent.review_required.is_(True))
            total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
            items = []
            for agent in session.scalars(query.order_by(ListingAgent.created_at.desc(), ListingAgent.id).offset((page - 1) * page_size).limit(page_size)).all():
                records = session.execute(select(ListingAgentObservation, ListingObservation, ListingSource).join(ListingObservation, ListingObservation.id == ListingAgentObservation.observation_id).join(ListingSource, ListingSource.key == ListingObservation.source_key).where(ListingAgentObservation.agent_id == agent.id, ListingAgentObservation.active.is_(True)).order_by(ListingAgentObservation.collected_at.desc())).all()
                records = [(row, listing, source) for row, listing, source in records if retained(source, row.collected_at, display=True) and retained(source, listing.collected_at, display=True)]
                if not records:
                    continue
                newest = records[0][0]
                contacts = []
                if agent.suppressed_at is None and not agent.review_required:
                    evidence_rows = session.execute(select(ListingContactEvidence, ListingSource, ListingAgentObservation).join(ListingSource, ListingSource.key == ListingContactEvidence.source_key).join(ListingAgentObservation, ListingAgentObservation.id == ListingContactEvidence.agent_observation_id).where(ListingContactEvidence.agent_id == agent.id, ListingContactEvidence.active.is_(True), ListingAgentObservation.active.is_(True))).all()
                    for evidence, source, observation in evidence_rows:
                        policy = permission(source)
                        if not policy.contacts_allowed or not retained(source, evidence.collected_at, display=True) or not retained(source, observation.collected_at, display=True):
                            continue
                        status = evidence.verification_status
                        if not policy.trusted_verification or evidence.verified_at is None or evidence.verified_at < datetime.now(UTC) - timedelta(days=policy.retention_days):
                            status = "unverified"
                        contacts.append({
                            "kind": evidence.kind, "value": evidence.value if reveal_contacts else "[restricted]",
                            "direct": evidence.direct, "verification_status": status,
                            "source_claimed_verification": evidence.claimed_verification,
                            "source_confidence": str(evidence.confidence) if evidence.confidence is not None else None,
                            "source_key": source.key, "source_reference": evidence.source_reference if reveal_contacts else None,
                            "source_url": evidence.source_url if reveal_contacts else None,
                            "verified_at": evidence.verified_at, "collected_at": evidence.collected_at,
                        })
                from dwellcall.crm.agent_mapping import AgentIneligible, export_snapshot
                from dwellcall.database.models import AgentCrmJob, AgentCrmLink

                try:
                    export_snapshot(session, agent.id)
                    export_eligible = True
                except AgentIneligible:
                    export_eligible = False
                crm_link = None
                if self.crm_settings and self.crm_settings.agent_destination_configured:
                    crm_link = session.scalar(select(AgentCrmLink).where(AgentCrmLink.agent_id == agent.id, AgentCrmLink.destination == self.crm_settings.destination))
                latest_job = session.scalar(select(AgentCrmJob).where(AgentCrmJob.link_id == crm_link.id).order_by(AgentCrmJob.created_at.desc()).limit(1)) if crm_link else None
                items.append({
                    "id": str(agent.id), "data_mode": agent.data_mode,
                    "full_name": newest.snapshot["full_name"], "brokerage": newest.snapshot.get("brokerage"),
                    "profile_url": newest.snapshot.get("profile_url"), "field_provenance": newest.provenance,
                    "contacts": contacts, "review_required": agent.review_required,
                    "suppressed": agent.suppressed_at is not None,
                    "listing_ids": sorted({str(listing.listing_id) for _, listing, _ in records}),
                    "active_listings": sum(1 for listing_id in {listing.listing_id for _, listing, _ in records} if current_listing_data(session, listing_id)[0].get("status") == "active"),
                    "source_keys": sorted({source.key for _, _, source in records}),
                    "crm_export_eligible": export_eligible, "crm_sync_status": latest_job.status if latest_job else "not_queued",
                    "ghl_contact_id": crm_link.contact_id if crm_link and reveal_contacts and self.crm_settings and self.crm_settings.crm_provider == "gohighlevel" else None,
                    "crm_provider": self.crm_settings.crm_provider if self.crm_settings else "none",
                    "crm_contact_id": crm_link.contact_id if crm_link and reveal_contacts else None,
                    "crm_company_id": crm_link.company_id if crm_link and reveal_contacts else None, "outreach_permission": False,
                })
            return {"items": items, "total": total, "page": page, "page_size": page_size, "data_mode": mode}

    def runs(self, limit: int = 20) -> list[dict[str, object]]:
        with self.sessions() as session:
            return [{**run.result, "created_at": run.created_at, "filters": run.filters} for run in session.scalars(select(ListingImportRun).order_by(ListingImportRun.created_at.desc()).limit(limit)).all()]

    @staticmethod
    def _listing_held(session: Session, entity: ListingEntity) -> bool:
        observations = session.scalars(select(ListingObservation).where(ListingObservation.listing_id == entity.id)).all()
        return any(session.scalar(select(ListingReview.id).where(
            ListingReview.source_key == row.source_key,
            ListingReview.source_listing_id == row.source_listing_id,
            (ListingReview.status != "approved") | ListingReview.applied_at.is_(None),
        ).limit(1)) is not None for row in observations)

    def reviews(self, limit: int = 50) -> list[dict[str, object]]:
        from dwellcall.listings.reviews import review_data

        with self.sessions() as session:
            rows = session.execute(select(ListingReview, ListingSource).join(ListingSource, ListingSource.key == ListingReview.source_key).order_by(ListingReview.created_at.desc()).limit(limit)).all()
            return [review_data(row) for row, source in rows if retained(source, row.created_at, display=True)]
