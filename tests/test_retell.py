import asyncio
import hashlib
import hmac
import time
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from dwellcall.errors import ApiError
from dwellcall.settings import ApiSettings
from dwellcall.telephony.retell.provider import RetellGateway
from dwellcall.telephony.retell.schemas import REQUEST, RetellCall


def call(**updates: object) -> RetellCall:
    return RetellCall.model_validate({
        "call_id": "call_private", "agent_id": "agent_dwellcall_test",
        "agent_version": 0, "call_type": "web_call", "call_status": "ongoing",
        **updates,
    })


@pytest.mark.parametrize("updates", [
    {"agent_id": "other_agent"}, {"call_type": "phone_call"},
    {"call_id": "another_call"}, {"agent_version": 1},
])
def test_cross_agent_phone_and_mismatched_calls_are_rejected(
    settings: ApiSettings, updates: dict[str, object],
) -> None:
    async def check() -> None:
        gateway = RetellGateway(settings)
        try:
            with pytest.raises(ApiError):
                gateway.validate_identity(call(**updates), "call_private")
        finally:
            await gateway.close()
    asyncio.run(check())


def test_signature_uses_exact_body_and_rejects_replays(settings: ApiSettings) -> None:
    async def check() -> None:
        gateway = RetellGateway(settings)
        body = b'{ "event": "call_ended" }'
        def signature(timestamp: int) -> str:
            digest = hmac.new(
                b"synthetic-retell-key", body + str(timestamp).encode(), hashlib.sha256,
            ).hexdigest()
            return f"v={timestamp},d={digest}"
        try:
            now = int(time.time() * 1000)
            assert gateway.verify(body, signature(now))
            assert not gateway.verify(body.replace(b" ", b""), signature(now))
            assert not gateway.verify(body, signature(now - 600_000))
            assert not gateway.verify(body, signature(now + 600_000))
            assert not gateway.verify(body, "malformed")
        finally:
            await gateway.close()
    asyncio.run(check())


def test_ended_call_fails_before_agent_lookup(settings: ApiSettings) -> None:
    async def check() -> None:
        gateway = RetellGateway(settings)
        gateway.retrieve = AsyncMock(return_value=call(call_status="ended"))
        try:
            with pytest.raises(ApiError, match="inactive"):
                await gateway.authorize("call_private")
        finally:
            await gateway.close()
    asyncio.run(check())


@pytest.mark.parametrize("payload", [
    '{"interaction_type":"response_required","response_id":true,"transcript":[]}',
    '{"interaction_type":"response_required","response_id":1,"transcript":[{"role":"tool","content":"x"}]}',
    '{"interaction_type":"response_required","response_id":1,"transcript":{}}',
])
def test_malformed_protocol_messages_are_rejected(payload: str) -> None:
    with pytest.raises(ValidationError):
        REQUEST.validate_json(payload)
