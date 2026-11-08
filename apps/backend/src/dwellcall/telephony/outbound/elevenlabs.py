"""ElevenLabs SIP outbound adapter adapted from HVACLine."""
import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

import httpx

from dwellcall.settings import ApiSettings
from dwellcall.telephony.outbound.prompt import DEMO_PROMPT, FIRST_MESSAGE
from dwellcall.telephony.outbound.provider import OutboundProviderError, rejected
from dwellcall.telephony.outbound.schemas import CallInput
from dwellcall.telephony.retell.schemas import RetellCall

MAX_WEBHOOK_BYTES = 1_000_000


def object_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


class ElevenLabsOutboundProvider:
    def __init__(self, settings: ApiSettings, client: httpx.Client | None = None) -> None:
        self.settings, self.client = settings, client

    def _request(self, method: str, path: str, payload: dict[str, object] | None = None) -> httpx.Response:
        key = self.settings.elevenlabs_api_key
        if key is None:
            raise rejected("ELEVENLABS_CREDENTIALS_MISSING", "Configure the ElevenLabs API key")
        client = self.client or httpx.Client(base_url="https://api.elevenlabs.io", timeout=12, follow_redirects=False, trust_env=False)
        try:
            return client.request(method, path, headers={"xi-api-key": key.get_secret_value()}, json=payload)
        finally:
            if self.client is None:
                client.close()

    def _read(self, path: str) -> dict[str, Any]:
        try:
            response = self._request("GET", path)
            response.raise_for_status()
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError("Invalid provider object")
            return value
        except (httpx.HTTPError, ValueError, TypeError):
            raise rejected("ELEVENLABS_READ_UNAVAILABLE", "ElevenLabs could not confirm configuration or call status") from None

    def preflight(self, destination: str | None = None) -> None:
        try:
            self._preflight(destination)
        except (ValueError, TypeError, OverflowError):
            raise rejected("ELEVENLABS_CONFIGURATION_INVALID", "ElevenLabs returned malformed configuration") from None

    def _preflight(self, destination: str | None) -> None:
        settings = self.settings
        agent = self._read("/v1/convai/agents/" + quote(settings.outbound_agent_id or "", safe=""))
        configuration = object_value(agent.get("conversation_config"))
        agent_config = object_value(configuration.get("agent"))
        prompt = object_value(agent_config.get("prompt"))
        platform = object_value(agent.get("platform_settings"))
        privacy = object_value(platform.get("privacy"))
        workspace = object_value(platform.get("workspace_overrides"))
        hooks = object_value(workspace.get("webhooks"))
        duration = object_value(configuration.get("conversation")).get("max_duration_seconds")
        tools = prompt.get("tools") or []
        built_in = object_value(prompt.get("built_in_tools"))
        if not isinstance(tools, list):
            raise rejected("ELEVENLABS_AGENT_INVALID", "Invalid agent tools")
        tools = tools + [value for value in built_in.values() if value is not None]
        if (
            agent.get("agent_id") != settings.outbound_agent_id
            or type(duration) is not int or not 1 <= duration <= settings.outbound_max_duration_seconds
            or agent_config.get("first_message") != FIRST_MESSAGE
            or str(prompt.get("prompt", "")).strip() != DEMO_PROMPT.strip()
            or privacy.get("record_voice") is not False or privacy.get("retention_days") != 0
            or object_value(platform.get("auth")).get("enable_auth") is not True
            or prompt.get("knowledge_base") or prompt.get("tool_ids")
            or configuration.get("language_presets") or agent.get("procedures") or agent.get("workflow")
            or object_value(workspace.get("conversation_initiation_client_data_webhook")).get("url")
            or not hooks.get("post_call_webhook_id")
            or not {"transcript", "call_initiation_failure"}.issubset(hooks.get("events") or [])
            or not tools
            or any(not isinstance(tool, dict) or tool.get("type") != "system" or object_value(tool.get("params")).get("system_tool_type") != "end_call" for tool in tools)
        ):
            raise rejected("ELEVENLABS_AGENT_INVALID", "Use the dedicated DwellCall prompt, first message, end_call tool, signed webhook, zero retention and bounded duration; human transfers are unavailable")
        phone = self._read("/v1/convai/phone-numbers/" + quote(settings.outbound_phone_number_id or "", safe=""))
        trunk = object_value(phone.get("outbound_trunk"))
        caller = settings.outbound_from_number.get_secret_value()
        if (
            phone.get("phone_number_id") != settings.outbound_phone_number_id
            or phone.get("phone_number") != caller or caller == destination
            or caller in settings.allowed_numbers
            or phone.get("provider") != "sip_trunk"
            or trunk.get("address") != settings.outbound_telnyx_termination_host
            or trunk.get("transport") != "tls" or trunk.get("has_auth_credentials") is not True
        ):
            raise rejected("ELEVENLABS_TRUNK_INVALID", "Import the authorized Telnyx caller with TLS and outbound SIP credentials into ElevenLabs")

    def dial(self, data: CallInput, call_id: str, request_hash: str) -> RetellCall:
        try:
            response = self._request("POST", "/v1/convai/sip-trunk/outbound-call", {
                "agent_id": self.settings.outbound_agent_id,
                "agent_phone_number_id": self.settings.outbound_phone_number_id,
                "to_number": data.phone_number,
                "telephony_call_config": {"ringing_timeout_secs": self.settings.outbound_ringing_seconds},
                "conversation_initiation_client_data": {"dynamic_variables": {
                    "dwellcall_outbound_id": call_id, "authorization": request_hash,
                    "demo_scenario": data.scenario, "call_purpose": data.call_purpose,
                    "transcript_analysis_enabled": self.settings.outbound_intelligence_enabled,
                    "qualification_criteria": self.settings.outbound_qualification_criteria or "Explore explicit platform needs and interest.", "demo_transfer_enabled": False,
                    "demo_max_duration_seconds": self.settings.outbound_max_duration_seconds,
                }},
            })
        except httpx.HTTPError:
            raise OutboundProviderError("ELEVENLABS_DIAL_UNCERTAIN", "The outcome is unknown; reconcile without redialing", outcome_unknown=True) from None
        if response.status_code not in {200, 201}:
            raise OutboundProviderError("ELEVENLABS_DIAL_REJECTED", "ElevenLabs did not return a successful call receipt", outcome_unknown=response.status_code not in {400, 401, 403, 404, 422, 429})
        try:
            value = object_value(response.json())
            conversation_id, sip_id = value.get("conversation_id"), value.get("sip_call_id")
            if value.get("success") is not True or not isinstance(sip_id, str) or not 1 <= len(sip_id) <= 512:
                raise ValueError("Invalid receipt")
            return RetellCall(call_id=conversation_id, agent_id=self.settings.outbound_agent_id, agent_version=0,
                call_type="phone_call", direction="outbound", call_status="registered",
                from_number=self.settings.outbound_from_number.get_secret_value(), to_number=data.phone_number,
                metadata={"dwellcall_outbound_id": call_id, "authorization": request_hash})
        except (ValueError, TypeError):
            raise OutboundProviderError("ELEVENLABS_RECEIPT_INVALID", "The receipt is unconfirmed; reconcile without redialing", outcome_unknown=True) from None

    def snapshot(self, data: dict[str, Any], event: str = "refresh") -> RetellCall:
        metadata = object_value(data.get("metadata"))
        phone = object_value(metadata.get("phone_call"))
        variables = object_value(object_value(data.get("conversation_initiation_client_data")).get("dynamic_variables"))
        duration = metadata.get("call_duration_secs")
        timestamp = metadata.get("start_time_unix_secs")
        status = data.get("status")
        if duration is not None and (type(duration) is not int or duration < 0):
            raise rejected("ELEVENLABS_STATUS_INVALID", "Invalid call duration")
        if timestamp is not None and (type(timestamp) is not int or timestamp < 0):
            raise rejected("ELEVENLABS_STATUS_INVALID", "Invalid call timestamp")
        reason = None
        if event == "call_initiation_failure":
            code = object_value(metadata.get("body")).get("sip_status_code")
            reason = "dial_busy" if code in {486, 600, 603} else "dial_no_answer" if code in {408, 480} else "provider_failure"
            normalized = "not_connected"
        elif status in {"done", "failed"}:
            normalized = "ended" if status == "done" else "error"
            reason = "agent_hangup" if status == "done" else "provider_failure"
        elif status in {"in-progress", "processing"}:
            normalized = "ongoing"
        elif status == "initiated":
            normalized = "registered"
        else:
            raise rejected("ELEVENLABS_STATUS_INVALID", "Unconfirmed call lifecycle")
        transcript = data.get("transcript") or []
        if not isinstance(transcript, list):
            raise rejected("ELEVENLABS_STATUS_INVALID", "Invalid call evidence")
        for turn in transcript:
            if not isinstance(turn, dict):
                raise rejected("ELEVENLABS_STATUS_INVALID", "Invalid call evidence")
            for tool in (turn.get("tool_calls") or []) + (turn.get("tool_results") or []):
                if not isinstance(tool, dict):
                    raise rejected("ELEVENLABS_STATUS_INVALID", "Invalid tool evidence")
                if tool.get("tool_name") == "transfer_to_number":
                    reason = "call_transfer"
        try:
            return RetellCall(call_id=data.get("conversation_id"), agent_id=data.get("agent_id"), agent_version=0,
                call_type="phone_call", direction=phone.get("direction"), call_status=normalized,
                from_number=phone.get("agent_number") or phone.get("agent_phone_number"), to_number=phone.get("external_number"),
                start_timestamp=timestamp * 1000 if timestamp is not None else None,
                duration_ms=duration * 1000 if duration is not None else None,
                metadata=variables, disconnection_reason=reason, transcript_object=transcript)
        except (ValueError, TypeError):
            raise rejected("ELEVENLABS_STATUS_INVALID", "Call identity or lifecycle evidence is incomplete") from None

    def retrieve(self, call_id: str) -> RetellCall:
        return self.snapshot(self._read("/v1/convai/conversations/" + quote(call_id, safe="")))

    def find(self, call_id: str, request_hash: str) -> RetellCall | None:
        raise rejected("ELEVENLABS_LOOKUP_REQUIRED", "Find the existing conversation in ElevenLabs and bind its ID; never redial an uncertain request")

    def stop(self, call_id: str) -> None:
        raise OutboundProviderError("ELEVENLABS_CARRIER_STOP_REQUIRED", "End the active SIP call in Telnyx, then reconcile or confirm all carrier legs ended", outcome_unknown=True)

    def verify_webhook(self, headers: Mapping[str, str], body: bytes) -> dict[str, Any]:
        secret = self.settings.outbound_webhook_secret
        try:
            parts: dict[str, str] = {}
            for item in headers.get("ElevenLabs-Signature", "").split(","):
                key, separator, value = item.strip().partition("=")
                if not separator or key in parts:
                    raise ValueError("Invalid signature")
                parts[key] = value
            timestamp = int(parts["t"])
            if not secret or len(body) > MAX_WEBHOOK_BYTES or abs(time.time() - timestamp) > 300:
                raise ValueError("Invalid signature")
            expected = hmac.new(secret.get_secret_value().encode(), str(timestamp).encode() + b"." + body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, parts["v0"]):
                raise ValueError("Invalid signature")
            payload = json.loads(body)
            if not isinstance(payload, dict) or object_value(payload.get("data")).get("agent_id") != self.settings.outbound_agent_id:
                raise ValueError("Invalid event")
            return payload
        except (KeyError, ValueError, TypeError, UnicodeError):
            raise rejected("ELEVENLABS_WEBHOOK_REJECTED", "Webhook verification failed") from None
