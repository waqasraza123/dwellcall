import json

import httpx
import pytest

from dwellcall.settings import ApiSettings
from dwellcall.telephony.outbound.provider import OutboundProviderError, RetellOutboundProvider
from tests.outbound.helpers import call_input, phone_call


def agent(settings: ApiSettings) -> dict[str, object]:
    return {
        "agent_id": "agent_outbound", "version": 3, "is_published": True,
        "response_engine": {"type": "custom-llm", "llm_websocket_url": "wss://api.dwellcall.test/api/v1/retell/llm/" + "a" * 43},
        "max_call_duration_ms": 180000, "ring_duration_ms": 25000,
        "data_storage_setting": "basic_attributes_only", "data_storage_retention_days": 7,
        "enable_dnc_detection": True, "contact_memory_config": {"enable_update": False, "enable_read": False},
        "webhook_url": "https://api.dwellcall.test/api/v1/retell/webhook",
        "webhook_events": ["call_started", "call_ended", "call_analyzed"],
    }


def phone() -> dict[str, object]:
    return {
        "phone_number": "+12025550123", "phone_number_type": "custom", "allowed_outbound_country_list": ["US"],
        "sip_outbound_trunk_config": {"termination_uri": "sip.telnyx.com", "transport": "TCP", "auth_username": "synthetic-sip-user"},
    }


def test_preflight_is_read_only_and_requires_imported_identity(outbound_settings: ApiSettings) -> None:
    seen = []
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=agent(outbound_settings) if request.url.path.startswith("/get-agent/") else phone())
    with httpx.Client(base_url="https://api.retellai.com", transport=httpx.MockTransport(handle)) as client:
        RetellOutboundProvider(outbound_settings, client).preflight("+12025550124")
    assert len(seen) == 2 and all(request.method == "GET" for request in seen)
    assert seen[1].url.params["version"] == "3"


@pytest.mark.parametrize("change", [{"data_storage_setting": "everything"}, {"max_call_duration_ms": 181000}, {"ring_duration_ms": 60000}, {"version": 4}, {"response_engine": {"type": "retell-llm"}}, {"webhook_events": []}, {"contact_memory_config": {"enable_read": True}}])
def test_unsafe_agent_configuration_never_originates(outbound_settings: ApiSettings, change: dict[str, object]) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, json={**agent(outbound_settings), **change} if request.url.path.startswith("/get-agent/") else phone())
    with httpx.Client(base_url="https://api.retellai.com", transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(OutboundProviderError) as caught:
            RetellOutboundProvider(outbound_settings, client).preflight()
        assert not caught.value.outcome_unknown


def test_creation_uses_only_retell_with_stable_key_and_required_telnyx_header(outbound_settings: ApiSettings) -> None:
    data = call_input()
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST" and request.url.host == "api.retellai.com"
        assert request.url.path == "/v2/create-phone-call"
        body = json.loads(request.content)
        assert body["idempotency_key"] == "dwellcall-" + str(data.request_id)
        assert body["honor_internal_dnc"] is True and body["ignore_e164_validation"] is False
        assert body["custom_sip_headers"] == {"X-Telnyx-Username": "synthetic-sip-user"}
        assert body["override_agent_version"] == 3
        return httpx.Response(201, json=phone_call("reservation", "proof").model_dump())
    with httpx.Client(base_url="https://api.retellai.com", transport=httpx.MockTransport(handle)) as client:
        assert RetellOutboundProvider(outbound_settings, client).dial(data, "reservation", "proof").call_status == "registered"


@pytest.mark.parametrize(("status", "unknown"), [(400, False), (401, False), (429, False), (500, True), (502, True), (302, True)])
def test_provider_errors_preserve_outcome_certainty(outbound_settings: ApiSettings, status: int, unknown: bool) -> None:
    requests = []
    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, json={"error": "sensitive carrier response"})
    with httpx.Client(base_url="https://api.retellai.com", transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(OutboundProviderError) as caught:
            RetellOutboundProvider(outbound_settings, client).dial(call_input(), "id", "proof")
        assert caught.value.outcome_unknown is unknown
        assert "sensitive" not in str(caught.value)
        assert len(requests) == 1


def test_timeout_and_malformed_receipt_never_retry(outbound_settings: ApiSettings) -> None:
    for timeout in (True, False):
        requests = []
        def handle(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if timeout:
                raise httpx.ReadTimeout("private destination", request=request)
            return httpx.Response(201, json={"call_id": "partial"})
        with httpx.Client(base_url="https://api.retellai.com", transport=httpx.MockTransport(handle)) as client:
            with pytest.raises(OutboundProviderError) as caught:
                RetellOutboundProvider(outbound_settings, client).dial(call_input(), "id", "proof")
            assert caught.value.outcome_unknown and len(requests) == 1


def test_malformed_trunk_data_produces_an_actionable_preflight_rejection(outbound_settings: ApiSettings) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        value = phone()
        value["sip_outbound_trunk_config"]["transport"] = {"invalid": True}
        return httpx.Response(200, json=value)
    with httpx.Client(base_url="https://api.retellai.com", transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(OutboundProviderError) as caught:
            RetellOutboundProvider(outbound_settings, client).preflight()
        assert caught.value.code == "RETELL_CONFIGURATION_INVALID" and not caught.value.outcome_unknown
