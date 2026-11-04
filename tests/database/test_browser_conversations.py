import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from dwellcall.consultant.catalog import PropertyRequirements
from dwellcall.consultant.state import AI_ONLY_HANDOFF_REPLY
from dwellcall.conversations.provider import WebGrant
from dwellcall.conversations.schemas import StartConversation, TextTurn
from dwellcall.conversations.service import BrowserConversationService
from dwellcall.database.models import AudioSession, BrowserConversation
from dwellcall.errors import ApiError
from dwellcall.settings import ApiSettings
from dwellcall.telephony.retell.schemas import RetellCall
from dwellcall.telephony.retell.service import AudioSessionService

OWNER = "v" * 43


def configuration(settings, **updates):
    return ApiSettings.model_validate({**settings.model_dump(), "browser_mock_enabled": True, "conversation_daily_budget_cents": 500, **updates})


def start(mode="text", scenario="renting"):
    return StartConversation(request_id=uuid4(), mode=mode, scenario=scenario, ai_consent=True, fictional_data_only=True)


@pytest.mark.parametrize("scenario", ["renting", "buying", "luxury"])
def test_mock_browser_lifecycle_reuses_budget_and_never_contacts_a_provider(sessions, settings, scenario):
    provider = Mock()
    service = BrowserConversationService(sessions, configuration(settings), None, provider)
    async def check():
        data = start(scenario=scenario)
        begun = await service.start(OWNER, data)
        assert begun.conversation.mock and begun.state_token and begun.grant is None
        with pytest.raises(ApiError):
            await service.start(OWNER, data)
        with pytest.raises(ApiError):
            AudioSessionService(sessions, settings).reserve("another-call", "agent")
        turn = TextTurn.model_validate({"state_token": begun.state_token, "transcript": [{"role": "user", "content": "Help me explore"}]})
        reply = await service.reply(OWNER, data.request_id, turn)
        assert "Simulation" in reply.reply and reply.conversation.turn_count == 1
        with pytest.raises(ApiError):
            await service.reply(OWNER, data.request_id, turn)
        restarted = BrowserConversationService(sessions, configuration(settings), None, provider)
        assert restarted.get(data.request_id, OWNER).status == "active"
        assert (await restarted.end(OWNER, data.request_id)).status == "ended"
        assert (await restarted.end(OWNER, data.request_id)).status == "ended"
        with sessions() as session:
            row = session.get(BrowserConversation, data.request_id)
            assert session.get(AudioSession, row.audio_session_id).reserved_cost_cents == 100
    asyncio.run(check())
    assert provider.mock_calls == []


def test_browser_ownership_and_signed_state_cannot_cross_sessions(sessions, settings):
    service = BrowserConversationService(sessions, configuration(settings), None, None)
    async def check():
        data = start()
        begun = await service.start(OWNER, data)
        with pytest.raises(ApiError):
            service.get(data.request_id, "x" * 43)
        with pytest.raises(ApiError):
            await service.end("x" * 43, data.request_id)
        with pytest.raises(ApiError):
            await service.reply(OWNER, data.request_id, TextTurn.model_validate({"state_token": begun.state_token + "corrupt", "transcript": [{"role": "user", "content": "Hello"}]}))
        assert service.get(data.request_id, OWNER).turn_count == 0
    asyncio.run(check())


def test_mock_text_human_request_explains_ai_only_operation(sessions, settings):
    service = BrowserConversationService(sessions, configuration(settings), None, None)
    async def check():
        data = start()
        begun = await service.start(OWNER, data)
        reply = await service.reply(OWNER, data.request_id, TextTurn.model_validate({
            "state_token": begun.state_token,
            "transcript": [{"role": "user", "content": "Can I speak to a human?"}],
        }))
        assert reply.reply == AI_ONLY_HANDOFF_REPLY
        assert reply.conversation.status == "active"
    asyncio.run(check())


def test_text_concurrency_and_stop_during_generation_cannot_replay_or_revive(sessions, settings):
    async def check():
        entered, release = asyncio.Event(), asyncio.Event()
        class Consultant:
            def greeting(self, scenario):
                return "Fictional property consultation"
            async def stream(self, transcript, state):
                entered.set()
                await release.wait()
                state.requirements = PropertyRequirements(scenario="buying", max_budget=700000, bedrooms=3)
                yield "A fictional response"
        config = configuration(settings, browser_mock_enabled=False, browser_text_enabled=True)
        service = BrowserConversationService(sessions, config, Consultant(), None)
        data = start(scenario="buying")
        begun = await service.start(OWNER, data)
        turn = TextTurn.model_validate({"state_token": begun.state_token, "transcript": [{"role": "user", "content": "A home with three bedrooms"}]})
        pending = asyncio.create_task(service.reply(OWNER, data.request_id, turn))
        await entered.wait()
        with pytest.raises(ApiError):
            await service.reply(OWNER, data.request_id, turn)
        assert (await service.end(OWNER, data.request_id)).status == "unknown"
        release.set()
        with pytest.raises(ApiError):
            await pending
        assert service.get(data.request_id, OWNER).status == "ended"
    asyncio.run(check())


def test_voice_timeout_retains_the_slot_without_another_provider_creation(sessions, settings):
    provider = Mock()
    provider.preflight = AsyncMock()
    provider.create = AsyncMock(side_effect=TimeoutError())
    configured = configuration(settings, browser_mock_enabled=False, browser_voice_enabled=True, retell_test_audio_enabled=True)
    service = BrowserConversationService(sessions, configured, None, provider)
    async def check():
        data = start(mode="voice")
        with pytest.raises(ApiError):
            await service.start(OWNER, data)
        assert service.get(data.request_id, OWNER).status == "unknown"
        with pytest.raises(ApiError):
            await service.start(OWNER, data)
        with pytest.raises(ApiError):
            AudioSessionService(sessions, configured).reserve("other", "agent")
    asyncio.run(check())
    provider.create.assert_awaited_once()


def test_expired_text_session_can_be_recovered_without_storing_transcripts(sessions, settings):
    service = BrowserConversationService(sessions, configuration(settings), None, None)
    async def check():
        data = start()
        await service.start(OWNER, data)
        with sessions() as session, session.begin():
            row = session.get(BrowserConversation, data.request_id)
            session.get(AudioSession, row.audio_session_id).created_at -= timedelta(minutes=4)
        assert service.get(data.request_id, OWNER).status == "ended"
        assert "transcript" not in BrowserConversation.__table__.columns
        assert "access_token" not in BrowserConversation.__table__.columns
    asyncio.run(check())


def test_browser_voice_attaches_to_one_reservation_and_stops_without_reconnecting(sessions, settings):
    provider = Mock()
    provider.preflight = AsyncMock()
    configured = configuration(settings, browser_mock_enabled=False, browser_voice_enabled=True, retell_test_audio_enabled=True)
    service = BrowserConversationService(sessions, configured, None, provider)
    calls = []
    async def create(metadata):
        calls.append(RetellCall(call_id="call_browser_test", agent_id=configured.retell_agent_id, agent_version=configured.retell_agent_version, call_type="web_call", call_status="registered", metadata=metadata))
        return WebGrant(call_id="call_browser_test", access_token="synthetic-grant", transport="gateway", ice_servers=[], expires_at=4102444800000)
    provider.create = AsyncMock(side_effect=create)
    provider.gateway.retrieve = AsyncMock(side_effect=lambda call_id: calls[0])
    async def stop(provider_id):
        calls[0] = calls[0].model_copy(update={"call_status": "ended", "disconnection_reason": "manual_stopped"})
    provider.stop = AsyncMock(side_effect=stop)
    async def check():
        data = start(mode="voice", scenario="luxury")
        begun = await service.start(OWNER, data)
        assert begun.grant["transport"] == "gateway"
        audio_id, scenario = service.apply(calls[0], admit=True)
        assert scenario == "luxury" and service.active(audio_id)
        with pytest.raises(ApiError):
            service.apply(calls[0], admit=True)
        with pytest.raises(ApiError):
            service.validate_details(audio_id, calls[0].model_copy(update={"agent_version": 99}))
        assert (await service.end(OWNER, data.request_id)).status == "ended"
        assert not service.active(audio_id)
        with pytest.raises(ApiError):
            service.apply(calls[0], admit=True)
    asyncio.run(check())
    provider.create.assert_awaited_once()
    provider.stop.assert_awaited_once_with("call_browser_test")
