from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from dwellcall.database.models import AudioSession, OutboundCall, OutboundCallEvent
from dwellcall.errors import ApiError
from dwellcall.settings import ApiSettings
from dwellcall.telephony.outbound.provider import OutboundProviderError, RetellOutboundProvider
from dwellcall.telephony.outbound.schemas import ControlsInput
from dwellcall.telephony.outbound.service import OutboundCallService
from dwellcall.telephony.retell.service import AudioSessionService
from tests.outbound.helpers import call_input, phone_call
from tests.outbound.test_api import application


def service(sessions: sessionmaker[Session], settings: ApiSettings) -> tuple[OutboundCallService, Mock]:
    provider = Mock(spec=RetellOutboundProvider)
    provider.dial.side_effect = lambda data, call_id, proof: phone_call(call_id, proof, to_number=data.phone_number)
    return OutboundCallService(sessions, settings, provider), provider


def receipt(sessions: sessionmaker[Session], call_id, **updates):
    with sessions() as session:
        row = session.get(OutboundCall, call_id)
        return phone_call(str(row.id), row.request_hash, **updates)


def test_persisted_reservation_precedes_http_and_duplicate_requests_never_redial(sessions, outbound_settings):
    calls, provider = service(sessions, outbound_settings)
    data = call_input()
    def dial(data, call_id, proof):
        with sessions() as session:
            row = session.get(OutboundCall, UUID(call_id))
            assert row and row.send_started_at and session.get(AudioSession, row.audio_session_id)
        return phone_call(call_id, proof)
    provider.dial.side_effect = dial
    first = calls.create(data)
    assert first.status == "dialing" and first.started_at is None and not first.terminal
    assert calls.create(data) == first
    assert provider.dial.call_count == 1
    assert calls.get_request(data.request_id).id == first.id
    with pytest.raises(ApiError):
        calls.create(call_input(request_id=str(data.request_id), scenario="buying"))


def test_concurrent_workers_share_the_global_web_and_phone_slot(sessions, outbound_settings):
    calls, provider = service(sessions, outbound_settings)
    barrier = Barrier(2)
    def attempt(index):
        barrier.wait(timeout=5)
        try:
            if index:
                calls.create(call_input())
            else:
                AudioSessionService(sessions, outbound_settings).reserve("call_browser", "agent_dwellcall_test")
            return "admitted"
        except ApiError:
            return "blocked"
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(attempt, range(2))) == ["admitted", "blocked"]
    assert provider.dial.call_count <= 1


def test_concurrent_identical_keys_dial_exactly_once(sessions, outbound_settings):
    calls, provider = service(sessions, outbound_settings)
    data = call_input()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: calls.create(data), range(2)))
    assert results[0].id == results[1].id and provider.dial.call_count == 1


def test_unknown_timeout_retains_budget_and_slot_and_empty_lookup_never_redials(sessions, outbound_settings):
    calls, provider = service(sessions, outbound_settings)
    provider.dial.side_effect = OutboundProviderError("RETELL_DIAL_UNCERTAIN", "Timeout", outcome_unknown=True)
    data = call_input()
    result = calls.create(data)
    assert result.status == "unknown" and not result.terminal
    provider.find.return_value = None
    assert calls.refresh(result.id).status == "unknown"
    assert calls.create(data).id == result.id
    with pytest.raises(ApiError):
        calls.create(call_input(phone_number="+12025550126"))
    with sessions() as session:
        row = session.get(OutboundCall, result.id)
        audio = session.get(AudioSession, row.audio_session_id)
        assert audio.status == "unknown" and audio.reserved_cost_cents == 100
    assert provider.dial.call_count == 1


def test_webhooks_bind_late_receipts_deduplicate_and_never_resurrect_final_calls(sessions, outbound_settings):
    calls, provider = service(sessions, outbound_settings)
    provider.dial.side_effect = OutboundProviderError("RETELL_DIAL_UNCERTAIN", "Timeout", outcome_unknown=True)
    result = calls.create(call_input())
    final = receipt(sessions, result.id, call_status="ended", disconnection_reason="user_hangup", duration_ms=10000)
    digest = calls.event_digest(b"signed-final-event")
    calls.apply(final, "call_ended", digest)
    calls.apply(final, "call_ended", digest)
    calls.apply(receipt(sessions, result.id, call_status="ongoing"), "call_started", calls.event_digest(b"late-start"))
    assert calls.get(result.id).status == "completed" and calls.get(result.id).terminal
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(OutboundCallEvent).where(OutboundCallEvent.fingerprint == digest)) == 1
        row = session.get(OutboundCall, result.id)
        assert row.provider_call_id == final.call_id
        assert session.get(AudioSession, row.audio_session_id).status == "ended"


@pytest.mark.parametrize(("reason", "expected"), [("dial_busy", "rejected"), ("user_declined", "rejected"), ("dial_no_answer", "unanswered"), ("voicemail_reached", "unanswered"), ("telephony_provider_permission_denied", "failed"), ("max_duration_reached", "completed")])
def test_final_outcomes_require_provider_evidence(sessions, outbound_settings, reason, expected):
    calls, _ = service(sessions, outbound_settings)
    result = calls.create(call_input())
    calls.apply(receipt(sessions, result.id, call_status="ended", disconnection_reason=reason), "call_ended")
    assert calls.get(result.id).status == expected and calls.get(result.id).terminal


@pytest.mark.parametrize("changes", [{"agent_id": "other"}, {"agent_version": 4}, {"to_number": "+12025550126"}, {"direction": "inbound"}, {"from_number": "+12025550126"}, {"metadata": {}}, {"call_id": "another_provider_call"}])
def test_call_identity_must_match_the_committed_authorization(sessions, outbound_settings, changes):
    calls, _ = service(sessions, outbound_settings)
    result = calls.create(call_input())
    with pytest.raises(ApiError):
        calls.apply(receipt(sessions, result.id, **changes), "call_ended")
    assert not calls.get(result.id).terminal


def test_phone_socket_attaches_once_without_another_spending_reservation(sessions, outbound_settings):
    calls, _ = service(sessions, outbound_settings)
    result = calls.create(call_input())
    provider_call = receipt(sessions, result.id)
    audio_id, scenario = calls.admit_phone(provider_call)
    assert scenario == "renting" and calls.active(audio_id)
    with pytest.raises(ApiError):
        calls.admit_phone(provider_call)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(AudioSession)) == 1
    calls.disconnect(audio_id)
    assert calls.get(result.id).status == "unknown" and not calls.get(result.id).terminal
    with pytest.raises(ApiError):
        calls.admit_phone(provider_call)


def test_suppression_and_emergency_pause_block_before_dial(sessions, outbound_settings):
    calls, provider = service(sessions, outbound_settings)
    calls.suppress("+12025550124")
    with pytest.raises(ApiError) as caught:
        calls.create(call_input())
    assert caught.value.code == "OUTBOUND_RECIPIENT_SUPPRESSED"
    calls.controls(ControlsInput(calls_paused=True, transfers_paused=True))
    with pytest.raises(ApiError):
        calls.create(call_input(phone_number="+12025550126"))
    provider.dial.assert_not_called()


def test_provider_dnc_evidence_persists_local_suppression(sessions, outbound_settings):
    calls, _ = service(sessions, outbound_settings)
    result = calls.create(call_input())
    calls.apply(receipt(sessions, result.id, call_status="ended", disconnection_reason="user_requested_dnc"), "call_ended")
    with pytest.raises(ApiError) as caught:
        calls.create(call_input())
    assert caught.value.code == "OUTBOUND_RECIPIENT_SUPPRESSED"


def test_spending_and_recipient_quotas_are_not_refunded(sessions, outbound_settings):
    configured = outbound_settings.model_copy(update={"outbound_daily_budget_cents": 100})
    calls, _ = service(sessions, configured)
    result = calls.create(call_input())
    calls.apply(receipt(sessions, result.id, call_status="ended", disconnection_reason="agent_hangup"), "call_ended")
    with sessions() as session, session.begin():
        row = session.get(OutboundCall, result.id)
        row.created_at -= timedelta(minutes=6)
    with pytest.raises(ApiError):
        calls.create(call_input())
    with pytest.raises(ApiError) as caught:
        calls.create(call_input(phone_number="+12025550126"))
    assert caught.value.code == "AUDIO_SESSION_LIMIT"


def test_transfer_acceptance_never_releases_a_carrier_leg_or_claims_human_answer(sessions, outbound_settings):
    configured = outbound_settings.model_copy(update={"outbound_human_number": "+12025550125"})
    calls, _ = service(sessions, configured)
    result = calls.create(call_input())
    provider_call = receipt(sessions, result.id, call_status="ongoing", start_timestamp=int(datetime.now(UTC).timestamp() * 1000))
    audio_id, _ = calls.admit_phone(provider_call)
    with pytest.raises(ApiError):
        calls.reserve_transfer(audio_id, "confirmation-digest")
    final = provider_call.model_copy(update={"call_status": "ended", "disconnection_reason": "call_transfer", "transfer_destination": "+12025550125"})
    calls.apply(final, "call_ended")
    assert calls.get(result.id).status == "transferred" and not calls.get(result.id).terminal
    with sessions() as session, session.begin():
        row = session.get(OutboundCall, result.id)
        row.send_started_at -= timedelta(minutes=2)
    assert calls.carrier_ended(result.id).terminal
    calls.apply(final, "call_analyzed")
    assert calls.get(result.id).terminal


def test_uncertain_or_failed_transfer_is_reported_without_an_automatic_retry(sessions, outbound_settings):
    calls, _ = service(sessions, outbound_settings)
    result = calls.create(call_input())
    with sessions() as session, session.begin():
        row = session.get(OutboundCall, result.id)
        row.transfer_status = "requested"
    calls.apply(receipt(sessions, result.id, call_status="ended", disconnection_reason="user_hangup"), "call_ended")
    assert calls.get(result.id).status == "transfer_unconfirmed" and not calls.get(result.id).terminal
    calls.apply(receipt(sessions, result.id, call_status="ended", disconnection_reason="transfer_cancelled"), "call_analyzed")
    assert calls.get(result.id).transfer_status == "failed" and calls.get(result.id).terminal


def test_mock_mode_recovers_after_a_backend_restart_without_provider_requests(sessions, outbound_settings):
    configured = ApiSettings.model_validate({**outbound_settings.model_dump(), "outbound_enabled": False, "outbound_mock_enabled": True})
    calls, provider = service(sessions, configured)
    result = calls.create(call_input())
    assert result.mock and result.status == "dialing"
    assert calls.refresh(result.id).mock
    with sessions() as session, session.begin():
        row = session.get(OutboundCall, result.id)
        row.created_at -= timedelta(seconds=20)
    restarted = OutboundCallService(sessions, configured, provider)
    recovered = restarted.get_request(result.request_id)
    assert recovered.mock and recovered.terminal and recovered.duration_seconds == 13
    provider.preflight.assert_not_called()
    provider.dial.assert_not_called()
    provider.retrieve.assert_not_called()


def test_cooldown_and_utc_day_quotas_are_independent_of_finalization(sessions, outbound_settings):
    calls, provider = service(sessions, outbound_settings)
    first = calls.create(call_input())
    calls.apply(receipt(sessions, first.id, call_status="ended", disconnection_reason="agent_hangup"), "call_ended")
    with pytest.raises(ApiError) as caught:
        calls.create(call_input(phone_number="+12025550126"))
    assert caught.value.code == "OUTBOUND_CALL_LIMIT"
    with sessions() as session, session.begin():
        row = session.get(OutboundCall, first.id)
        yesterday = datetime.now(UTC) - timedelta(days=1, minutes=6)
        row.created_at = yesterday
        session.get(AudioSession, row.audio_session_id).created_at = yesterday
    second = calls.create(call_input())
    assert second.id != first.id and provider.dial.call_count == 2


def test_overdue_reservation_never_expires_into_a_new_dial(sessions, outbound_settings):
    calls, provider = service(sessions, outbound_settings)
    data = call_input()
    call_id, _ = calls._reserve(data)
    with sessions() as session, session.begin():
        session.get(OutboundCall, call_id).created_at -= timedelta(minutes=2)
    assert calls.get(call_id).status == "unknown"
    assert calls.create(data).status == "unknown"
    provider.dial.assert_not_called()


def test_transfer_emergency_pause_is_checked_at_confirmation_time(sessions, outbound_settings):
    calls, _ = service(sessions, outbound_settings)
    result = calls.create(call_input())
    audio_id, _ = calls.admit_phone(receipt(sessions, result.id, call_status="ongoing"))
    calls.controls(ControlsInput(calls_paused=False, transfers_paused=True))
    with pytest.raises(ApiError) as caught:
        calls.reserve_transfer(audio_id, "confirmation")
    assert caught.value.code == "OUTBOUND_TRANSFER_DISABLED"


def test_operator_can_cancel_during_preflight_without_a_provider_send(sessions, outbound_settings):
    calls, provider = service(sessions, outbound_settings)
    def preflight(number):
        with sessions() as session:
            call_id = session.scalar(select(OutboundCall.id))
        assert calls.stop(call_id).terminal
    provider.preflight.side_effect = preflight
    result = calls.create(call_input())
    assert result.terminal and result.status == "failed"
    provider.dial.assert_not_called()
    provider.stop.assert_not_called()


def test_stop_is_durable_and_late_start_cannot_admit_a_socket(sessions, outbound_settings):
    calls, provider = service(sessions, outbound_settings)
    result = calls.create(call_input())
    ongoing = receipt(sessions, result.id, call_status="ongoing")
    provider.retrieve.return_value = ongoing
    stopped = calls.stop(result.id)
    assert stopped.status == "unknown" and not stopped.terminal
    provider.stop.assert_called_once_with(ongoing.call_id)
    restarted = OutboundCallService(sessions, outbound_settings, provider)
    restarted.apply(ongoing, "call_started")
    with pytest.raises(ApiError, match="already admitted"):
        restarted.admit_phone(ongoing)
    with sessions() as session:
        row = session.get(OutboundCall, result.id)
        assert not restarted.active(row.audio_session_id)
    assert restarted.get(result.id).status == "unknown"
    assert provider.dial.call_count == 1


def test_stop_looks_up_a_missing_receipt_without_dialing_again(sessions, outbound_settings):
    calls, provider = service(sessions, outbound_settings)
    provider.dial.side_effect = OutboundProviderError("RETELL_DIAL_UNCERTAIN", "Timeout", outcome_unknown=True)
    result = calls.create(call_input())
    existing = receipt(sessions, result.id, call_status="ongoing")
    provider.find.return_value = existing
    provider.retrieve.return_value = existing.model_copy(update={"call_status": "ended", "disconnection_reason": "manual_stopped"})
    assert calls.stop(result.id).terminal
    provider.stop.assert_called_once_with(existing.call_id)
    assert provider.dial.call_count == 1


def test_rejected_stop_retains_reservation_until_final_evidence(sessions, outbound_settings):
    calls, provider = service(sessions, outbound_settings)
    result = calls.create(call_input())
    provider.stop.side_effect = OutboundProviderError("RETELL_STOP_UNCERTAIN", "Unknown", outcome_unknown=True)
    with pytest.raises(ApiError):
        calls.stop(result.id)
    assert not calls.get(result.id).terminal
    with pytest.raises(ApiError):
        calls.create(call_input(phone_number="+12025550126"))
    calls.apply(receipt(sessions, result.id, call_status="ended", disconnection_reason="manual_stopped"), "call_ended")
    assert calls.get(result.id).terminal


def test_mismatched_creation_receipt_holds_the_slot_without_redial(sessions, outbound_settings):
    calls, provider = service(sessions, outbound_settings)
    provider.dial.side_effect = lambda data, call_id, proof: phone_call(call_id, proof, agent_version=4)
    data = call_input()
    result = calls.create(data)
    assert result.status == "unknown" and not result.terminal and result.provider_call_id is None
    assert calls.create(data).id == result.id
    with pytest.raises(ApiError):
        calls.create(call_input(phone_number="+12025550126"))
    assert provider.dial.call_count == 1


def test_final_timestamps_supply_duration_without_rewriting_the_connection_time(sessions, outbound_settings):
    calls, _ = service(sessions, outbound_settings)
    result = calls.create(call_input())
    start = int(datetime.now(UTC).timestamp() * 1000)
    calls.apply(receipt(sessions, result.id, call_status="ongoing", start_timestamp=start), "call_started")
    calls.apply(receipt(sessions, result.id, call_status="ended", start_timestamp=start, end_timestamp=start + 12000, disconnection_reason="user_hangup"), "call_ended")
    calls.apply(receipt(sessions, result.id, call_status="ongoing", start_timestamp=start + 1000), "late_start")
    final = calls.get(result.id)
    assert final.terminal and final.duration_seconds == 12
    assert final.started_at == datetime.fromtimestamp(start / 1000, UTC)


@pytest.mark.parametrize("scenario", ["renting", "buying", "luxury"])
@pytest.mark.parametrize("finish", ["stop", "complete"])
def test_mock_api_start_duplicate_recovery_history_and_end_need_no_external_services(sessions, outbound_settings, scenario, finish):
    configured = ApiSettings.model_validate({**outbound_settings.model_dump(), "outbound_enabled": False, "outbound_mock_enabled": True})
    calls, provider = service(sessions, configured)
    data = call_input(scenario=scenario)
    headers = {"X-Admin-Token": "b" * 43, "Idempotency-Key": str(data.request_id)}
    with TestClient(application(configured, calls)) as client:
        assert client.post("/api/v1/outbound/preflight", headers=headers).json() == {"ready": True, "mock": True}
        response = client.post("/api/v1/outbound/calls", headers=headers, json=data.model_dump(mode="json"))
        assert response.status_code == 200
        created = response.json()
        duplicate = client.post("/api/v1/outbound/calls", headers=headers, json=data.model_dump(mode="json"))
        assert duplicate.json()["id"] == created["id"]
        assert created["mock"] and created["scenario"] == scenario
        assert client.get(f"/api/v1/outbound/requests/{data.request_id}", headers=headers).json()["id"] == created["id"]
        assert client.get("/api/v1/outbound/calls", headers=headers).json()[0]["id"] == created["id"]
        if finish == "stop":
            final = client.post(f"/api/v1/outbound/calls/{created['id']}/stop", headers=headers).json()
        else:
            with sessions() as session, session.begin():
                session.get(OutboundCall, UUID(created["id"])).created_at -= timedelta(seconds=20)
            final = client.get(f"/api/v1/outbound/requests/{data.request_id}", headers=headers).json()
            assert final["duration_seconds"] == 13
        assert final["terminal"] and final["mock"]
    assert provider.mock_calls == []
