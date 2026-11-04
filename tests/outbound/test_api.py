from unittest.mock import Mock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from dwellcall.errors import ApiError, api_error_handler
from dwellcall.settings import ApiSettings
from dwellcall.telephony.outbound.routes import create_outbound_router
from dwellcall.telephony.outbound.schemas import CallResponse
from dwellcall.telephony.outbound.service import OutboundCallService
from tests.outbound.helpers import call_input, response_data


def application(settings: ApiSettings, service: OutboundCallService) -> FastAPI:
    app = FastAPI()
    @app.exception_handler(ApiError)
    async def handler(request: Request, error: ApiError) -> JSONResponse:
        return await api_error_handler(request, error)
    app.include_router(create_outbound_router(settings, service))
    return app


@pytest.mark.parametrize(("method", "path"), [("GET", "/calls"), ("GET", "/availability"), ("POST", "/calls"), ("POST", "/preflight"), ("POST", "/controls"), ("POST", "/suppress")])
def test_every_outbound_operation_requires_strong_operator_auth(outbound_settings: ApiSettings, method: str, path: str) -> None:
    service = Mock(spec=OutboundCallService)
    with TestClient(application(outbound_settings, service)) as client:
        assert client.request(method, "/api/v1/outbound" + path, json={}).status_code == 401
    service.create.assert_not_called()
    service.controls.assert_not_called()


def test_initiation_returns_receipt_without_claiming_an_answer(outbound_settings: ApiSettings) -> None:
    service = Mock(spec=OutboundCallService)
    data = call_input()
    service.create.return_value = CallResponse.model_validate(response_data(request_id=str(data.request_id)))
    with TestClient(application(outbound_settings, service)) as client:
        response = client.post("/api/v1/outbound/calls", headers={"X-Admin-Token": "b" * 43, "Idempotency-Key": str(data.request_id)}, json=data.model_dump(mode="json"))
        assert response.status_code == 200 and response.json()["status"] == "dialing"
        assert response.json()["started_at"] is None and response.json()["terminal"] is False
    service.create.assert_called_once_with(data)


def test_mismatched_idempotency_header_never_calls_service(outbound_settings: ApiSettings) -> None:
    service = Mock(spec=OutboundCallService)
    with TestClient(application(outbound_settings, service)) as client:
        response = client.post("/api/v1/outbound/calls", headers={"X-Admin-Token": "b" * 43, "Idempotency-Key": "different"}, json=call_input().model_dump(mode="json"))
        assert response.status_code == 409
    service.create.assert_not_called()
