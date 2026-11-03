from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from dwellcall.crm.agent_mapping import AgentIneligible, export_snapshot, snapshot_fingerprint
from dwellcall.crm.agent_schemas import AgentAuditPage, AgentJobPage, AgentJobStatus, AgentPreview, AgentPreviewPage
from dwellcall.crm.settings import CrmSettings
from dwellcall.database.models import AgentCrmAudit, AgentCrmDestination, AgentCrmJob, AgentCrmLink, ListingAgent
from dwellcall.errors import ApiError
from dwellcall.listings.service import ingestion_lock


def agent_audit(session: Session, destination: str, event: str, job_id: UUID | None = None, reference: str | None = None) -> None:
    session.add(AgentCrmAudit(id=uuid4(), destination=destination, event_type=event,
                             job_id=job_id, evidence_reference=reference, occurred_at=datetime.now(UTC)))


def destination_state(session: Session, settings: CrmSettings) -> AgentCrmDestination:
    row = session.get(AgentCrmDestination, settings.destination, with_for_update=True)
    if row is None:
        row = AgentCrmDestination(destination=settings.destination, fields=dict(settings.agent_fields),
                                  capabilities={}, paused=False, next_attempt_at=datetime.now(UTC))
        session.add(row)
        session.flush()
    return row


def job_status(row: AgentCrmJob, link: AgentCrmLink) -> AgentJobStatus:
    return AgentJobStatus(id=row.id, agent_id=link.agent_id, status=row.status, code=row.code,
                          attempts=row.attempts, next_attempt_at=row.next_attempt_at, contact_id=link.contact_id,
                          opportunity_id=link.opportunity_id, company_id=link.company_id, last_synced_at=link.synced_at, created_at=row.created_at)


def reserve_agent(session: Session, settings: CrmSettings, agent_id: UUID) -> AgentCrmJob:
    state = destination_state(session, settings)
    if not state.configured_at or settings.required_agent_fields - state.fields.keys():
        raise ApiError(status_code=409, code=settings.agent_code("SETUP_REQUIRED"), message="Inspect and configure the CRM field mapping first")
    try:
        snapshot = export_snapshot(session, agent_id)
    except AgentIneligible as error:
        raise ApiError(status_code=409, code=str(error), message="Agent does not meet current identity, verification or source export requirements") from None
    digest = snapshot_fingerprint(settings, snapshot, state.fields)
    link = session.scalar(select(AgentCrmLink).where(AgentCrmLink.agent_id == agent_id, AgentCrmLink.destination == state.destination).with_for_update())
    if link is None:
        link = AgentCrmLink(id=uuid4(), agent_id=agent_id, destination=state.destination)
        session.add(link)
        session.flush()
    rows = list(session.scalars(select(AgentCrmJob).where(AgentCrmJob.link_id == link.id).with_for_update()))
    if any(row.status in {"sending", "unknown"} for row in rows):
        raise ApiError(status_code=409, code=settings.agent_code("OUTCOME_UNRESOLVED"), message="Reconcile the prior uncertain synchronization before reserving another")
    existing = next((row for row in rows if row.fingerprint == digest), None)
    if existing is not None and (existing.status not in {"sent", "cancelled"} or link.synced_fingerprint == digest):
        return existing
    now = datetime.now(UTC)
    for old in rows:
        if old.status in {"pending", "retry_wait"}:
            old.status, old.code, old.payload = "cancelled", settings.agent_code("SNAPSHOT_SUPERSEDED"), None
            agent_audit(session, state.destination, settings.agent_code("SNAPSHOT_SUPERSEDED"), old.id)
    row = existing or AgentCrmJob(id=uuid4(), link_id=link.id, fingerprint=digest, created_at=now)
    row.status, row.code, row.attempts = "pending", None, 0
    row.payload, row.fields = snapshot.model_dump(mode="json"), dict(state.fields)
    row.next_attempt_at = now
    row.retain_until = now + timedelta(days=settings.crm_retention_days)
    session.add(row)
    session.flush()
    agent_audit(session, state.destination, settings.agent_code("EXPORT_RESERVED"), row.id)
    return row


def bind_verified_contact(session: Session, settings: CrmSettings, agent_id: UUID, contact_id: str, reference: str) -> dict[str, object]:
    state = destination_state(session, settings)
    collision = session.scalar(select(AgentCrmLink).where(AgentCrmLink.destination == state.destination, AgentCrmLink.contact_id == contact_id))
    if collision and collision.agent_id != agent_id:
        raise ApiError(status_code=409, code=settings.agent_code("LOCAL_CONTACT_COLLISION"), message="Contact already belongs to another local agent")
    link = session.scalar(select(AgentCrmLink).where(AgentCrmLink.destination == state.destination, AgentCrmLink.agent_id == agent_id).with_for_update())
    if link and link.contact_id not in (None, contact_id):
        raise ApiError(status_code=409, code=settings.agent_code("MAPPING_IMMUTABLE"), message="Existing contact mappings cannot be reassigned")
    if link and session.scalar(select(AgentCrmJob.id).where(AgentCrmJob.link_id == link.id, AgentCrmJob.status.in_(("sending", "unknown"))).limit(1)):
        raise ApiError(status_code=409, code=settings.agent_code("OUTCOME_UNRESOLVED"), message="Reconcile the uncertain job before binding")
    if link is None:
        link = AgentCrmLink(id=uuid4(), agent_id=agent_id, destination=state.destination)
        session.add(link)
    link.contact_id = contact_id
    session.flush()
    snapshot = export_snapshot(session, agent_id)
    digest = snapshot_fingerprint(settings, snapshot, state.fields)
    for job in session.scalars(select(AgentCrmJob).where(
        AgentCrmJob.link_id == link.id, AgentCrmJob.status == "failed",
        AgentCrmJob.code.in_(tuple(settings.agent_code(suffix) for suffix in ("CONTACT_REVIEW_REQUIRED", "CONFLICTING_CONTACT_MATCHES", "MULTIPLE_CONTACT_MATCHES"))),
        AgentCrmJob.fingerprint == digest, AgentCrmJob.retain_until > datetime.now(UTC),
    )):
        job.status, job.code, job.attempts = "retry_wait", settings.agent_code("CONTACT_CONFIRMED_RETRY_UPDATE"), 0
        job.next_attempt_at = max(datetime.now(UTC), state.next_attempt_at)
        agent_audit(session, state.destination, settings.agent_code("BOUND_CONTACT_RETRY"), job.id, reference)
    agent_audit(session, state.destination, settings.agent_code("CONTACT_BOUND"), reference=reference)
    return {"agent_id": str(agent_id), "contact_id": link.contact_id, "external_write": False}


class AgentCrmService:
    def __init__(self, sessions: sessionmaker[Session], settings: CrmSettings) -> None:
        self.sessions, self.settings = sessions, settings

    def queue(self, agent_ids: list[UUID]) -> list[AgentJobStatus]:
        settings = self.settings
        if not self.settings.agent_provider_selected or not self.settings.dispatch_enabled:
            raise ApiError(status_code=409, code=settings.agent_code("SYNC_DISABLED"), message="Owner-approved CRM dispatch must be enabled before queuing")
        with self.sessions() as session, session.begin():
            ingestion_lock(session)
            result = []
            for agent_id in dict.fromkeys(agent_ids):
                row = reserve_agent(session, self.settings, agent_id)
                link = session.get(AgentCrmLink, row.link_id)
                if link is None:
                    raise RuntimeError("Reserved CRM identity mapping is unavailable")
                result.append(job_status(row, link))
            return result

    def preview(self, page: int, page_size: int) -> AgentPreviewPage:
        with self.sessions() as session:
            total = session.scalar(select(func.count()).select_from(ListingAgent)) or 0
            ids = session.scalars(select(ListingAgent.id).order_by(ListingAgent.created_at, ListingAgent.id).offset((page - 1) * page_size).limit(page_size))
            items = []
            for agent_id in ids:
                link = session.scalar(select(AgentCrmLink).where(AgentCrmLink.agent_id == agent_id, AgentCrmLink.destination == self.settings.destination)) if self.settings.agent_destination_configured else None
                try:
                    snapshot = export_snapshot(session, agent_id)
                    item = AgentPreview(agent_id=agent_id, eligible=True, snapshot=snapshot)
                except AgentIneligible as error:
                    item = AgentPreview(agent_id=agent_id, eligible=False, reason=str(error))
                if link:
                    item.company_id, item.last_synced_at = link.company_id, link.synced_at
                    item.contact_id = link.contact_id
                    latest = session.scalar(select(AgentCrmJob).where(AgentCrmJob.link_id == link.id).order_by(AgentCrmJob.created_at.desc()).limit(1))
                    item.sync_status = latest.status if latest else None
                items.append(item)
            return AgentPreviewPage(items=items, page=page, page_size=page_size, total=total)

    def history(self, page: int, page_size: int, status: str | None = None, agent_id: UUID | None = None) -> AgentJobPage:
        if not self.settings.agent_destination_configured:
            return AgentJobPage(items=[], page=page, page_size=page_size, total=0)
        with self.sessions() as session:
            query = select(AgentCrmJob, AgentCrmLink).join(AgentCrmLink, AgentCrmLink.id == AgentCrmJob.link_id).where(AgentCrmLink.destination == self.settings.destination)
            if status:
                query = query.where(AgentCrmJob.status == status)
            if agent_id:
                query = query.where(AgentCrmLink.agent_id == agent_id)
            total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
            rows = session.execute(query.order_by(AgentCrmJob.created_at.desc(), AgentCrmJob.id).offset((page - 1) * page_size).limit(page_size))
            return AgentJobPage(items=[job_status(row, link) for row, link in rows], page=page, page_size=page_size, total=total)

    def retry(self, job_id: UUID, reference: str) -> AgentJobStatus:
        settings = self.settings
        if not self.settings.agent_provider_selected or not self.settings.dispatch_enabled:
            raise ApiError(status_code=409, code=settings.agent_code("SYNC_DISABLED"), message="Enable approved CRM dispatch before retrying")
        with self.sessions() as session, session.begin():
            ingestion_lock(session)
            state = destination_state(session, self.settings)
            row = session.get(AgentCrmJob, job_id, with_for_update=True)
            link = session.get(AgentCrmLink, row.link_id) if row else None
            if row is None or link is None or link.destination != state.destination:
                raise ApiError(status_code=404, code=settings.agent_code("JOB_NOT_FOUND"), message="Synchronization job not found")
            safe_codes = {settings.agent_code("RATE_LIMITED"), settings.agent_code("NOT_SUBMITTED"), settings.agent_code("READ_UNAVAILABLE"), settings.agent_code("CONTACT_CONFIRMED_RETRY_UPDATE"), settings.agent_code("REJECTED_401"), settings.agent_code("REJECTED_403")}
            if row.status not in {"failed", "retry_wait"} or row.code not in safe_codes or row.retain_until <= datetime.now(UTC):
                raise ApiError(status_code=409, code=settings.agent_code("RETRY_UNSAFE"), message="Only retained, confirmed-safe failures can be retried; reconcile unknown writes first")
            try:
                current = export_snapshot(session, link.agent_id)
            except AgentIneligible as error:
                raise ApiError(status_code=409, code=str(error), message="The agent is no longer export eligible") from None
            if snapshot_fingerprint(self.settings, current, state.fields) != row.fingerprint:
                raise ApiError(status_code=409, code=settings.agent_code("SNAPSHOT_CHANGED"), message="Queue a fresh eligible snapshot instead")
            row.payload, row.attempts = current.model_dump(mode="json"), 0
            row.status, row.next_attempt_at, state.paused = "retry_wait", max(datetime.now(UTC), state.next_attempt_at), False
            agent_audit(session, state.destination, settings.agent_code("OPERATOR_RETRY"), row.id, reference)
            return job_status(row, link)


def queue_import_agents(session: Session, settings: CrmSettings, source_key: str, listing_ids: list[str]) -> dict[str, object]:
    from dwellcall.database.models import ListingAgentObservation, ListingObservation

    ids = session.scalars(select(ListingAgentObservation.agent_id).join(
        ListingObservation, ListingObservation.id == ListingAgentObservation.observation_id,
    ).where(ListingObservation.source_key == source_key, ListingObservation.source_listing_id.in_(listing_ids)).distinct().order_by(ListingAgentObservation.agent_id).limit(51)).all()
    queued, excluded = 0, 0
    codes: set[str] = set()
    for agent_id in ids[:50]:
        try:
            reserve_agent(session, settings, agent_id)
            queued += 1
        except ApiError as error:
            excluded += 1
            codes.add(error.code)
    return {"queued": queued, "excluded": excluded, "codes": sorted(codes), "more_available": len(ids) > 50}


def job_audit_history(sessions: sessionmaker[Session], settings: CrmSettings, job_id: UUID,
                      page: int, page_size: int) -> AgentAuditPage:
    from dwellcall.crm.agent_schemas import AgentAuditEntry, AgentAuditPage

    with sessions() as session:
        row = session.get(AgentCrmJob, job_id)
        link = session.get(AgentCrmLink, row.link_id) if row else None
        if row is None or link is None or link.destination != settings.destination:
            raise ApiError(status_code=404, code=settings.agent_code("JOB_NOT_FOUND"), message="Synchronization job not found")
        query = select(AgentCrmAudit).where(AgentCrmAudit.job_id == job_id)
        total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = session.scalars(query.order_by(AgentCrmAudit.occurred_at, AgentCrmAudit.id).offset((page - 1) * page_size).limit(page_size))
        return AgentAuditPage(items=[AgentAuditEntry(event_type=event.event_type, evidence_reference=event.evidence_reference,
                                                   occurred_at=event.occurred_at) for event in rows],
                              page=page, page_size=page_size, total=total)
