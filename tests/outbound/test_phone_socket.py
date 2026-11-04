import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from dwellcall.consultant.catalog import PropertyRequirements
from dwellcall.consultant.state import ConsultationSession, RequirementExtraction, TRANSFER_PROMPT
from dwellcall.errors import ApiError, api_error_handler
from dwellcall.telephony.outbound.service import OutboundCallService
from dwellcall.telephony.retell import routes
from dwellcall.telephony.retell.provider import RetellGateway
from dwellcall.telephony.retell.schemas import Utterance
from tests.outbound.helpers import phone_call


class Consultant:
    def greeting(self, scenario=None):
        return "I am DwellCall's AI property consultant. " + str(scenario)

    async def stream(self, transcript: list[Utterance], session: ConsultationSession):
        update = session.propose(RequirementExtraction(requirements=PropertyRequirements(scenario="renting"), intent="handoff" if transcript[-1].content == "A human please" else "continue"), transcript, self.settings)
        yield update.reply or "I can help with fictional properties."
        session.commit(update)


def application(monkeypatch, settings, transfer=False):
    provider_call = phone_call(str(uuid4()), "proof", call_status="ongoing")
    gateway = Mock(spec=RetellGateway)
    gateway.authorize = AsyncMock(return_value=provider_call)
    outbound = Mock(spec=OutboundCallService)
    outbound.admit_phone.return_value = ("reserved_audio", "renting")
    outbound.remaining_seconds.return_value = 180.0
    outbound.transfer_available.return_value = transfer
    outbound.active.return_value = True
    outbound.reserve_transfer.return_value = "+12025550125"
    audio = Mock()
    monkeypatch.setattr(routes, "AudioSessionService", Mock(return_value=audio))
    consultant = Consultant()
    consultant.settings = settings
    app = FastAPI()
    @app.exception_handler(ApiError)
    async def handler(request: Request, error: ApiError) -> JSONResponse:
        return await api_error_handler(request, error)
    app.include_router(routes.create_retell_router(settings, Mock(), gateway, consultant, outbound))
    return app, provider_call, gateway, outbound, audio


def test_phone_uses_existing_reservation_and_consultant(monkeypatch, outbound_settings):
    app, call, _, outbound, audio = application(monkeypatch, outbound_settings)
    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/retell/llm/{'a' * 43}/{call.call_id}") as socket:
            assert socket.receive_json()["response_type"] == "config"
            assert "AI property consultant" in socket.receive_json()["content"]
            socket.send_json({"interaction_type": "response_required", "response_id": 1, "transcript": [{"role": "user", "content": "One bedroom"}]})
            assert "fictional" in socket.receive_json()["content"]
            assert socket.receive_json()["content_complete"] is True
    audio.reserve.assert_not_called()
    outbound.admit_phone.assert_called_once_with(call)
    outbound.disconnect.assert_called_once_with("reserved_audio")


def test_phone_admission_failure_never_greets_or_reserves_twice(monkeypatch, outbound_settings):
    app, call, _, outbound, audio = application(monkeypatch, outbound_settings)
    outbound.admit_phone.side_effect = ApiError(status_code=403, code="UNBOUND", message="Not authorized")
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/api/v1/retell/llm/{'a' * 43}/{call.call_id}"):
                pass
    outbound.disconnect.assert_not_called()
    audio.reserve.assert_not_called()


def test_transfer_number_only_follows_the_spoken_separate_turn_confirmation(monkeypatch, outbound_settings):
    app, call, _, outbound, _ = application(monkeypatch, outbound_settings, transfer=True)
    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/retell/llm/{'a' * 43}/{call.call_id}") as socket:
            socket.receive_json(); socket.receive_json()
            socket.send_json({"interaction_type": "response_required", "response_id": 1, "transcript": [{"role": "user", "content": "A human please"}]})
            assert socket.receive_json()["content"] == TRANSFER_PROMPT
            assert "transfer_number" not in socket.receive_json()
            outbound.reserve_transfer.assert_not_called()
            socket.send_json({"interaction_type": "response_required", "response_id": 2, "transcript": [{"role": "user", "content": "A human please"}, {"role": "agent", "content": TRANSFER_PROMPT}, {"role": "user", "content": "yes"}]})
            assert "not confirmed" in socket.receive_json()["content"]
            final = socket.receive_json()
            assert final["transfer_number"] == "+12025550125" and final["show_transferee_as_caller"] is False
            outbound.reserve_transfer.assert_called_once()


def test_do_not_call_suppresses_without_a_model_request(monkeypatch, outbound_settings):
    app, call, _, outbound, _ = application(monkeypatch, outbound_settings)
    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/retell/llm/{'a' * 43}/{call.call_id}") as socket:
            socket.receive_json(); socket.receive_json()
            socket.send_json({"interaction_type": "response_required", "response_id": 1, "transcript": [{"role": "user", "content": "Do not call me again"}]})
            assert socket.receive_json()["end_call"] is True
    outbound.suppress_call.assert_called_once_with("reserved_audio")


def test_phone_webhook_verification_receives_original_request_bytes(monkeypatch, outbound_settings):
    app, call, gateway, outbound, _ = application(monkeypatch, outbound_settings)
    final = call.model_copy(update={"call_status": "ended", "disconnection_reason": "agent_hangup"})
    body = b'{ "event": "call_ended", "call": ' + json.dumps(final.model_dump()).encode() + b' }'
    timestamp = int(time.time() * 1000)
    signature = "v=" + str(timestamp) + ",d=" + hmac.new(b"synthetic-retell-key", body + str(timestamp).encode(), hashlib.sha256).hexdigest()
    gateway.verify.side_effect = lambda raw, supplied: raw == body and supplied == signature
    outbound.event_digest.return_value = "event-digest"
    with TestClient(app) as client:
        assert client.post("/api/v1/retell/webhook", content=body, headers={"X-Retell-Signature": signature}).status_code == 200
        assert client.post("/api/v1/retell/webhook", content=body.replace(b" ", b""), headers={"X-Retell-Signature": signature}).status_code == 401
    outbound.apply.assert_called_once_with(final, "call_ended", "event-digest")


def test_expired_phone_conversation_does_not_greet_or_release_the_call(monkeypatch, outbound_settings):
    app, call, _, outbound, audio = application(monkeypatch, outbound_settings)
    outbound.remaining_seconds.return_value = 0
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/api/v1/retell/llm/{'a' * 43}/{call.call_id}"):
                pass
    outbound.disconnect.assert_called_once_with("reserved_audio")
    audio.finalize.assert_not_called()


def test_transfer_disable_race_returns_a_failure_without_a_transfer_frame(monkeypatch, outbound_settings):
    app, call, _, outbound, _ = application(monkeypatch, outbound_settings, transfer=True)
    outbound.reserve_transfer.side_effect = ApiError(status_code=409, code="OUTBOUND_TRANSFER_DISABLED", message="Paused")
    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/retell/llm/{'a' * 43}/{call.call_id}") as socket:
            socket.receive_json(); socket.receive_json()
            socket.send_json({"interaction_type": "response_required", "response_id": 1, "transcript": [{"role": "user", "content": "A human please"}]})
            socket.receive_json(); socket.receive_json()
            socket.send_json({"interaction_type": "response_required", "response_id": 2, "transcript": [{"role": "agent", "content": TRANSFER_PROMPT}, {"role": "user", "content": "yes"}]})
            socket.receive_json()
            failure = socket.receive_json()
            assert "unavailable" in failure["content"] and "transfer_number" not in failure
