from urllib.parse import quote, urlsplit

import httpx
from pydantic import ValidationError

from dwellcall.settings import ApiSettings
from dwellcall.telephony.outbound.schemas import CallInput
from dwellcall.telephony.retell.schemas import RetellCall


class OutboundProviderError(RuntimeError):
    def __init__(self, code: str, message: str, *, outcome_unknown: bool) -> None:
        super().__init__(message)
        self.code = code
        self.outcome_unknown = outcome_unknown


def rejected(code: str, message: str) -> OutboundProviderError:
    return OutboundProviderError(code, message, outcome_unknown=False)


class RetellOutboundProvider:
    """HVACLine outbound preflight/receipt pattern with Retell as sole originator."""

    def __init__(self, settings: ApiSettings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.client = client

    def _request(self, method: str, path: str, payload: dict[str, object] | None = None) -> httpx.Response:
        key = self.settings.retell_api_key
        if key is None:
            raise rejected("RETELL_CREDENTIALS_MISSING", "Configure the dedicated DwellCall Retell API key")
        client = self.client or httpx.Client(
            base_url="https://api.retellai.com", timeout=12,
            trust_env=False, follow_redirects=False,
        )
        try:
            return client.request(method, path, headers={"Authorization": "Bearer " + key.get_secret_value()}, json=payload)
        finally:
            if self.client is None:
                client.close()

    def _read(self, path: str) -> dict[str, object]:
        try:
            response = self._request("GET", path)
            response.raise_for_status()
            result: object = response.json()
            if not isinstance(result, dict):
                raise ValueError("Invalid provider object")
            return result
        except (httpx.HTTPError, ValueError, TypeError):
            raise rejected("RETELL_PREFLIGHT_UNAVAILABLE", "Retell could not confirm configuration; check API access and provider availability") from None

    def preflight(self, destination: str | None = None) -> None:
        try:
            self._preflight(destination)
        except (ValueError, TypeError, OverflowError):
            raise rejected("RETELL_CONFIGURATION_INVALID", "Retell returned malformed configuration; inspect the imported number and published agent before calling") from None

    def _preflight(self, destination: str | None) -> None:
        settings = self.settings
        caller = settings.outbound_from_number.get_secret_value()
        if destination == caller:
            raise rejected("CALLER_ID_LOOP", "The caller number cannot also be the recipient")
        phone = self._read("/get-phone-number/" + quote(caller, safe=""))
        trunk = phone.get("sip_outbound_trunk_config")
        if not isinstance(trunk, dict):
            raise rejected("TELNYX_TRUNK_MISSING", "Import the authorized Telnyx number with outbound SIP credentials into Retell")
        uri = trunk.get("termination_uri")
        host = urlsplit("sip://" + str(uri).removeprefix("sip:").removeprefix("//")).hostname
        if (
            phone.get("phone_number") != caller or phone.get("phone_number_type") != "custom"
            or host != settings.outbound_telnyx_termination_host
            or trunk.get("auth_username") != settings.outbound_sip_username.get_secret_value()
            or trunk.get("transport") not in {"TCP", "TLS"}
        ):
            raise rejected("TELNYX_TRUNK_INVALID", "Check the imported caller number, Telnyx termination host, username and TCP/TLS transport")
        permitted = phone.get("allowed_outbound_country_list")
        if not isinstance(permitted, list) or any(not isinstance(value, str) for value in permitted) or not settings.outbound_allowed_countries.issubset(permitted):
            raise rejected("RETELL_DESTINATIONS_INVALID", "Authorize the configured destination countries on the imported Retell number")
        agent = self._read("/get-agent/" + quote(settings.outbound_agent_id or "", safe="") + "?version=" + str(settings.outbound_agent_version))
        engine = agent.get("response_engine")
        duration = agent.get("max_call_duration_ms")
        ringing = agent.get("ring_duration_ms")
        secret = settings.retell_websocket_secret
        expected_socket = (settings.outbound_public_base_url or "").replace("https://", "wss://", 1) + "/api/v1/retell/llm/" + (secret.get_secret_value() if secret else "")
        if (
            agent.get("agent_id") != settings.outbound_agent_id
            or agent.get("version") != settings.outbound_agent_version
            or agent.get("is_published") is not True
            or not isinstance(engine, dict) or engine.get("type") != "custom-llm"
            or engine.get("llm_websocket_url") != expected_socket
            or type(duration) is not int or not 60000 <= duration <= settings.outbound_max_duration_seconds * 1000
            or type(ringing) is not int or not 10000 <= ringing <= settings.outbound_ringing_seconds * 1000
        ):
            raise rejected("RETELL_AGENT_INVALID", "Publish the pinned Custom LLM agent with this backend's WebSocket URL and bounded call/ringing durations")
        memory = agent.get("contact_memory_config")
        retention = agent.get("data_storage_retention_days")
        if (
            agent.get("data_storage_setting") != "basic_attributes_only"
            or type(retention) is not int
            or not 1 <= retention <= settings.outbound_retention_days
            or agent.get("enable_dnc_detection") is not True
            or (isinstance(memory, dict) and (memory.get("enable_update") is True or memory.get("enable_read") is True))
            or agent.get("pre_session_tools") or agent.get("post_session_tools")
        ):
            raise rejected("RETELL_PRIVACY_INVALID", "Disable recordings/transcript storage, contact memory and session tools; configure retention and DNC detection")
        events = agent.get("webhook_events")
        if agent.get("webhook_url") != (settings.outbound_public_base_url or "") + "/api/v1/retell/webhook" or not isinstance(events, list) or not {"call_started", "call_ended", "call_analyzed"}.issubset(events):
            raise rejected("RETELL_WEBHOOK_INVALID", "Configure the signed DwellCall Retell webhook and all three lifecycle events")

    def dial(self, data: CallInput, call_id: str, request_hash: str) -> RetellCall:
        try:
            response = self._request("POST", "/v2/create-phone-call", {
                "from_number": self.settings.outbound_from_number.get_secret_value(),
                "to_number": data.phone_number,
                "override_agent_id": self.settings.outbound_agent_id,
                "override_agent_version": self.settings.outbound_agent_version,
                "idempotency_key": "dwellcall-" + str(data.request_id),
                "metadata": {"dwellcall_outbound_id": call_id, "authorization": request_hash},
                "custom_sip_headers": {"X-Telnyx-Username": self.settings.outbound_sip_username.get_secret_value()},
                "honor_internal_dnc": True,
                "ignore_e164_validation": False,
            })
        except httpx.HTTPError:
            raise OutboundProviderError("RETELL_DIAL_UNCERTAIN", "The provider outcome is unconfirmed; reconcile this request without redialing", outcome_unknown=True) from None
        if response.status_code not in {200, 201}:
            safe_rejection = response.status_code in {400, 401, 403, 404, 422, 429}
            raise OutboundProviderError("RETELL_DIAL_REJECTED" if safe_rejection else "RETELL_DIAL_UNCERTAIN", "Retell rejected the request; check credentials, agent, trunk permissions and quota" if safe_rejection else "Retell did not return a reliable receipt; reconcile without redialing", outcome_unknown=not safe_rejection)
        try:
            return RetellCall.model_validate(response.json())
        except (ValidationError, ValueError, TypeError):
            raise OutboundProviderError("RETELL_RECEIPT_INVALID", "The provider receipt is unconfirmed; retain the reservation and reconcile", outcome_unknown=True) from None

    def retrieve(self, call_id: str) -> RetellCall:
        try:
            return RetellCall.model_validate(self._read("/v2/get-call/" + quote(call_id, safe="")))
        except ValidationError:
            raise rejected("RETELL_STATUS_INVALID", "The provider returned invalid call identity or lifecycle evidence") from None

    def find(self, call_id: str, request_hash: str) -> RetellCall | None:
        try:
            response = self._request("POST", "/v3/list-calls", {
                "filter_criteria": {"metadata": [{"type": "string", "key": "dwellcall_outbound_id", "value": call_id}]},
                "limit": 2, "sort_order": "descending",
            })
            response.raise_for_status()
            result = response.json()
            items = result.get("items") if isinstance(result, dict) else None
            if not isinstance(items, list) or result.get("has_more") is not False:
                raise ValueError("Unbounded or invalid lookup")
            if not items:
                return None
            if len(items) != 1:
                raise ValueError("Ambiguous call identity")
            call = RetellCall.model_validate(items[0])
            if not call.metadata or call.metadata.get("authorization") != request_hash:
                raise ValueError("Mismatched authorization")
            return call
        except (httpx.HTTPError, ValueError, TypeError):
            raise rejected("RETELL_LOOKUP_UNAVAILABLE", "Provider lookup is incomplete or ambiguous; investigate and bind the existing call, never redial") from None

    def stop(self, call_id: str) -> None:
        try:
            response = self._request("POST", "/v2/stop-call/" + quote(call_id, safe=""))
            response.raise_for_status()
        except httpx.HTTPError:
            raise OutboundProviderError("RETELL_STOP_UNCERTAIN", "Stopping is unconfirmed; verify all carrier legs before releasing this reservation", outcome_unknown=True) from None
