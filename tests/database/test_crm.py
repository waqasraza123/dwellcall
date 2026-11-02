import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from dwellcall.crm.contracts import DeliveryResult
from dwellcall.crm.jobs import claim, process_crm_jobs, recover_and_expire
from dwellcall.crm.schemas import ExportAuthorization, ReconciliationInput
from dwellcall.crm.service import CrmService
from dwellcall.crm.settings import CrmSettings
from dwellcall.database.models import AudioSession, CrmExport
from dwellcall.errors import ApiError
from dwellcall.settings import ApiSettings


def finalized_call(sessions: sessionmaker[Session], call_id: str = "call_crm_mock") -> None:
    now = datetime.now(UTC)
    with sessions() as session, session.begin():
        session.add(AudioSession(
            call_id=call_id, agent_id="agent_dwellcall_test", status="ended",
            created_at=now, finalized_at=now, reserved_cost_cents=100,
        ))


def test_concurrent_duplicate_confirmation_enqueues_once(
    sessions: sessionmaker[Session], settings: ApiSettings,
    crm_settings: CrmSettings, authorization: ExportAuthorization,
) -> None:
    finalized_call(sessions)
    service = CrmService(sessions, settings, crm_settings)
    barrier = threading.Barrier(2)
    def submit(index: int):
        barrier.wait(timeout=5)
        return service.authorize(authorization)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    assert results[0].id == results[1].id
    assert sorted(item.replayed for item in results) == [False, True]
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(CrmExport)) == 1
    changed = authorization.model_copy(update={"permission_reference": "different-reference"})
    with pytest.raises(ApiError):
        service.authorize(changed)


def test_only_finalized_admitted_consultation_can_be_authorized(
    sessions: sessionmaker[Session], settings: ApiSettings,
    crm_settings: CrmSettings, authorization: ExportAuthorization,
) -> None:
    finalized_call(sessions)
    with sessions() as session, session.begin():
        session.get(AudioSession, authorization.call_id).status = "unknown"
    with pytest.raises(ApiError):
        CrmService(sessions, settings, crm_settings).authorize(authorization)


def test_success_is_durable_and_never_sent_twice(
    sessions: sessionmaker[Session], settings: ApiSettings,
    crm_settings: CrmSettings, authorization: ExportAuthorization,
) -> None:
    finalized_call(sessions)
    service = CrmService(sessions, settings, crm_settings)
    authorized = service.authorize(authorization)
    provider = Mock()
    provider.send.return_value = DeliveryResult("sent", "CRM_DELIVERED", person_id=101)
    process_crm_jobs(sessions, crm_settings, provider)
    process_crm_jobs(sessions, crm_settings, provider)
    provider.send.assert_called_once()
    assert service.get(authorized.id).status == "sent"
    with sessions() as session:
        assert session.get(CrmExport, authorized.id).payload is None


def test_global_rate_delay_survives_the_next_worker_batch(
    sessions: sessionmaker[Session], settings: ApiSettings,
    crm_settings: CrmSettings, authorization: ExportAuthorization,
) -> None:
    finalized_call(sessions)
    finalized_call(sessions, "call_other")
    service = CrmService(sessions, settings, crm_settings)
    first = service.authorize(authorization)
    second = service.authorize(authorization.model_copy(update={"call_id": "call_other"}))
    provider = Mock()
    provider.send.return_value = DeliveryResult("retry_wait", "CRM_RATE_LIMITED", retry_after_seconds=120)
    process_crm_jobs(sessions, crm_settings, provider)
    process_crm_jobs(sessions, crm_settings, provider)
    provider.send.assert_called_once()
    assert service.get(first.id).status == "retry_wait"
    assert service.get(second.id).status == "pending"
    assert service.get(first.id).next_attempt_at >= datetime.now(UTC) + timedelta(seconds=115)


def test_stale_sending_is_unknown_and_requires_audited_reconciliation(
    sessions: sessionmaker[Session], settings: ApiSettings,
    crm_settings: CrmSettings, authorization: ExportAuthorization,
) -> None:
    finalized_call(sessions)
    service = CrmService(sessions, settings, crm_settings)
    authorized = service.authorize(authorization)
    assert claim(sessions, crm_settings) is not None
    with sessions() as session, session.begin():
        session.get(CrmExport, authorized.id).attempted_at = datetime.now(UTC) - timedelta(seconds=121)
    provider = Mock(side_effect=AssertionError("Unknown job was resent"))
    process_crm_jobs(sessions, crm_settings, provider)
    provider.send.assert_not_called()
    assert service.get(authorized.id).status == "unknown"
    service.reconcile(authorized.id, ReconciliationInput(
        resolution="delivered", person_id=101, evidence_reference="mock-fub-history-reference",
    ))
    process_crm_jobs(sessions, crm_settings, provider)
    provider.send.assert_not_called()
    assert service.get(authorized.id).status == "sent"


def test_revocation_or_destination_rotation_prevents_dispatch(
    sessions: sessionmaker[Session], settings: ApiSettings,
    crm_settings: CrmSettings, authorization: ExportAuthorization,
) -> None:
    finalized_call(sessions)
    service = CrmService(sessions, settings, crm_settings)
    first = service.authorize(authorization)
    service.revoke(first.id)
    provider = Mock()
    process_crm_jobs(sessions, crm_settings, provider)
    provider.send.assert_not_called()
    assert service.get(first.id).status == "cancelled"
    second = service.authorize(authorization.model_copy(update={"snapshot_version": 2}))
    rotated = crm_settings.model_copy(update={"followupboss_lead_source": "Changed Demo Source"})
    process_crm_jobs(sessions, rotated, provider)
    provider.send.assert_not_called()
    assert service.get(second.id).code == "CRM_DESTINATION_CHANGED"


def test_expired_payload_can_be_purged_without_any_provider(
    sessions: sessionmaker[Session], settings: ApiSettings,
    crm_settings: CrmSettings, authorization: ExportAuthorization,
) -> None:
    finalized_call(sessions)
    service = CrmService(sessions, settings, crm_settings)
    authorized = service.authorize(authorization)
    with sessions() as session, session.begin():
        session.get(CrmExport, authorized.id).retain_until = datetime.now(UTC) - timedelta(seconds=1)
    assert recover_and_expire(sessions) == 1
    assert service.get(authorized.id).status == "cancelled"
    with sessions() as session:
        assert session.get(CrmExport, authorized.id).payload is None


def test_two_workers_make_only_one_provider_submission(
    sessions: sessionmaker[Session], settings: ApiSettings,
    crm_settings: CrmSettings, authorization: ExportAuthorization,
) -> None:
    finalized_call(sessions)
    service = CrmService(sessions, settings, crm_settings)
    authorized = service.authorize(authorization)
    barrier = threading.Barrier(2)
    provider = Mock()
    provider.send.return_value = DeliveryResult("sent", "CRM_DELIVERED", person_id=101)
    def run(index: int):
        barrier.wait(timeout=5)
        return process_crm_jobs(sessions, crm_settings, provider)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, range(2)))
    provider.send.assert_called_once()
    assert service.get(authorized.id).status == "sent"


def test_unknown_result_cannot_be_bypassed_with_retry_or_changed_credentials(
    sessions: sessionmaker[Session], settings: ApiSettings,
    crm_settings: CrmSettings, authorization: ExportAuthorization,
) -> None:
    finalized_call(sessions)
    service = CrmService(sessions, settings, crm_settings)
    authorized = service.authorize(authorization)
    provider = Mock()
    provider.send.return_value = DeliveryResult("unknown", "CRM_OUTCOME_UNCERTAIN")
    process_crm_jobs(sessions, crm_settings, provider)
    assert service.authorize(authorization).status == "unknown"
    rotated = crm_settings.model_copy(update={"followupboss_lead_source": "Other Demo Source"})
    changed = authorization.model_copy(update={"snapshot_version": 2, "destination": rotated.destination})
    with pytest.raises(ApiError):
        CrmService(sessions, settings, rotated).authorize(changed)
    process_crm_jobs(sessions, crm_settings, provider)
    provider.send.assert_called_once()
    assert service.get(authorized.id).status == "unknown"


def test_credential_rejection_pauses_other_exports_until_operator_resume(
    sessions: sessionmaker[Session], settings: ApiSettings,
    crm_settings: CrmSettings, authorization: ExportAuthorization,
) -> None:
    finalized_call(sessions)
    finalized_call(sessions, "call_other")
    service = CrmService(sessions, settings, crm_settings)
    first = service.authorize(authorization)
    second = service.authorize(authorization.model_copy(update={"call_id": "call_other"}))
    provider = Mock()
    provider.send.return_value = DeliveryResult("failed", "CRM_REJECTED_401")
    process_crm_jobs(sessions, crm_settings, provider)
    process_crm_jobs(sessions, crm_settings, provider)
    provider.send.assert_called_once()
    assert service.get(first.id).status == "failed"
    assert service.get(second.id).status == "pending"
    service.resume_dispatch("mock-credential-validation-reference")
    provider.send.return_value = DeliveryResult("sent", "CRM_DELIVERED", person_id=101)
    process_crm_jobs(sessions, crm_settings, provider)
    assert provider.send.call_count == 2
    assert service.get(second.id).status == "sent"


def test_invalid_stored_payload_is_redacted_and_never_sent(
    sessions: sessionmaker[Session], settings: ApiSettings,
    crm_settings: CrmSettings, authorization: ExportAuthorization,
) -> None:
    finalized_call(sessions)
    service = CrmService(sessions, settings, crm_settings)
    authorized = service.authorize(authorization)
    with sessions() as session, session.begin():
        session.get(CrmExport, authorized.id).payload = {"sensitive": "synthetic-private-value"}
    provider = Mock()
    process_crm_jobs(sessions, crm_settings, provider)
    provider.send.assert_not_called()
    result = service.get(authorized.id)
    assert result.status == "failed" and result.code == "CRM_PAYLOAD_INVALID"
    assert "synthetic-private-value" not in result.model_dump_json()
