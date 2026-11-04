import asyncio
import threading
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from dwellcall.consultant.graph import PropertyConsultant
from dwellcall.errors import ApiError, api_error_handler
from dwellcall.settings import ApiSettings
from dwellcall.telephony.retell import routes
from dwellcall.telephony.retell.provider import RetellGateway
from dwellcall.telephony.retell.schemas import RetellCall
from dwellcall.telephony.retell.service import AudioSessionService


def application(
    monkeypatch: pytest.MonkeyPatch, settings: ApiSettings,
    consultant: PropertyConsultant,
) -> tuple[FastAPI, Mock, Mock]:
    gateway = Mock(spec=RetellGateway)
    gateway.authorize = AsyncMock(return_value=RetellCall(
        call_id="call_private", agent_id="agent_dwellcall_test", agent_version=0,
        call_type="web_call", call_status="ongoing",
    ))
    service = Mock(spec=AudioSessionService)
    service.is_active.return_value = True
    monkeypatch.setattr(routes, "AudioSessionService", Mock(return_value=service))
    app = FastAPI()
    @app.exception_handler(ApiError)
    async def error_handler(request: Request, error: ApiError) -> JSONResponse:
        return await api_error_handler(request, error)
    configured = settings.model_copy(update={"retell_test_audio_enabled": True})
    app.include_router(routes.create_retell_router(configured, Mock(), gateway, consultant))
    return app, gateway, service


def test_bad_websocket_secret_fails_before_provider_and_reservation(
    monkeypatch: pytest.MonkeyPatch, settings: ApiSettings,
) -> None:
    app, gateway, service = application(monkeypatch, settings, Mock(spec=PropertyConsultant))
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/api/v1/retell/llm/invalid/call_private"):
                pass
    gateway.authorize.assert_not_called()
    service.reserve.assert_not_called()


def test_new_response_cancels_old_stream_and_preserves_request_identity(
    monkeypatch: pytest.MonkeyPatch, settings: ApiSettings,
) -> None:
    cancelled = threading.Event()
    class Consultant:
        def greeting(self) -> str:
            return "A fictional property demonstration"

        async def stream(self, transcript: object, session: object) -> AsyncIterator[str]:
            if not transcript:
                yield "first"
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            else:
                yield "replacement"
    app, _, service = application(monkeypatch, settings, Consultant())
    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/retell/llm/{'a' * 43}/call_private") as socket:
            assert socket.receive_json()["response_type"] == "config"
            assert "fictional" in socket.receive_json()["content"]
            socket.send_json({"interaction_type": "response_required", "response_id": 1, "transcript": []})
            assert socket.receive_json()["content"] == "first"
            socket.send_json({
                "interaction_type": "response_required", "response_id": 2,
                "transcript": [{"role": "user", "content": "I changed my mind"}],
            })
            response = socket.receive_json()
            assert response["response_id"] == 2
            assert response["content"] == "replacement"
            assert socket.receive_json()["content_complete"] is True
            socket.send_json({"interaction_type": "ping_pong", "timestamp": 123})
            assert socket.receive_json() == {"response_type": "ping_pong", "timestamp": 123}
    assert cancelled.wait(timeout=1)
    service.disconnect.assert_called_once_with("call_private")


def test_operator_refresh_requires_authentication(
    monkeypatch: pytest.MonkeyPatch, settings: ApiSettings,
) -> None:
    app, gateway, _ = application(monkeypatch, settings, Mock(spec=PropertyConsultant))
    with TestClient(app) as client:
        assert client.post("/api/v1/retell/admin/calls/call_private/refresh").status_code == 401
    gateway.retrieve.assert_not_called()


def test_completed_closing_turn_sets_retell_end_call_without_releasing_reservation(
    monkeypatch: pytest.MonkeyPatch, settings: ApiSettings,
) -> None:
    class Consultant:
        def greeting(self) -> str:
            return "A fictional property demonstration"

        async def stream(self, transcript, session):
            yield "Goodbye."
            session.end_call = True

    app, _, service = application(monkeypatch, settings, Consultant())
    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/retell/llm/{'a' * 43}/call_private") as socket:
            socket.receive_json()
            socket.receive_json()
            socket.send_json({
                "interaction_type": "response_required", "response_id": 1,
                "transcript": [{"role": "user", "content": "Goodbye"}],
            })
            assert socket.receive_json()["content"] == "Goodbye."
            final = socket.receive_json()
            assert final["content_complete"] is True and final["end_call"] is True
    service.finalize.assert_not_called()
    service.disconnect.assert_called_once_with("call_private")
