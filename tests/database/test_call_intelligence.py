from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

from cryptography.fernet import Fernet
from sqlalchemy import select

from dwellcall.database.models import OutboundCall, OutboundSuppression
from dwellcall.database.models.call_intelligence import CallIntelligence
from dwellcall.settings import ApiSettings
from dwellcall.telephony.outbound.intelligence import LeadAssessment
from tests.database.test_outbound_calls import service, receipt
from tests.outbound.helpers import call_input


def configured(settings):
    return ApiSettings.model_validate({**settings.model_dump(), "outbound_intelligence_enabled": True,
        "outbound_transcript_encryption_key": Fernet.generate_key().decode(), "openai_api_key": "synthetic-openai-key",
        "outbound_analysis_model": "owner-selected-model", "outbound_qualification_criteria": "Explicit platform fit and interest"})


def assessment(**updates):
    return LeadAssessment.model_validate({"disposition": "follow_up", "summary": "Platform interest expressed.", "needs": ["Lead workflow"],
        "timing": None, "crm": None, "follow_up_permission": True, "permission_quote": "Please contact me about DwellCall.",
        "evidence_quotes": ["Please contact me about DwellCall."], "unanswered_questions": [], "next_step": "Review permission before contacting.", **updates})


def prepare(sessions, settings, **updates):
    calls, provider = service(sessions, configured(settings))
    result = calls.create(call_input(consent_version="dwellcall-ai-call-v2", call_purpose="qualification", **updates))
    calls.apply(receipt(sessions, result.id, call_status="ended", disconnection_reason="user_hangup"), "call_ended")
    return calls, result


def test_encrypted_transcript_duplicate_events_and_single_analysis(sessions, outbound_settings):
    calls, result = prepare(sessions, outbound_settings)
    turns = [{"role": "user", "message": "Please contact me about DwellCall."}]
    for _ in range(2):
        calls.intelligence.capture(result.id, turns)
    calls.intelligence._analyze = Mock(return_value=assessment())
    calls.intelligence.process(result.id)
    calls.intelligence.process(result.id)
    assert calls.intelligence._analyze.call_count == 1
    with sessions() as session:
        row = session.get(CallIntelligence, result.id)
        assert row.status == "complete" and row.disposition == "follow_up"
        assert "Please contact" not in row.transcript_ciphertext
        assert "Platform interest" not in row.analysis_ciphertext
    assert calls.intelligence.detail(result.id)["assessment"]["follow_up_permission"]


def test_fabricated_quotes_fail_and_suppression_overrides_qualification(sessions, outbound_settings):
    calls, result = prepare(sessions, outbound_settings)
    calls.intelligence.capture(result.id, [{"role": "user", "message": "Please contact me about DwellCall."}])
    calls.intelligence._analyze = Mock(return_value=assessment(permission_quote="Fabricated permission"))
    calls.intelligence.process(result.id)
    assert calls.intelligence.detail(result.id)["status"] == "failed"
    with sessions() as session, session.begin():
        row = session.get(CallIntelligence, result.id)
        row.attempted_at = datetime.now(UTC) - timedelta(minutes=3)
        call = session.get(OutboundCall, result.id)
        session.add(OutboundSuppression(destination_hash=call.destination_hash, created_at=datetime.now(UTC)))
    calls.intelligence._analyze = Mock(return_value=assessment())
    calls.intelligence.process(result.id, retry=True)
    assert calls.intelligence.detail(result.id)["assessment"]["disposition"] == "do_not_contact"


def test_demo_never_becomes_real_lead_and_expired_content_is_purged(sessions, outbound_settings):
    calls, result = prepare(sessions, outbound_settings)
    with sessions() as session, session.begin():
        session.get(OutboundCall, result.id).call_purpose = "demonstration"
    calls.intelligence.capture(result.id, [{"role": "user", "message": "Please contact me about DwellCall."}])
    calls.intelligence._analyze = Mock(return_value=assessment())
    calls.intelligence.process(result.id)
    assert calls.intelligence.detail(result.id)["assessment"]["disposition"] == "demonstration"
    with sessions() as session, session.begin():
        session.get(CallIntelligence, result.id).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert calls.intelligence.detail(result.id)["transcript"] == []
    assert calls.intelligence.purge() == 1
    with sessions() as session:
        row = session.scalar(select(CallIntelligence))
        assert row.transcript_ciphertext is None and row.analysis_ciphertext is None
