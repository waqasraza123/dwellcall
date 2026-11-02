import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from dwellcall.crm.schemas import ExportAuthorization, ExportStatus, ReconciliationInput
from dwellcall.crm.settings import CrmSettings
from dwellcall.database.models import AudioSession, CrmAuditEvent, CrmDispatchState, CrmExport
from dwellcall.errors import ApiError
from dwellcall.settings import ApiSettings


def export_status(row: CrmExport, *, replayed: bool = False) -> ExportStatus:
    return ExportStatus(
        id=row.id, status=row.status, code=row.last_code, attempts=row.attempts,
        created_at=row.created_at, next_attempt_at=row.next_attempt_at,
        permission_revoked_at=row.permission_revoked_at, replayed=replayed,
        permission_expires_at=row.retain_until,
    )


def audit(session: Session, row: CrmExport, event: str, reference: str | None = None) -> None:
    session.add(CrmAuditEvent(
        id=uuid4(), export_id=row.id, event_type=event,
        evidence_reference=reference, occurred_at=datetime.now(UTC),
    ))


class CrmService:
    def __init__(
        self, sessions: sessionmaker[Session], api: ApiSettings, settings: CrmSettings,
    ) -> None:
        self.sessions = sessions
        self.api = api
        self.settings = settings

    def authorize(self, data: ExportAuthorization) -> ExportStatus:
        if self.settings.crm_provider == "none":
            raise ApiError(status_code=404, code="CRM_DISABLED", message="CRM is disabled")
        if (
            data.destination != self.settings.destination
            or data.business_name != self.api.business_name
            or data.business_name != self.settings.business_name
        ):
            raise ApiError(status_code=409, code="CRM_DESTINATION_CHANGED", message="Review and authorize the configured CRM destination")
        canonical = json.dumps(data.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        fingerprint = self.settings.fingerprint("export", canonical)
        now = datetime.now(UTC)
        with self.sessions() as session, session.begin():
            call = session.get(AudioSession, data.call_id, with_for_update=True)
            if (
                call is None or call.status != "ended" or call.finalized_at is None
                or call.reserved_cost_cents <= 0 or call.agent_id != self.api.retell_agent_id
            ):
                raise ApiError(status_code=409, code="CONSULTATION_NOT_FINAL", message="An admitted, finalized consultation is required")
            scope = select(CrmExport).where(
                CrmExport.call_id == data.call_id,
                CrmExport.provider == self.settings.crm_provider,
            )
            rows = list(session.scalars(scope.with_for_update()).all())
            for existing in rows:
                if existing.snapshot_version == data.snapshot_version:
                    if existing.destination != data.destination:
                        raise ApiError(status_code=409, code="CRM_DESTINATION_BOUND", message="Use a newly confirmed version and permission for a changed destination")
                    if existing.request_fingerprint != fingerprint:
                        raise ApiError(status_code=409, code="IDEMPOTENCY_KEY_REUSED", message="This consultation version was authorized with different data")
                    return export_status(existing, replayed=True)
            if any(row.snapshot_version > data.snapshot_version for row in rows):
                raise ApiError(status_code=409, code="SNAPSHOT_SUPERSEDED", message="A newer confirmed snapshot exists")
            if any(row.status in {"sending", "unknown"} for row in rows):
                raise ApiError(status_code=409, code="CRM_OUTCOME_UNRESOLVED", message="Resolve the previous export before authorizing another revision")
            for previous in rows:
                if previous.status in {"pending", "retry_wait"}:
                    previous.status = "cancelled"
                    previous.last_code = "SNAPSHOT_SUPERSEDED"
                    previous.payload = None
                    previous.finalized_at = now
                    audit(session, previous, "CRM_SNAPSHOT_SUPERSEDED")
            row = CrmExport(
                id=uuid4(), call_id=data.call_id, snapshot_version=data.snapshot_version,
                provider=self.settings.crm_provider, destination=data.destination,
                request_fingerprint=fingerprint,
                payload=data.snapshot.model_dump(mode="json"),
                consent_version=data.consent_version,
                permission_reference=data.permission_reference, permission_at=now,
                retain_until=now + timedelta(days=self.settings.crm_retention_days),
                status="pending", attempts=0, created_at=now, next_attempt_at=now,
            )
            session.add(row)
            session.flush()
            audit(session, row, "CRM_EXPORT_AUTHORIZED", data.permission_reference)
            return export_status(row)

    @staticmethod
    def _owned(session: Session, export_id: UUID, *, lock: bool = False) -> CrmExport:
        row = session.get(CrmExport, export_id, with_for_update=lock)
        if row is None:
            raise ApiError(status_code=404, code="CRM_EXPORT_NOT_FOUND", message="The export could not be found")
        return row

    def get(self, export_id: UUID) -> ExportStatus:
        with self.sessions() as session:
            return export_status(self._owned(session, export_id))

    def revoke(self, export_id: UUID) -> ExportStatus:
        with self.sessions() as session, session.begin():
            row = self._owned(session, export_id, lock=True)
            if row.permission_revoked_at is None:
                row.permission_revoked_at = datetime.now(UTC)
                audit(session, row, "CRM_PERMISSION_REVOKED")
            row.payload = None
            if row.status in {"pending", "retry_wait"}:
                row.status = "cancelled"
                row.last_code = "CRM_PERMISSION_REVOKED"
                row.finalized_at = datetime.now(UTC)
                row.payload = None
            return export_status(row)

    def reconcile(self, export_id: UUID, data: ReconciliationInput) -> ExportStatus:
        with self.sessions() as session, session.begin():
            row = self._owned(session, export_id, lock=True)
            if row.status != "unknown":
                raise ApiError(status_code=409, code="CRM_NOT_UNCERTAIN", message="Only an uncertain export can be reconciled")
            row.status = "sent" if data.resolution == "delivered" else "failed"
            row.person_id = (
                data.person_id
                if data.resolution == "delivered"
                and row.retain_until > datetime.now(UTC)
                and row.permission_revoked_at is None
                else None
            )
            row.last_code = "CRM_OPERATOR_CONFIRMED" if data.resolution == "delivered" else "CRM_OPERATOR_CLOSED"
            row.payload = None
            row.finalized_at = datetime.now(UTC)
            audit(session, row, "CRM_OPERATOR_RECONCILED", data.evidence_reference)
            return export_status(row)

    def resume_dispatch(self, evidence_reference: str) -> dict[str, bool]:
        with self.sessions() as session, session.begin():
            state = session.get(CrmDispatchState, 1, with_for_update=True)
            if state is None:
                raise ApiError(status_code=503, code="CRM_SCHEMA_UNAVAILABLE", message="CRM dispatch schema is unavailable")
            if state.paused_destination == self.settings.destination:
                state.paused_destination = None
                session.add(CrmAuditEvent(
                    id=uuid4(), event_type="CRM_DISPATCH_RESUMED",
                    evidence_reference=evidence_reference, occurred_at=datetime.now(UTC),
                ))
            return {"resumed": True}
