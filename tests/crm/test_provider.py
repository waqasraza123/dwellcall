import base64
from dataclasses import replace

import httpx
import pytest

from dwellcall.crm.contracts import CrmExportRequest
from dwellcall.crm.providers.followupboss import EVENTS_URL, FollowUpBossProvider
from dwellcall.crm.providers.none import NoCrmProvider
from dwellcall.crm.settings import CrmSettings


def test_auth_registration_and_only_fictional_inquiry_fields(
    crm_settings: CrmSettings, export_request: CrmExportRequest,
) -> None:
    import json
    def handle(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == EVENTS_URL
        assert request.method == "POST"
        assert request.headers["authorization"] == "Basic " + base64.b64encode(b"synthetic-fub-api-key:").decode()
        assert request.headers["x-system"] == "DwellCallMock"
        assert request.headers["x-system-key"] == "synthetic-system-key"
        assert "idempotency-key" not in request.headers
        payload = json.loads(request.content)
        assert set(payload) == {"type", "source", "system", "person", "message", "description"}
        assert payload["type"] == "General Inquiry"
        assert "FICTIONAL DEMONSTRATION" in payload["message"]
        assert "FICTIONAL DEMONSTRATION" in payload["description"]
        assert str(export_request.export_id) in payload["description"]
        assert payload["person"] == {"firstName": "Demo", "emails": [{"value": "visitor@example.com"}]}
        assert "budget" in payload["description"] and "monthly" in payload["description"]
        return httpx.Response(201, json={"id": 101})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = FollowUpBossProvider(crm_settings, client).send(export_request)
    assert result.status == "sent" and result.person_id == 101


@pytest.mark.parametrize(("status", "expected"), [
    (200, "sent"), (201, "sent"), (204, "ignored"),
    (400, "failed"), (401, "failed"), (403, "failed"), (404, "failed"),
    (422, "failed"), (429, "retry_wait"), (500, "unknown"),
    (503, "unknown"), (302, "unknown"), (409, "unknown"),
])
def test_response_semantics(
    crm_settings: CrmSettings, export_request: CrmExportRequest,
    status: int, expected: str,
) -> None:
    calls = []
    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, json={"id": 101}, headers={"Retry-After": "120", "Location": "https://example.com"})
    with httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        result = FollowUpBossProvider(crm_settings, client).send(export_request)
    assert result.status == expected
    assert len(calls) == 1
    if status == 429:
        assert result.retry_after_seconds == 120


@pytest.mark.parametrize("body", [b"not-json", b'{}', b'{"id":true}', b'{"id":"101"}', b'{"id":-1}', b"x" * 65537])
def test_invalid_receipt_is_never_retried_automatically(
    crm_settings: CrmSettings, export_request: CrmExportRequest, body: bytes,
) -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))) as client:
        assert FollowUpBossProvider(crm_settings, client).send(export_request).status == "unknown"


@pytest.mark.parametrize(("error", "expected"), [
    (httpx.ReadTimeout, "unknown"), (httpx.WriteTimeout, "unknown"),
    (httpx.ConnectTimeout, "retry_wait"), (httpx.ConnectError, "retry_wait"),
    (httpx.PoolTimeout, "retry_wait"),
])
def test_transport_certainty_controls_retries(
    crm_settings: CrmSettings, export_request: CrmExportRequest,
    error: type[httpx.RequestError], expected: str,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise error("synthetic-sensitive-provider-error", request=request)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = FollowUpBossProvider(crm_settings, client).send(export_request)
    assert result.status == expected
    assert "sensitive" not in result.code


def test_off_and_changed_destination_never_send(
    crm_settings: CrmSettings, export_request: CrmExportRequest,
) -> None:
    def forbidden(request: httpx.Request) -> httpx.Response:
        pytest.fail("Disabled or changed-destination export attempted HTTP")
    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        off = crm_settings.model_copy(update={"crm_sync_enabled": False})
        assert FollowUpBossProvider(off, client).send(export_request).status == "disabled"
        changed = replace(export_request, destination="0" * 64)
        assert FollowUpBossProvider(crm_settings, client).send(changed).status == "failed"
    assert NoCrmProvider().send(export_request).status == "disabled"


@pytest.mark.parametrize("header", ["", "garbage", "-1", "99999999999999999999999999"])
def test_malformed_retry_after_uses_safe_delay(
    crm_settings: CrmSettings, export_request: CrmExportRequest, header: str,
) -> None:
    with httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(429, headers={"Retry-After": header})
    )) as client:
        result = FollowUpBossProvider(crm_settings, client).send(export_request)
    assert result.status == "retry_wait" and result.retry_after_seconds >= 60
