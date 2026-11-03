from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Text, case, cast, func, literal, select, text, union_all
from sqlalchemy.orm import Session, sessionmaker

from dwellcall.crm.settings import CrmSettings
from dwellcall.database.models import (
    AgentCrmAudit, AgentCrmJob, AgentCrmLink, ListingAgent, ListingAgentObservation,
    ListingAuditEvent, ListingContactEvidence, ListingEntity, ListingImportRun,
    ListingObservation, ListingReview, ListingRevision, ListingSource,
)
from dwellcall.database.models.workspace import DiscoveryAttempt, DiscoveryJob
from dwellcall.errors import ApiError
from dwellcall.listings.queries import ListingQueries, current_field, visible_listing_ids, visible_source_condition


def visible_agents(mode: str):
    return select(ListingAgent.id).join(
        ListingAgentObservation, ListingAgentObservation.agent_id == ListingAgent.id,
    ).join(ListingObservation, ListingObservation.id == ListingAgentObservation.observation_id).join(
        ListingSource, ListingSource.key == ListingObservation.source_key,
    ).where(ListingAgent.data_mode == mode, ListingAgentObservation.active.is_(True), visible_source_condition(),
            ListingAgentObservation.collected_at > func.now() - ListingSource.permission["retention_days"].as_integer() * text("INTERVAL '1 day'"))


class WorkspaceQueries:
    def __init__(self, sessions: sessionmaker[Session], crm: CrmSettings) -> None:
        self.sessions, self.crm = sessions, crm
        self.queries = ListingQueries(sessions, crm)

    def dashboard(self, mode: str) -> dict[str, object]:
        now = datetime.now(UTC)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        with self.sessions() as session:
            listings = select(ListingEntity).where(ListingEntity.id.in_(visible_listing_ids(mode)))
            agents = select(ListingAgent).where(ListingAgent.id.in_(visible_agents(mode)))
            def count(query):
                return session.scalar(select(func.count()).select_from(query.subquery())) or 0
            contacts = select(ListingContactEvidence.agent_id).join(
                ListingAgent, ListingAgent.id == ListingContactEvidence.agent_id,
            ).join(ListingAgentObservation, ListingAgentObservation.id == ListingContactEvidence.agent_observation_id).join(
                ListingObservation, ListingObservation.id == ListingAgentObservation.observation_id,
            ).join(ListingSource, ListingSource.key == ListingContactEvidence.source_key).where(
                ListingAgent.data_mode == "live", ListingAgent.data_mode == mode,
                ListingAgent.review_required.is_(False), ListingAgent.suppressed_at.is_(None),
                ListingContactEvidence.active.is_(True), ListingAgentObservation.active.is_(True),
                ListingSource.permission["contacts_allowed"].as_boolean().is_(True),
                ListingSource.permission["trusted_verification"].as_boolean().is_(True),
                ListingContactEvidence.verification_status == "verified", visible_source_condition(),
                ListingContactEvidence.verified_at >= func.now() - ListingSource.permission["retention_days"].as_integer() * text("INTERVAL '1 day'"),
                ListingContactEvidence.collected_at >= func.now() - ListingSource.permission["retention_days"].as_integer() * text("INTERVAL '1 day'"),
                ListingAgentObservation.collected_at >= func.now() - ListingSource.permission["retention_days"].as_integer() * text("INTERVAL '1 day'"),
            ).distinct()
            metrics = {"listings": count(listings), "new_today": count(listings.where(ListingEntity.created_at >= today)),
                       "agents": count(agents), "verified_agents": count(contacts),
                       "synced": 0, "pending": 0, "failed": 0}
            if self.crm.agent_destination_configured:
                links = select(AgentCrmLink).where(AgentCrmLink.destination == self.crm.destination,
                                                  AgentCrmLink.agent_id.in_(visible_agents(mode)))
                metrics["synced"] = count(links.where(AgentCrmLink.synced_at.is_not(None)))
                for name, statuses in (("pending", ("pending", "sending", "retry_wait")), ("failed", ("failed", "unknown"))):
                    metrics[name] = count(select(AgentCrmJob).where(AgentCrmJob.link_id.in_(links.with_only_columns(AgentCrmLink.id)),
                        AgentCrmJob.status.in_(statuses), AgentCrmJob.retain_until > now))
            trend = session.execute(select(func.date_trunc("day", ListingEntity.created_at), func.count()).where(
                ListingEntity.id.in_(visible_listing_ids(mode)), ListingEntity.created_at >= today - timedelta(days=13),
            ).group_by(func.date_trunc("day", ListingEntity.created_at)).order_by(func.date_trunc("day", ListingEntity.created_at))).all()
            status_field = current_field("status")
            distribution = session.execute(select(status_field, func.count()).where(
                ListingEntity.id.in_(visible_listing_ids(mode)),
            ).group_by(status_field)).all()
            trends = {stamp.date().isoformat(): value for stamp, value in trend}
            return {"data_mode": mode, "crm_provider": self.crm.crm_provider, "as_of": now, "timezone": "UTC", "metrics": metrics,
                    "trend": [{"label": (today - timedelta(days=13-i)).date().isoformat(), "value": trends.get((today - timedelta(days=13-i)).date().isoformat(), 0)} for i in range(14)],
                    "distribution": [{"label": name or "unknown", "value": value} for name, value in distribution]}

    def listing(self, listing_id: UUID, mode: str) -> dict[str, object]:
        page = self.queries.listings(1, 1, mode, listing_id=listing_id)
        items = page["items"]
        if not items:
            raise ApiError(status_code=404, code="LISTING_NOT_FOUND", message="Listing is unavailable under current source rights")
        return items[0]

    def revisions(self, listing_id: UUID, mode: str, page: int, page_size: int) -> dict[str, object]:
        self.listing(listing_id, mode)
        with self.sessions() as session:
            query = select(ListingRevision, ListingSource).join(ListingObservation, ListingObservation.id == ListingRevision.observation_id).join(
                ListingSource, ListingSource.key == ListingObservation.source_key,
            ).where(ListingObservation.listing_id == listing_id, visible_source_condition(),
                    ListingRevision.collected_at > func.now() - ListingSource.permission["retention_days"].as_integer() * text("INTERVAL '1 day'"))
            total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
            rows = session.execute(query.order_by(ListingRevision.collected_at.desc(), ListingRevision.id).offset((page-1)*page_size).limit(page_size)).all()
            return {"items": [{"id": str(row.id), "at": row.collected_at, "events": row.events,
                               "source_key": source.key, "property": row.snapshot, "attribution": source.permission.get("attribution")} for row, source in rows],
                    "total": total, "page": page, "page_size": page_size}

    def activity(self, mode: str, page: int, page_size: int, kind: str | None, q: str, status: str | None = None) -> dict[str, object]:
        cutoff = func.now() - ListingSource.permission["retention_days"].as_integer() * text("INTERVAL '1 day'")
        permitted = (ListingSource.permission["display_allowed"].as_boolean().is_(True),
                     ListingSource.permission["store_allowed"].as_boolean().is_(True),
                     ListingSource.permission["data_mode"].astext == mode)
        imports = select(ListingImportRun.id.label("id"), literal("discovery").label("kind"), ListingImportRun.status.label("status"),
                         ListingImportRun.created_at.label("at"), ListingImportRun.source_key.label("source"), literal("Listing import").label("summary"),
                         ListingImportRun.id.label("reference")).join(ListingSource).where(*permitted, ListingImportRun.created_at > cutoff)
        audits = select(ListingAuditEvent.id, literal("system"), literal("recorded"), ListingAuditEvent.occurred_at,
                        ListingAuditEvent.source_key, ListingAuditEvent.event_type, ListingAuditEvent.id).join(ListingSource).where(*permitted, ListingAuditEvent.occurred_at > cutoff)
        revisions = select(ListingRevision.id, literal("listing"), case((ListingRevision.events.contains(["new"]), "new"), else_="updated"), ListingRevision.collected_at,
                           ListingObservation.source_key, func.concat("Listing events: ", cast(ListingRevision.events, Text)),
                           ListingObservation.listing_id).join(ListingObservation, ListingObservation.id == ListingRevision.observation_id).join(ListingSource).where(*permitted, visible_source_condition(), ListingRevision.collected_at > cutoff)
        reviews = select(ListingReview.id, literal("review"), ListingReview.status, ListingReview.created_at,
                         ListingReview.source_key, ListingReview.reason, ListingReview.id).join(ListingSource).where(*permitted, ListingReview.created_at > cutoff)
        attempts = select(DiscoveryAttempt.id, literal("discovery"), DiscoveryAttempt.status, DiscoveryAttempt.started_at,
                          DiscoveryJob.source_key, func.coalesce(DiscoveryAttempt.code, literal("Discovery job run")), DiscoveryAttempt.job_id).join(DiscoveryJob).join(ListingSource).where(*permitted, DiscoveryAttempt.started_at > cutoff)
        parts = [imports, audits, revisions, reviews, attempts]
        if self.crm.agent_destination_configured:
            parts.append(select(AgentCrmAudit.id, literal("crm"), AgentCrmJob.status, AgentCrmAudit.occurred_at,
                                literal(self.crm.crm_provider), AgentCrmAudit.event_type, AgentCrmJob.id).join(
                AgentCrmJob, AgentCrmJob.id == AgentCrmAudit.job_id,
            ).join(AgentCrmLink, AgentCrmLink.id == AgentCrmJob.link_id).where(
                AgentCrmAudit.destination == self.crm.destination, AgentCrmLink.agent_id.in_(visible_agents(mode)), AgentCrmJob.retain_until > func.now()))
        events = union_all(*parts).subquery()
        query = select(events)
        if kind:
            query = query.where(events.c.kind == kind)
        if q:
            query = query.where(events.c.summary.icontains(q, autoescape=True))
        if status:
            query = query.where(events.c.status == status)
        with self.sessions() as session:
            total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
            rows = session.execute(query.order_by(events.c.at.desc(), events.c.id).offset((page-1)*page_size).limit(page_size)).mappings().all()
            return {"items": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size}
