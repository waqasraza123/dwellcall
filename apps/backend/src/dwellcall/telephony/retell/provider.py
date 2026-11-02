from typing import cast

import httpx
from retell import AsyncRetell

from dwellcall.errors import ApiError
from dwellcall.settings import ApiSettings
from dwellcall.telephony.retell.schemas import RetellCall


class RetellGateway:
    def __init__(self, settings: ApiSettings) -> None:
        if settings.retell_api_key is None:
            raise ValueError("Retell credentials are required")
        self.settings = settings
        self._key = settings.retell_api_key.get_secret_value()
        self._client = AsyncRetell(
            api_key=self._key,
            base_url="https://api.retellai.com",
            max_retries=0,
            http_client=httpx.AsyncClient(timeout=10, trust_env=False),
        )

    async def close(self) -> None:
        await self._client.close()

    def validate_identity(self, call: RetellCall, call_id: str) -> None:
        if (
            call.call_id != call_id
            or call.agent_id != self.settings.retell_agent_id
            or call.agent_version != self.settings.retell_agent_version
            or call.call_type != "web_call"
        ):
            raise ApiError(
                status_code=403,
                code="CALL_IDENTITY_INVALID",
                message="The call does not belong to the private audio agent",
            )

    async def retrieve(self, call_id: str) -> RetellCall:
        result = await self._client.call.retrieve(call_id)
        call = RetellCall.model_validate(result.model_dump())
        self.validate_identity(call, call_id)
        return call

    async def authorize(self, call_id: str) -> RetellCall:
        call = await self.retrieve(call_id)
        if call.call_status not in {"registered", "ongoing"}:
            raise ApiError(
                status_code=409, code="CALL_INACTIVE", message="The call is inactive"
            )
        agent_id = self.settings.retell_agent_id
        version = self.settings.retell_agent_version
        if agent_id is None or version is None:
            raise ValueError("Retell agent configuration is unavailable")
        agent = await self._client.agent.retrieve(agent_id, version=version)
        duration = agent.max_call_duration_ms
        if (
            agent.agent_id != call.agent_id
            or agent.version != call.agent_version
            or agent.response_engine.type != "custom-llm"
            or duration is None
            or not (
                60000 <= duration
                <= self.settings.conversation_max_duration_seconds * 1000
            )
        ):
            raise ApiError(
                status_code=503,
                code="AGENT_LIMIT_INVALID",
                message="Configure the private agent duration and response engine",
            )
        return call

    def verify(self, body: bytes, signature: str) -> bool:
        return cast(
            bool,
            self._client.verify(
                body.decode("utf-8"), api_key=self._key, signature=signature
            ),
        )
