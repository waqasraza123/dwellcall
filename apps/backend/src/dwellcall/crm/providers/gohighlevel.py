import json
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import httpx

from dwellcall.crm.contracts import AgentDeliveryResult, AgentExportRequest, DeliveryStatus
from dwellcall.crm.settings import CrmSettings

BASE_URL = "https://services.leadconnectorhq.com"
API_VERSION = "2021-07-28"
FIELD_DEFINITIONS = {
    "agent_id": ("DwellCall Agent ID", "TEXT"),
    "revision": ("DwellCall Revision", "TEXT"),
    "properties": ("DwellCall Properties", "LARGE_TEXT"),
    "brokerage": ("DwellCall Brokerage", "TEXT"),
    "sources": ("DwellCall Sources", "LARGE_TEXT"),
}


class GhlFailure(Exception):
    def __init__(self, status: DeliveryStatus, code: str, delay: int = 0) -> None:
        super().__init__(code)
        self.status, self.code, self.delay = status, code, delay


def remote_id(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is None:
        raise GhlFailure("unknown", "GHL_RECEIPT_INVALID")
    return value


def field_values(contact: dict[str, Any]) -> dict[str, object]:
    fields = contact.get("customFields", [])
    if not isinstance(fields, list):
        raise GhlFailure("unknown", "GHL_RECEIPT_INVALID")
    return {str(item["id"]): item.get("value", item.get("field_value")) for item in fields if isinstance(item, dict) and "id" in item}


def owned_fields(request: AgentExportRequest) -> list[dict[str, str]]:
    snapshot = request.snapshot
    values = {
        "agent_id": str(snapshot.agent_id),
        "properties": json.dumps([item.model_dump(mode="json") for item in snapshot.properties], sort_keys=True, separators=(",", ":")),
        "sources": json.dumps(snapshot.contact_references, sort_keys=True, separators=(",", ":")),
        "brokerage": snapshot.brokerage or "",
    }
    if any(len(value.encode()) > 50000 for value in values.values()):
        raise GhlFailure("failed", "GHL_FIELD_CAPACITY_EXCEEDED")
    return [{"id": request.fields[key], "field_value": value} for key, value in values.items()]


class GoHighLevelProvider:
    def __init__(self, settings: CrmSettings, client: httpx.Client) -> None:
        self.settings, self.client = settings, client

    def close(self) -> None:
        self.client.close()

    def request(self, method: str, path: str, *, body: dict[str, Any] | None = None,
                params: dict[str, Any] | None = None, write: bool = False,
                agency: bool = False) -> dict[str, Any]:
        token = self.settings.ghl_agency_token if agency else self.settings.ghl_private_integration_token
        if self.settings.crm_provider != "gohighlevel" or not self.settings.ghl_api_enabled or not self.settings.crm_owner_approved or token is None:
            raise GhlFailure("disabled", "GHL_API_DISABLED")
        try:
            with self.client.stream(method, BASE_URL + path, json=body, params=params, headers={
                "Authorization": "Bearer " + token.get_secret_value(),
                "Version": API_VERSION, "Accept": "application/json",
            }, timeout=8, follow_redirects=False) as response:
                code = response.status_code
                if code == 429:
                    value = response.headers.get("Retry-After", "60")
                    try:
                        delay = int(value) if value.isascii() and value.isdigit() else int((parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
                    except (ValueError, TypeError, OverflowError):
                        delay = 60
                    raise GhlFailure("retry_wait", "GHL_RATE_LIMITED", max(1, min(delay, 86400)))
                if code in {400, 401, 403, 404, 409, 422}:
                    raise GhlFailure("failed", f"GHL_REJECTED_{code}")
                if not 200 <= code < 300:
                    raise GhlFailure("unknown" if write else "retry_wait", "GHL_WRITE_UNCERTAIN" if write else "GHL_READ_UNAVAILABLE", 60)
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 1048576:
                        raise GhlFailure("unknown" if write else "failed", "GHL_RESPONSE_TOO_LARGE")
                result = json.loads(data) if data else {}
                if not isinstance(result, dict):
                    raise ValueError("Invalid response")
                return result
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise GhlFailure("retry_wait", "GHL_NOT_SUBMITTED", 60) from None
        except (httpx.HTTPError, ValueError, UnicodeError, RecursionError):
            raise GhlFailure("unknown" if write else "retry_wait", "GHL_WRITE_UNCERTAIN" if write else "GHL_READ_UNAVAILABLE", 60) from None

    def get_contact(self, contact_id: str) -> dict[str, Any]:
        contact = self.request("GET", "/contacts/" + quote(remote_id(contact_id), safe="" )).get("contact")
        if not isinstance(contact, dict) or contact.get("locationId") != self.settings.ghl_location_id:
            raise GhlFailure("failed", "GHL_CONTACT_LOCATION_MISMATCH")
        remote_id(contact.get("id"))
        return contact

    def search(self, field: str, value: str) -> list[dict[str, Any]]:
        result = self.request("POST", "/contacts/search", body={
            "locationId": self.settings.ghl_location_id, "page": 1, "pageLimit": 2,
            "filters": [{"field": field, "operator": "eq", "value": value}],
        })
        contacts = result.get("contacts")
        total = result.get("total", len(contacts) if isinstance(contacts, list) else 0)
        if not isinstance(contacts, list) or not isinstance(total, int) or total > 1 or len(contacts) > 1:
            raise GhlFailure("failed", "GHL_MULTIPLE_CONTACT_MATCHES")
        if any(not isinstance(contact, dict) for contact in contacts):
            raise GhlFailure("failed", "GHL_RECEIPT_INVALID")
        return contacts

    def lookup(self, request: AgentExportRequest, *, marker_only: bool = False) -> dict[str, Any] | None:
        matches: dict[str, dict[str, Any]] = {}
        searches = [("customFields." + request.fields["agent_id"], str(request.snapshot.agent_id))]
        if not marker_only:
            searches += [(field, value) for field, value in (("email", request.snapshot.email), ("phone", request.snapshot.phone)) if value]
        for field, value in searches:
            for contact in self.search(field, value):
                identifier = remote_id(contact.get("id"))
                matches[identifier] = contact
        if len(matches) > 1:
            raise GhlFailure("failed", "GHL_CONFLICTING_CONTACT_MATCHES")
        if not matches:
            return None
        contact = self.get_contact(next(iter(matches)))
        if field_values(contact).get(request.fields["agent_id"]) != str(request.snapshot.agent_id):
            raise GhlFailure("failed", "GHL_CONTACT_REVIEW_REQUIRED")
        return contact

    def opportunity(self, request: AgentExportRequest, contact_id: str, *, reconcile: bool = False) -> str | None:
        settings = self.settings
        if not settings.ghl_opportunities_enabled or len({item.listing_id for item in request.snapshot.properties if item.status in settings.ghl_qualifying_statuses}) < settings.ghl_qualified_min_listings:
            return request.opportunity_id
        name = "DwellCall " + str(request.snapshot.agent_id)
        result = self.request("GET", "/opportunities/search", params={
            "location_id": settings.ghl_location_id, "contact_id": contact_id,
            "pipeline_id": settings.ghl_pipeline_id, "limit": 100,
        })
        opportunities = result.get("opportunities")
        if not isinstance(opportunities, list) or len(opportunities) >= 100:
            raise GhlFailure("unknown", "GHL_OPPORTUNITY_SEARCH_INCOMPLETE")
        matches = [item for item in opportunities if item.get("name") == name and item.get("contactId") == contact_id and item.get("pipelineId") == settings.ghl_pipeline_id]
        if len(matches) > 1:
            raise GhlFailure("unknown", "GHL_MULTIPLE_OPPORTUNITIES")
        if matches:
            return remote_id(matches[0].get("id"))
        if request.opportunity_id or reconcile:
            raise GhlFailure("unknown", "GHL_OPPORTUNITY_UNCERTAIN")
        created = self.request("POST", "/opportunities/", body={
            "locationId": settings.ghl_location_id, "pipelineId": settings.ghl_pipeline_id,
            "pipelineStageId": settings.ghl_pipeline_stage_id, "contactId": contact_id,
            "name": name, "status": "open",
        }, write=True)
        return remote_id(created.get("opportunity", {}).get("id"))

    def send_agent(self, request: AgentExportRequest) -> AgentDeliveryResult:
        if not self.settings.dispatch_enabled:
            return AgentDeliveryResult("disabled", "GHL_SYNC_DISABLED")
        contact_id, opportunity_id = request.contact_id, request.opportunity_id
        try:
            if request.destination != self.settings.destination:
                raise GhlFailure("failed", "GHL_DESTINATION_CHANGED")
            if set(FIELD_DEFINITIONS) - request.fields.keys():
                raise GhlFailure("failed", "GHL_FIELD_MAPPING_REQUIRED")
            contact = self.get_contact(contact_id) if contact_id else self.lookup(request)
            if contact is None:
                payload: dict[str, Any] = {
                    "locationId": self.settings.ghl_location_id, "name": request.snapshot.full_name,
                    "source": self.settings.ghl_lead_source, "customFields": owned_fields(request),
                }
                if request.snapshot.email:
                    payload["email"] = request.snapshot.email
                if request.snapshot.phone:
                    payload["phone"] = request.snapshot.phone
                created = self.request("POST", "/contacts/", body=payload, write=True)
                contact_id = remote_id(created.get("contact", {}).get("id"))
                contact = self.get_contact(contact_id)
            else:
                contact_id = remote_id(contact.get("id"))
            marker = field_values(contact).get(request.fields["agent_id"])
            if marker not in (None, "", str(request.snapshot.agent_id)):
                raise GhlFailure("failed", "GHL_IDENTITY_MARKER_CONFLICT")
            payload = {"customFields": owned_fields(request)}
            for name, value in (("name", request.snapshot.full_name), ("email", request.snapshot.email),
                                ("phone", request.snapshot.phone), ("source", self.settings.ghl_lead_source)):
                if name == "name" and any(contact.get(key) for key in ("name", "firstName", "lastName")):
                    continue
                if not contact.get(name) and value:
                    payload[name] = value
            self.request("PUT", "/contacts/" + contact_id, body=payload, write=True)
            if self.settings.ghl_tags:
                self.request("POST", "/contacts/" + contact_id + "/tags", body={"tags": list(self.settings.ghl_tags)}, write=True)
            opportunity_id = self.opportunity(request, contact_id)
            self.request("PUT", "/contacts/" + contact_id, body={
                "customFields": [{"id": request.fields["revision"], "field_value": request.fingerprint}],
            }, write=True)
            return AgentDeliveryResult("sent", "GHL_DELIVERED", contact_id, opportunity_id)
        except GhlFailure as error:
            return AgentDeliveryResult(error.status, error.code, contact_id, opportunity_id, error.delay)

    def reconcile_agent(self, request: AgentExportRequest) -> AgentDeliveryResult:
        contact_id, opportunity_id = request.contact_id, request.opportunity_id
        try:
            contact = self.get_contact(contact_id) if contact_id else self.lookup(request, marker_only=True)
            if contact is None:
                raise GhlFailure("unknown", "GHL_CONTACT_NOT_CONFIRMED")
            contact_id = remote_id(contact.get("id"))
            values = field_values(contact)
            if values.get(request.fields["agent_id"]) != str(request.snapshot.agent_id):
                raise GhlFailure("unknown", "GHL_IDENTITY_NOT_CONFIRMED")
            opportunity_id = self.opportunity(request, contact_id, reconcile=True)
            if values.get(request.fields["revision"]) == request.fingerprint:
                return AgentDeliveryResult("sent", "GHL_RECONCILED", contact_id, opportunity_id)
            return AgentDeliveryResult("retry_wait", "GHL_CONTACT_CONFIRMED_RETRY_UPDATE", contact_id, opportunity_id, 1)
        except GhlFailure as error:
            return AgentDeliveryResult("unknown", error.code, contact_id, opportunity_id, error.delay)
