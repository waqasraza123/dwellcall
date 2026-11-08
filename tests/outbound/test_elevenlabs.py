import hashlib
import hmac
import json
import time

import httpx
import pytest
from pydantic import ValidationError

from dwellcall.settings import ApiSettings
from dwellcall.telephony.outbound.elevenlabs import ElevenLabsOutboundProvider
from dwellcall.telephony.outbound.provider import OutboundProviderError, create_outbound_provider
from tests.outbound.helpers import call_input


def configured(outbound_settings: ApiSettings) -> ApiSettings:
    return ApiSettings.model_validate({**outbound_settings.model_dump(), "outbound_provider": "elevenlabs", "retell_api_key": None,
        "retell_websocket_secret": None, "llm_api_key": None, "elevenlabs_api_key": "synthetic-elevenlabs-key",
        "outbound_phone_number_id": "phone_synthetic", "outbound_webhook_secret": "w" * 43})


def test_elevenlabs_does_not_require_retell_or_external_llm(outbound_settings):
    settings = configured(outbound_settings)
    assert isinstance(create_outbound_provider(settings), ElevenLabsOutboundProvider)
    assert not settings.retell_api_key and not settings.llm_api_key


@pytest.mark.parametrize("status", [302, 500, 502])
def test_uncertain_dial_is_never_retried(outbound_settings, status):
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(status, json={"success": False})
    with httpx.Client(base_url="https://api.elevenlabs.io", transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(OutboundProviderError) as caught:
            ElevenLabsOutboundProvider(configured(outbound_settings), client).dial(call_input(), "reservation", "proof")
    assert caught.value.outcome_unknown and len(seen) == 1


def test_dial_passes_authorization_and_purpose_without_transfer(outbound_settings):
    def handle(request):
        body = json.loads(request.content)
        variables = body["conversation_initiation_client_data"]["dynamic_variables"]
        assert variables["authorization"] == "proof" and variables["demo_transfer_enabled"] is False
        assert variables["call_purpose"] == "qualification"
        assert request.url.path == "/v1/convai/sip-trunk/outbound-call"
        return httpx.Response(200, json={"success": True, "conversation_id": "conv_synthetic", "sip_call_id": "sip_synthetic"})
    with httpx.Client(base_url="https://api.elevenlabs.io", transport=httpx.MockTransport(handle)) as client:
        result = ElevenLabsOutboundProvider(configured(outbound_settings), client).dial(call_input(call_purpose="qualification"), "reservation", "proof")
    assert result.call_status == "registered" and result.metadata["authorization"] == "proof"


def test_webhook_requires_original_bytes_fresh_signature_and_agent(outbound_settings):
    provider = ElevenLabsOutboundProvider(configured(outbound_settings))
    body = json.dumps({"type": "post_call_transcription", "data": {"agent_id": "agent_outbound"}}).encode()
    timestamp = str(int(time.time()))
    digest = hmac.new(("w" * 43).encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    headers = {"ElevenLabs-Signature": f"t={timestamp},v0={digest}"}
    assert provider.verify_webhook(headers, body)["type"] == "post_call_transcription"
    with pytest.raises(OutboundProviderError):
        provider.verify_webhook(headers, body + b" ")
    with pytest.raises(OutboundProviderError):
        provider.verify_webhook({"ElevenLabs-Signature": "t=0,v0=" + digest}, body)


def test_intelligence_requires_explicit_configuration(outbound_settings):
    with pytest.raises(ValidationError):
        ApiSettings.model_validate({**outbound_settings.model_dump(), "outbound_intelligence_enabled": True})
