from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from dwellcall.crm.agent_mapping import AgentIneligible, export_snapshot, snapshot_fingerprint
from dwellcall.crm.agent_schemas import AgentContactSnapshot, AgentJobStatus
from dwellcall.crm.agent_service import agent_audit, destination_state, job_status
from dwellcall.crm.contracts import AgentCrmProvider, AgentDeliveryResult, AgentExportRequest
from dwellcall.crm.job_execution import JobDeadlineExceeded, check_job_deadline, job_budget, provider_client
from dwellcall.crm.jobs import JOB_LOCK_NAME, JobBatchResult
from dwellcall.crm.providers.gohighlevel import GoHighLevelProvider
from dwellcall.crm.settings import CrmSettings
from dwellcall.database.models import AgentCrmDestination, AgentCrmJob, AgentCrmLink
from dwellcall.errors import ApiError
from dwellcall.listings.service import ingestion_lock


def request_for(row: AgentCrmJob, link: AgentCrmLink) -> AgentExportRequest:
    return AgentExportRequest(row.id, link.destination, AgentContactSnapshot.model_validate(row.payload),
                              row.fingerprint, row.fields, link.contact_id, link.opportunity_id)


def finish(session: Session, settings: CrmSettings, row: AgentCrmJob, link: AgentCrmLink,
           state: AgentCrmDestination, result: AgentDeliveryResult) -> None:
    now = datetime.now(UTC)
    if result.contact_id:
        conflict = session.scalar(select(AgentCrmLink.id).where(
            AgentCrmLink.destination == link.destination, AgentCrmLink.contact_id == result.contact_id, AgentCrmLink.id != link.id,
        ).limit(1))
        if conflict:
            result = AgentDeliveryResult("unknown", "GHL_LOCAL_CONTACT_COLLISION")
        else:
            link.contact_id = result.contact_id
    if result.opportunity_id:
        link.opportunity_id = result.opportunity_id
    row.status = "unknown" if result.status == "disabled" else result.status
    row.code = result.code
    if result.code in {"GHL_REJECTED_401", "GHL_REJECTED_403"}:
        state.paused = True
    if result.retry_after_seconds or row.status == "retry_wait":
        delay = max(result.retry_after_seconds, min(3600, 30 * 2 ** min(row.attempts, 7)))
        row.next_attempt_at = now + timedelta(seconds=delay)
        if result.code == "GHL_RATE_LIMITED":
            state.next_attempt_at = max(state.next_attempt_at, row.next_attempt_at)
    if row.status == "retry_wait" and row.attempts >= settings.crm_max_attempts:
        row.status = "failed"
    if row.status == "sent":
        link.synced_fingerprint, link.synced_at = row.fingerprint, now
        row.payload = None
        state.capabilities = {**state.capabilities, "contacts.write": "observed",
                              **({"opportunities.write": "observed"} if result.opportunity_id else {})}
    agent_audit(session, link.destination, "GHL_EXPORT_" + row.status.upper(), row.id)


def recover(sessions: sessionmaker[Session], settings: CrmSettings) -> None:
    now = datetime.now(UTC)
    with sessions() as session, session.begin():
        ingestion_lock(session)
        rows = session.execute(select(AgentCrmJob, AgentCrmLink).join(AgentCrmLink, AgentCrmLink.id == AgentCrmJob.link_id).where(
            AgentCrmLink.destination == settings.destination,
            ((AgentCrmJob.status == "sending") & (AgentCrmJob.attempted_at < now - timedelta(seconds=120)))
            | ((AgentCrmJob.retain_until <= now) & AgentCrmJob.payload.is_not(None)),
        ).with_for_update(skip_locked=True).limit(50)).all()
        for row, link in rows:
            if row.status == "sending":
                row.status, row.code = "unknown", "GHL_WORKER_INTERRUPTED"
            if row.retain_until <= now:
                row.payload = None
                if row.status in {"pending", "retry_wait"}:
                    row.status, row.code = "cancelled", "GHL_PERMISSION_EXPIRED"
            agent_audit(session, link.destination, "GHL_RECOVERY_" + row.status.upper(), row.id)


def claim(sessions: sessionmaker[Session], settings: CrmSettings) -> tuple[UUID, UUID] | None:
    now = datetime.now(UTC)
    with sessions() as session, session.begin():
        ingestion_lock(session)
        state = destination_state(session, settings)
        if state.paused or state.next_attempt_at > now or not state.configured_at:
            return None
        row = session.scalar(select(AgentCrmJob).join(AgentCrmLink, AgentCrmLink.id == AgentCrmJob.link_id).where(
            AgentCrmLink.destination == settings.destination, AgentCrmJob.status.in_(("pending", "retry_wait")),
            AgentCrmJob.next_attempt_at <= now,
        ).order_by(AgentCrmJob.created_at, AgentCrmJob.id).with_for_update(skip_locked=True).limit(1))
        if row is None:
            return None
        if row.attempts >= settings.crm_max_attempts:
            row.status, row.code = "failed", "GHL_ATTEMPTS_EXHAUSTED"
            return None
        token = uuid4()
        row.status, row.attempt_id, row.attempted_at = "sending", token, now
        row.attempts += 1
        agent_audit(session, state.destination, "GHL_EXPORT_CLAIMED", row.id)
        return row.id, token


def dispatch_one(sessions: sessionmaker[Session], settings: CrmSettings, item: tuple[UUID, UUID], provider: AgentCrmProvider) -> AgentDeliveryResult:
    with sessions() as session, session.begin():
        ingestion_lock(session)
        state = destination_state(session, settings)
        row = session.get(AgentCrmJob, item[0], with_for_update=True)
        if row is None or row.attempt_id != item[1] or row.status != "sending":
            return AgentDeliveryResult("failed", "GHL_CLAIM_CHANGED")
        link = session.get(AgentCrmLink, row.link_id, with_for_update=True)
        if link is None or link.destination != settings.destination:
            row.status, row.code, row.payload = "cancelled", "GHL_DESTINATION_CHANGED", None
            return AgentDeliveryResult("failed", row.code)
        try:
            snapshot = export_snapshot(session, link.agent_id)
            if row.retain_until <= datetime.now(UTC) or snapshot_fingerprint(settings, snapshot, state.fields) != row.fingerprint:
                raise AgentIneligible("GHL_SNAPSHOT_CHANGED_OR_EXPIRED")
            request = request_for(row, link)
        except (AgentIneligible, ValidationError) as error:
            row.status, row.code, row.payload = "cancelled", str(error) if isinstance(error, AgentIneligible) else "GHL_PAYLOAD_INVALID", None
            agent_audit(session, link.destination, "GHL_EXPORT_CANCELLED", row.id)
            return AgentDeliveryResult("failed", row.code)
        if state.paused or state.next_attempt_at > datetime.now(UTC):
            row.status, row.next_attempt_at = "retry_wait", max(datetime.now(UTC), state.next_attempt_at)
            return AgentDeliveryResult("retry_wait", "GHL_DISPATCH_PAUSED")
        try:
            result = provider.send_agent(request)
        except Exception:
            result = AgentDeliveryResult("unknown", "GHL_WRITE_UNCERTAIN")
        finish(session, settings, row, link, state, result)
        return result


def process_agent_jobs(sessions: sessionmaker[Session], settings: CrmSettings,
                       provider: AgentCrmProvider | None = None, *, seconds: float = 20,
                       batch_size: int = 12) -> JobBatchResult:
    if settings.crm_provider != "gohighlevel" or not settings.dispatch_enabled:
        return JobBatchResult(status="disabled")
    if not 0 < seconds <= 20 or not 1 <= batch_size <= 50:
        raise ValueError("Invalid CRM job batch limits")
    batch = JobBatchResult()
    adapter = provider
    try:
        with job_budget(seconds), sessions() as guard, guard.begin():
            if not guard.scalar(text("SELECT pg_try_advisory_xact_lock(hashtextextended(:name, 0))"), {"name": JOB_LOCK_NAME}):
                return JobBatchResult(status="busy")
            recover(sessions, settings)
            if adapter is None:
                adapter = GoHighLevelProvider(settings, provider_client())
            for _ in range(batch_size):
                check_job_deadline()
                item = claim(sessions, settings)
                if item is None:
                    break
                try:
                    result = dispatch_one(sessions, settings, item, adapter)
                except ApiError as error:
                    if error.code != "INGESTION_BUSY":
                        raise
                    with sessions() as release, release.begin():
                        unsent = release.get(AgentCrmJob, item[0], with_for_update=True)
                        if unsent is not None and unsent.status == "sending" and unsent.attempt_id == item[1]:
                            unsent.status, unsent.code = "retry_wait", "GHL_LOCAL_BUSY"
                            unsent.attempts = max(0, unsent.attempts - 1)
                            unsent.next_attempt_at = datetime.now(UTC) + timedelta(seconds=1)
                            agent_audit(release, settings.destination, "GHL_UNSENT_CLAIM_RELEASED", unsent.id)
                    batch.status = "busy"
                    break
                batch.processed += 1
                if result.status in {"retry_wait", "unknown"} or result.code in {"GHL_REJECTED_401", "GHL_REJECTED_403"}:
                    break
    except JobDeadlineExceeded:
        batch.status = "deferred"
    except ApiError as error:
        if error.code != "INGESTION_BUSY":
            raise
        batch.status = "busy"
    finally:
        if provider is None and adapter is not None:
            adapter.close()
    return batch


def reconcile_job(sessions: sessionmaker[Session], settings: CrmSettings, job_id: UUID,
                  reference: str, provider: AgentCrmProvider | None = None) -> AgentJobStatus:
    if not settings.ghl_api_enabled or settings.crm_provider != "gohighlevel":
        raise ApiError(status_code=409, code="GHL_API_DISABLED", message="Enable owner-configured GHL API access first")
    with job_budget(20), sessions() as session, session.begin():
        ingestion_lock(session)
        state = destination_state(session, settings)
        row = session.get(AgentCrmJob, job_id, with_for_update=True)
        link = session.get(AgentCrmLink, row.link_id, with_for_update=True) if row else None
        if row is None or link is None or link.destination != settings.destination:
            raise ApiError(status_code=404, code="GHL_JOB_NOT_FOUND", message="Synchronization job not found")
        if row.status != "unknown":
            raise ApiError(status_code=409, code="GHL_NOT_UNCERTAIN", message="Only uncertain jobs may be reconciled")
        if row.payload is None or row.retain_until <= datetime.now(UTC):
            raise ApiError(status_code=409, code="GHL_EVIDENCE_EXPIRED", message="Expired evidence requires independent operator investigation; automatic creation remains blocked")
        if state.next_attempt_at > datetime.now(UTC):
            raise ApiError(status_code=429, code="GHL_BACKOFF_ACTIVE", message="Respect the persisted provider backoff")
        adapter = provider or GoHighLevelProvider(settings, provider_client())
        try:
            result = adapter.reconcile_agent(request_for(row, link))
        except Exception:
            result = AgentDeliveryResult("unknown", "GHL_RECONCILIATION_UNAVAILABLE")
        finally:
            if provider is None:
                adapter.close()
        finish(session, settings, row, link, state, result)
        agent_audit(session, settings.destination, "GHL_OPERATOR_RECONCILED", row.id, reference)
        return job_status(row, link)
