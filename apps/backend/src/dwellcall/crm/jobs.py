import argparse
import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from secrets import randbelow
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from dwellcall.crm.contracts import CrmExportRequest, CrmProvider, DeliveryResult
from dwellcall.crm.job_execution import (
    JobDeadlineExceeded, check_job_deadline, create_job_engine, job_budget, provider_client,
)
from dwellcall.crm.providers.followupboss import FollowUpBossProvider
from dwellcall.crm.schemas import ConsultationSnapshot
from dwellcall.crm.service import audit
from dwellcall.crm.settings import CrmSettings
from dwellcall.database.models import AudioSession, CrmDispatchState, CrmExport
from dwellcall.settings import DatabaseConnectionSettings

JOB_LOCK_NAME = "dwellcall.crm-jobs"


@dataclass
class JobBatchResult:
    status: str = "completed"
    processed: int = 0


@dataclass(frozen=True)
class ClaimedExport:
    request: CrmExportRequest
    attempt_id: UUID


def recover_and_expire(sessions: sessionmaker[Session]) -> int:
    now = datetime.now(UTC)
    with sessions() as session, session.begin():
        rows = session.scalars(
            select(CrmExport).where(or_(
                (CrmExport.status == "sending")
                & (CrmExport.attempted_at < now - timedelta(seconds=120)),
                (CrmExport.retain_until <= now)
                & ((CrmExport.payload.is_not(None)) | CrmExport.person_id.is_not(None)),
            )).with_for_update(skip_locked=True).limit(50)
        ).all()
        for row in rows:
            if row.status == "sending":
                row.status = "unknown"
                row.last_code = "CRM_WORKER_INTERRUPTED"
                audit(session, row, "CRM_EXPORT_UNCERTAIN")
            if row.retain_until <= now:
                row.payload = None
                row.person_id = None
                if row.status in {"pending", "retry_wait"}:
                    row.status = "cancelled"
                    row.last_code = "CRM_PERMISSION_EXPIRED"
                    row.finalized_at = now
                audit(session, row, "CRM_PERSONAL_PAYLOAD_EXPIRED")
        return len(rows)


def claim(sessions: sessionmaker[Session], settings: CrmSettings) -> ClaimedExport | None:
    if not settings.dispatch_enabled:
        return None
    now = datetime.now(UTC)
    with sessions() as session, session.begin():
        throttle = session.get(CrmDispatchState, 1, with_for_update=True)
        if throttle is None:
            raise RuntimeError("CRM dispatch schema is unavailable")
        if (
            throttle.next_attempt_at > now
            or throttle.paused_destination == settings.destination
        ):
            return None
        row = session.scalar(
            select(CrmExport).where(
                CrmExport.status.in_(["pending", "retry_wait"]),
                CrmExport.next_attempt_at <= now,
            ).order_by(CrmExport.created_at, CrmExport.id)
            .with_for_update(skip_locked=True).limit(1)
        )
        if row is None:
            return None
        call = session.get(AudioSession, row.call_id)
        reason = None
        if row.destination != settings.destination:
            reason = "CRM_DESTINATION_CHANGED"
        elif row.permission_revoked_at is not None:
            reason = "CRM_PERMISSION_REVOKED"
        elif row.retain_until <= now or row.payload is None:
            reason = "CRM_PERMISSION_EXPIRED"
        elif row.consent_version != "dwellcall-crm-v1":
            reason = "CRM_PERMISSION_INVALID"
        elif call is None or call.status != "ended" or call.reserved_cost_cents <= 0:
            reason = "CONSULTATION_NOT_FINAL"
        elif row.attempts >= settings.crm_max_attempts:
            reason = "CRM_ATTEMPTS_EXHAUSTED"
        if reason:
            row.status = "cancelled"
            row.last_code = reason
            row.payload = None
            row.finalized_at = now
            audit(session, row, reason)
            return None
        try:
            snapshot = ConsultationSnapshot.model_validate(row.payload)
        except ValidationError:
            row.status = "failed"
            row.last_code = "CRM_PAYLOAD_INVALID"
            row.payload = None
            row.finalized_at = now
            audit(session, row, "CRM_PAYLOAD_INVALID")
            return None
        token = uuid4()
        row.status = "sending"
        row.attempt_id = token
        row.attempted_at = now
        row.attempts += 1
        audit(session, row, "CRM_EXPORT_DISPATCHED")
        return ClaimedExport(
            CrmExportRequest(row.id, row.destination, snapshot), token,
        )


def finish(
    sessions: sessionmaker[Session], settings: CrmSettings,
    item: ClaimedExport, result: DeliveryResult,
) -> None:
    now = datetime.now(UTC)
    with sessions() as session, session.begin():
        throttle = session.get(CrmDispatchState, 1, with_for_update=True)
        row = session.get(CrmExport, item.request.export_id, with_for_update=True)
        if row is None or row.attempt_id != item.attempt_id or row.status not in {"sending", "unknown"}:
            return
        status = "unknown" if result.status == "disabled" else result.status
        if result.code in {"CRM_REJECTED_401", "CRM_REJECTED_403"}:
            if throttle is None:
                raise RuntimeError("CRM dispatch schema is unavailable")
            throttle.paused_destination = row.destination
        if status == "retry_wait":
            delay = max(result.retry_after_seconds, min(3600, 60 * 2 ** (row.attempts - 1)))
            row.next_attempt_at = now + timedelta(seconds=delay + randbelow(1000) / 1000)
            if result.code == "CRM_RATE_LIMITED":
                if throttle is None:
                    raise RuntimeError("CRM dispatch schema is unavailable")
                throttle.next_attempt_at = max(throttle.next_attempt_at, row.next_attempt_at)
            if row.attempts >= settings.crm_max_attempts:
                status = "failed"
        row.status = status
        row.last_code = result.code
        row.person_id = (
            result.person_id
            if row.retain_until > now and row.permission_revoked_at is None
            else None
        )
        if status in {"sent", "failed", "ignored"}:
            row.payload = None
            row.finalized_at = now
        if row.permission_revoked_at is not None and status == "retry_wait":
            row.status = "cancelled"
            row.last_code = "CRM_PERMISSION_REVOKED"
            row.payload = None
            row.finalized_at = now
        audit(session, row, f"CRM_EXPORT_{row.status.upper()}")


def process_crm_jobs(
    sessions: sessionmaker[Session], settings: CrmSettings,
    provider: CrmProvider | None = None, *, seconds: float = 20, batch_size: int = 12,
) -> JobBatchResult:
    if not settings.dispatch_enabled:
        return JobBatchResult(status="disabled")
    if not 0 < seconds <= 20 or not 1 <= batch_size <= 50:
        raise ValueError("Invalid CRM job batch limits")
    result = JobBatchResult()
    try:
        with job_budget(seconds), sessions() as guard, guard.begin():
            acquired = guard.scalar(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(:name, 0))"),
                {"name": JOB_LOCK_NAME},
            )
            if not acquired:
                return JobBatchResult(status="busy")
            recover_and_expire(sessions)
            for _ in range(batch_size):
                check_job_deadline()
                item = claim(sessions, settings)
                if item is None:
                    continue
                try:
                    if provider is None:
                        adapter = FollowUpBossProvider(settings, provider_client())
                        try:
                            receipt = adapter.send(item.request)
                        finally:
                            adapter.close()
                    else:
                        receipt = provider.send(item.request)
                except Exception:
                    receipt = DeliveryResult("unknown", "CRM_OUTCOME_UNCERTAIN")
                finish(sessions, settings, item, receipt)
                result.processed += 1
                if receipt.status == "retry_wait" or receipt.code in {
                    "CRM_REJECTED_401", "CRM_REJECTED_403",
                }:
                    break
    except JobDeadlineExceeded:
        result.status = "deferred"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(prog="dwellcall-crm-jobs")
    parser.add_argument("--purge-only", action="store_true", help="Run bounded local retention/recovery without CRM HTTP")
    arguments = parser.parse_args()
    settings = CrmSettings()
    if not arguments.purge_only and not settings.dispatch_enabled:
        print(json.dumps(asdict(JobBatchResult(status="disabled"))))
        return
    engine = create_job_engine(DatabaseConnectionSettings())
    try:
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        if arguments.purge_only:
            print(json.dumps({"status": "maintenance_completed", "processed": recover_and_expire(sessions)}))
        else:
            print(json.dumps(asdict(process_crm_jobs(sessions, settings))))
    except (SQLAlchemyError, RuntimeError):
        logging.getLogger(__name__).error("CRM jobs unavailable; durable work retained")
        parser.exit(1, "CRM jobs unavailable; reservations were retained\n")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
