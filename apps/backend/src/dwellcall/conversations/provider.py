from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field

from dwellcall.errors import ApiError
from dwellcall.settings import ApiSettings
from dwellcall.telephony.retell.schemas import CallId, RetellCall

if TYPE_CHECKING:
    from dwellcall.telephony.retell.provider import RetellGateway


class IceServer(BaseModel):
    urls: str | list[str]
    username: str | None = None
    credential: str | None = None


class WebGrant(BaseModel):
    call_id: CallId
    access_token: str = Field(min_length=1, max_length=16000)
    transport: str = Field(pattern="^gateway$")
    ice_servers: list[IceServer] = Field(max_length=20)
    expires_at: int = Field(gt=0)


class BrowserProvider:
    def __init__(self, settings: ApiSettings, gateway: RetellGateway) -> None:
        self.settings, self.gateway = settings, gateway

    async def preflight(self) -> None:
        settings = self.settings
        agent_id, version = settings.retell_agent_id, settings.retell_agent_version
        if agent_id is None or version is None:
            raise ApiError(status_code=503, code="BROWSER_AGENT_INVALID", message="Pin the private Retell web agent and version")
        agent = await self.gateway._client.agent.retrieve(agent_id, version=version)
        data = agent.model_dump()
        engine = data.get("response_engine") or {}
        socket = urlsplit(str(engine.get("llm_websocket_url", "")))
        secret = settings.retell_websocket_secret
        expected_path = "/api/v1/retell/llm/" + (secret.get_secret_value() if secret else "")
        memory = data.get("contact_memory_config")
        retention = data.get("data_storage_retention_days")
        if (
            agent.agent_id != settings.retell_agent_id or agent.version != settings.retell_agent_version
            or data.get("is_published") is not True or engine.get("type") != "custom-llm"
            or socket.scheme != "wss" or not socket.hostname or socket.username or socket.password
            or socket.path != expected_path or socket.query or socket.fragment
            or data.get("data_storage_setting") != "basic_attributes_only"
            or type(retention) is not int or not 1 <= retention <= 7
            or not isinstance(data.get("max_call_duration_ms"), int)
            or not 60000 <= data["max_call_duration_ms"] <= settings.conversation_max_duration_seconds * 1000
            or (memory is not None and (not isinstance(memory, dict) or memory.get("enable_read") is not False or memory.get("enable_update") is not False))
            or data.get("pre_session_tools") or data.get("post_session_tools")
            or data.get("webhook_url") != "https://" + socket.netloc + "/api/v1/retell/webhook"
            or (data.get("webhook_events") is not None and not {"call_started", "call_ended", "call_analyzed"}.issubset(data["webhook_events"]))
        ):
            raise ApiError(status_code=503, code="BROWSER_AGENT_INVALID", message="Configure the published pinned web agent, Custom LLM URL, signed lifecycle webhooks, privacy and duration limits")

    async def request(self, path: str, body: dict[str, object]) -> dict[str, object]:
        key = self.settings.retell_api_key
        if key is None:
            raise ValueError("Retell credentials are unavailable")
        async with httpx.AsyncClient(timeout=12, trust_env=False, follow_redirects=False) as client:
            response = await client.post("https://api.retellai.com" + path, headers={"Authorization": "Bearer " + key.get_secret_value()}, json=body)
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("Invalid browser provider receipt")
            return result

    async def create(self, metadata: dict[str, object]) -> WebGrant:
        try:
            data = await self.request("/v3/create-web-call", {
                "agent_id": self.settings.retell_agent_id,
                "agent_version": self.settings.retell_agent_version,
                "metadata": metadata,
            })
        except httpx.HTTPStatusError as error:
            if error.response.status_code in {400, 401, 403, 404, 422, 429}:
                raise ApiError(status_code=503, code="BROWSER_PROVIDER_REJECTED", message="Retell rejected browser call creation; correct agent access or quota before another deliberate request") from None
            raise
        return WebGrant.model_validate(data)

    async def find(self, local_id: str) -> RetellCall | None:
        data = await self.request("/v3/list-calls", {
            "filter_criteria": {"metadata": [{"type": "string", "key": "dwellcall_browser_id", "value": local_id}]},
            "limit": 2, "sort_order": "descending",
        })
        items = data.get("items")
        if data.get("has_more") is not False or not isinstance(items, list) or len(items) > 1:
            raise ValueError("Browser call lookup is incomplete")
        return RetellCall.model_validate(items[0]) if items else None

    async def stop(self, provider_id: str) -> None:
        key = self.settings.retell_api_key
        if key is None:
            raise ValueError("Retell credentials are unavailable")
        async with httpx.AsyncClient(timeout=12, trust_env=False, follow_redirects=False) as client:
            response = await client.post("https://api.retellai.com/v2/stop-call/" + provider_id, headers={"Authorization": "Bearer " + key.get_secret_value()})
            response.raise_for_status()
