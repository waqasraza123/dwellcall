import json
import re
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import httpx

from dwellcall.crm.contracts import AgentDeliveryResult, AgentExportRequest, DeliveryStatus
from dwellcall.crm.hubspot_mapping import brokerage_key, listing_references, owned_properties
from dwellcall.crm.job_execution import JobDeadlineExceeded, check_job_deadline, current_job_budget
from dwellcall.crm.settings import CrmSettings
from dwellcall.listings.normalization import text_key

BASE_URL = "https://api.hubapi.com"


class HubSpotFailure(Exception):
    def __init__(self, status: DeliveryStatus, code: str, delay: int = 0) -> None:
        super().__init__(code)
        self.status, self.code, self.delay = status, code, delay


def remote_id(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{1,30}", value) is None:
        raise HubSpotFailure("unknown", "HUBSPOT_RECEIPT_INVALID")
    return value


def properties(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("properties")
    if not isinstance(value, dict) or record.get("archived") is True:
        raise HubSpotFailure("failed", "HUBSPOT_RECORD_UNAVAILABLE")
    return value


def next_page(result: dict[str, Any]) -> str | None:
    paging = result.get("paging")
    if paging is None:
        return None
    if not isinstance(paging, dict):
        raise HubSpotFailure("failed", "HUBSPOT_PAGINATION_INVALID")
    following = paging.get("next")
    if following is None:
        return None
    if not isinstance(following, dict):
        raise HubSpotFailure("failed", "HUBSPOT_PAGINATION_INVALID")
    after = following.get("after")
    if after is None:
        return None
    if not str(after).isdigit():
        raise HubSpotFailure("failed", "HUBSPOT_PAGINATION_INVALID")
    return str(after)


def same_phone(first: object, second: str | None) -> bool:
    if not isinstance(first, str) or not second:
        return False
    return re.sub(r"[^0-9]", "", first) == re.sub(r"[^0-9]", "", second)


class HubSpotProvider:
    def __init__(self, settings: CrmSettings, client: httpx.Client) -> None:
        self.settings, self.client = settings, client
        self.last_request_at = 0.0
        self.portal_confirmed = False

    def close(self) -> None:
        self.client.close()

    def objects_path(self, object_type: str) -> str:
        return f"/crm/objects/{self.settings.hubspot_api_version}/{object_type}"

    def properties_path(self, object_type: str) -> str:
        return f"/crm/properties/{self.settings.hubspot_api_version}/{object_type}"

    def request(self, method: str, path: str, *, body: dict[str, Any] | None = None,
                params: dict[str, Any] | None = None, write: bool = False,
                schema_write: bool = False, step: str = "WRITE") -> dict[str, Any]:
        settings, token = self.settings, self.settings.hubspot_access_token
        if settings.crm_provider != "hubspot" or not settings.hubspot_api_enabled or not settings.crm_owner_approved or token is None:
            raise HubSpotFailure("disabled", "HUBSPOT_API_DISABLED")
        if write and not (settings.dispatch_enabled or (schema_write and path.startswith("/crm/properties/") and method == "POST" and settings.hubspot_schema_creation_enabled)):
            raise HubSpotFailure("disabled", "HUBSPOT_SYNC_DISABLED")
        if not path.startswith(("/crm/", "/account-info/")) or ".." in path or "?" in path:
            raise HubSpotFailure("failed", "HUBSPOT_PATH_INVALID")
        if write:
            self.ensure_portal()
        submitted = False
        try:
            check_job_deadline()
            wait = 1 / settings.hubspot_requests_per_second - (time.monotonic() - self.last_request_at)
            if wait > 0:
                budget = current_job_budget.get()
                if budget is not None and budget.remaining() <= wait:
                    raise HubSpotFailure("retry_wait", "HUBSPOT_NOT_SUBMITTED", 1)
                time.sleep(wait)
            check_job_deadline()
            self.last_request_at = time.monotonic()
            submitted = True
            with self.client.stream(method, BASE_URL + path, json=body, params=params, headers={
                "Authorization": "Bearer " + token.get_secret_value(), "Accept": "application/json",
            }, timeout=8, follow_redirects=False) as response:
                code = response.status_code
                if code == 429:
                    raw = response.headers.get("Retry-After", "60")
                    try:
                        delay = int(raw) if raw.isascii() and raw.isdigit() else int((parsedate_to_datetime(raw) - datetime.now(UTC)).total_seconds())
                    except (ValueError, TypeError, OverflowError):
                        delay = 60
                    raise HubSpotFailure("retry_wait", "HUBSPOT_RATE_LIMITED", max(1, min(delay, 86400)))
                if code in {400, 401, 403, 404, 409, 422}:
                    raise HubSpotFailure("failed", f"HUBSPOT_REJECTED_{code}")
                if not 200 <= code < 300:
                    raise HubSpotFailure("unknown" if write else "retry_wait", f"HUBSPOT_{step}_UNCERTAIN" if write else "HUBSPOT_READ_UNAVAILABLE", 60)
                data = bytearray()
                for chunk in response.iter_bytes():
                    check_job_deadline()
                    data.extend(chunk)
                    if len(data) > 1_048_576:
                        raise HubSpotFailure("unknown" if write else "failed", f"HUBSPOT_{step}_UNCERTAIN" if write else "HUBSPOT_RESPONSE_TOO_LARGE")
                result = json.loads(data) if data else {}
                if not isinstance(result, dict):
                    raise ValueError("Invalid response")
                return result
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise HubSpotFailure("retry_wait", "HUBSPOT_NOT_SUBMITTED", 60) from None
        except JobDeadlineExceeded:
            raise HubSpotFailure("unknown" if write and submitted else "retry_wait", f"HUBSPOT_{step}_UNCERTAIN" if write and submitted else "HUBSPOT_NOT_SUBMITTED", 60) from None
        except (httpx.HTTPError, ValueError, UnicodeError, RecursionError):
            raise HubSpotFailure("unknown" if write else "retry_wait", f"HUBSPOT_{step}_UNCERTAIN" if write else "HUBSPOT_READ_UNAVAILABLE", 60) from None

    def ensure_portal(self) -> None:
        if self.portal_confirmed:
            return
        account = self.request("GET", f"/account-info/{self.settings.hubspot_api_version}/details")
        if str(account.get("portalId", account.get("hubId", ""))) != self.settings.hubspot_portal_id:
            raise HubSpotFailure("failed", "HUBSPOT_PORTAL_MISMATCH")
        self.portal_confirmed = True

    def get_object(self, object_type: str, identifier: str, names: list[str], *, id_property: str | None = None) -> dict[str, Any] | None:
        parameters = {"properties": ",".join(names), **({"idProperty": id_property} if id_property else {})}
        try:
            record = self.request("GET", self.objects_path(object_type) + "/" + quote(identifier, safe=""), params=parameters)
        except HubSpotFailure as error:
            if error.code == "HUBSPOT_REJECTED_404":
                return None
            raise
        remote_id(record.get("id"))
        properties(record)
        return record

    def get_contact(self, contact_id: str, fields: dict[str, str]) -> dict[str, Any]:
        names = [name for key, name in fields.items() if not key.startswith(("company_", "deal_"))] + ["firstname", "lastname", "email", "phone", "mobilephone"]
        record = self.get_object("contacts", remote_id(contact_id), names)
        if record is None:
            raise HubSpotFailure("failed", "HUBSPOT_CONTACT_UNAVAILABLE")
        return record

    def search(self, object_type: str, body: dict[str, Any]) -> list[dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        after: str | None = None
        seen: set[str] = set()
        for _ in range(self.settings.hubspot_max_lookup_pages):
            result = self.request("POST", self.objects_path(object_type) + "/search", body={**body, "limit": 100, **({"after": after} if after else {})})
            rows = result.get("results")
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise HubSpotFailure("failed", "HUBSPOT_SEARCH_INVALID")
            for row in rows:
                found[remote_id(row.get("id"))] = row
            next_value = next_page(result)
            if next_value is None:
                total = result.get("total")
                if isinstance(total, int) and total > len(found):
                    raise HubSpotFailure("failed", "HUBSPOT_LOOKUP_INCOMPLETE")
                return list(found.values())
            after = str(next_value)
            if not after.isdigit() or after in seen:
                break
            seen.add(after)
        raise HubSpotFailure("failed", "HUBSPOT_LOOKUP_INCOMPLETE")

    def marker_contact(self, request: AgentExportRequest) -> dict[str, Any] | None:
        return self.get_object("contacts", str(request.snapshot.agent_id), [name for key, name in request.fields.items() if not key.startswith(("company_", "deal_"))] + ["email", "phone", "mobilephone"], id_property=request.fields["agent_id"])

    def lookup(self, request: AgentExportRequest) -> dict[str, Any] | None:
        matches: dict[str, dict[str, Any]] = {}
        owned = self.marker_contact(request)
        if owned:
            matches[remote_id(owned["id"])] = owned
        snapshot = request.snapshot
        queries: list[dict[str, Any]] = []
        if snapshot.email:
            queries.append({"filterGroups": [{"filters": [{"propertyName": "email", "operator": "EQ", "value": snapshot.email}]}]})
        national_phone: str | None = None
        if snapshot.phone:
            digits = snapshot.phone.removeprefix("+")
            national_phone = next((digits[len(code):] for code in self.settings.hubspot_phone_calling_codes if digits.startswith(code)), None)
            if national_phone is None and owned is None:
                raise HubSpotFailure("failed", "HUBSPOT_PHONE_REGION_NOT_CONFIGURED")
            if national_phone:
                queries.append({"query": national_phone})
        for query in queries:
            for row in self.search("contacts", {**query, "properties": ["email", "phone", "mobilephone", request.fields["agent_id"]]}):
                values = properties(row)
                reliable = (snapshot.email and str(values.get("email", "")).casefold() == snapshot.email.casefold()) or same_phone(values.get("phone"), snapshot.phone) or same_phone(values.get("mobilephone"), snapshot.phone)
                if reliable:
                    matches[remote_id(row["id"])] = row
                elif national_phone and any(re.sub(r"[^0-9]", "", str(values.get(name) or "")) == national_phone for name in ("phone", "mobilephone")):
                    raise HubSpotFailure("failed", "HUBSPOT_CONTACT_COUNTRY_AMBIGUOUS")
        if len(matches) > 1:
            raise HubSpotFailure("failed", "HUBSPOT_CONFLICTING_CONTACT_MATCHES")
        if not matches:
            return None
        contact = self.get_contact(next(iter(matches)), request.fields)
        if properties(contact).get(request.fields["agent_id"]) != str(snapshot.agent_id):
            raise HubSpotFailure("failed", "HUBSPOT_CONTACT_REVIEW_REQUIRED")
        return contact

    def company(self, request: AgentExportRequest, *, reconcile: bool = False) -> str | None:
        brokerage = request.snapshot.brokerage
        if not brokerage:
            return request.company_id
        marker = request.fields["company_key"]
        mapped = self.settings.hubspot_company_mappings.get(text_key(brokerage))
        if mapped:
            record = self.get_object("companies", remote_id(mapped), ["name", marker])
            if record is None:
                raise HubSpotFailure("failed", "HUBSPOT_COMPANY_MAPPING_UNAVAILABLE")
            return remote_id(record["id"])
        key = brokerage_key(brokerage)
        record = self.get_object("companies", key, ["name", marker, request.fields["company_name"]], id_property=marker)
        if record:
            if properties(record).get(marker) != key:
                raise HubSpotFailure("failed", "HUBSPOT_COMPANY_MARKER_CONFLICT")
            if not reconcile and properties(record).get(request.fields["company_name"]) != brokerage:
                self.request("PATCH", self.objects_path("companies") + "/" + remote_id(record["id"]), body={"properties": {request.fields["company_name"]: brokerage}}, write=True, step="COMPANY_UPDATE")
            return remote_id(record["id"])
        if reconcile:
            raise HubSpotFailure("unknown", "HUBSPOT_COMPANY_NOT_CONFIRMED")
        candidates = self.search("companies", {"filterGroups": [{"filters": [{"propertyName": "name", "operator": "EQ", "value": brokerage}]}], "properties": ["name", marker]})
        if candidates:
            raise HubSpotFailure("failed", "HUBSPOT_COMPANY_REVIEW_REQUIRED")
        created = self.request("POST", self.objects_path("companies"), body={"properties": {"name": brokerage, marker: key, request.fields["company_name"]: brokerage}}, write=True, step="COMPANY_CREATE")
        return remote_id(created.get("id"))

    def qualified(self, request: AgentExportRequest) -> bool:
        return self.settings.hubspot_deals_enabled and len({item.listing_id for item in request.snapshot.properties if item.status in self.settings.hubspot_qualifying_statuses}) >= self.settings.hubspot_qualified_min_listings

    def deal(self, request: AgentExportRequest, *, reconcile: bool = False) -> str | None:
        if not self.qualified(request):
            return request.opportunity_id
        marker = request.fields["deal_key"]
        record = self.get_object("deals", str(request.snapshot.agent_id), [marker, "pipeline", "dealstage", request.fields["deal_listings"]], id_property=marker)
        if record:
            if properties(record).get("pipeline") != self.settings.hubspot_pipeline_id:
                raise HubSpotFailure("failed", "HUBSPOT_DEAL_PIPELINE_CONFLICT")
            if not reconcile:
                self.request("PATCH", self.objects_path("deals") + "/" + remote_id(record["id"]), body={"properties": {request.fields["deal_listings"]: listing_references(request)}}, write=True, step="DEAL_UPDATE")
            return remote_id(record["id"])
        if request.opportunity_id or reconcile:
            raise HubSpotFailure("unknown", "HUBSPOT_DEAL_NOT_CONFIRMED")
        created = self.request("POST", self.objects_path("deals"), body={"properties": {
            "dealname": "DwellCall · " + request.snapshot.full_name, "pipeline": self.settings.hubspot_pipeline_id,
            "dealstage": self.settings.hubspot_stage_id, marker: str(request.snapshot.agent_id),
            request.fields["deal_listings"]: listing_references(request),
        }}, write=True, step="DEAL_CREATE")
        return remote_id(created.get("id"))

    def associated(self, from_type: str, from_id: str, to_type: str, to_id: str) -> bool:
        after: str | None = None
        seen: set[str] = set()
        for _ in range(self.settings.hubspot_max_lookup_pages):
            result = self.request("GET", self.objects_path(from_type) + f"/{remote_id(from_id)}/associations/{to_type}", params={"limit": 100, **({"after": after} if after else {})})
            rows = result.get("results")
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise HubSpotFailure("failed", "HUBSPOT_ASSOCIATIONS_INVALID")
            if any(str(row.get("toObjectId", row.get("id"))) == to_id for row in rows if isinstance(row, dict)):
                return True
            value = next_page(result)
            if value is None:
                return False
            after = str(value)
            if not after.isdigit() or after in seen:
                break
            seen.add(after)
        raise HubSpotFailure("unknown", "HUBSPOT_ASSOCIATION_LOOKUP_INCOMPLETE")

    def associate(self, from_type: str, from_id: str, to_type: str, to_id: str) -> None:
        if not self.associated(from_type, from_id, to_type, to_id):
            self.request("PUT", self.objects_path(from_type) + f"/{remote_id(from_id)}/associations/default/{to_type}/{remote_id(to_id)}", write=True, step="ASSOCIATION_WRITE")

    def send_agent(self, request: AgentExportRequest) -> AgentDeliveryResult:
        if self.settings.crm_provider != "hubspot" or not self.settings.dispatch_enabled:
            return AgentDeliveryResult("disabled", "HUBSPOT_SYNC_DISABLED")
        contact_id, company_id, deal_id = request.contact_id, request.company_id, request.opportunity_id
        try:
            self.ensure_portal()
            if request.destination != self.settings.destination or self.settings.required_agent_fields - request.fields.keys():
                raise HubSpotFailure("failed", "HUBSPOT_DESTINATION_OR_FIELDS_CHANGED")
            values = owned_properties(request, self.settings.hubspot_lead_source, self.settings.hubspot_classifications)
            contact = self.get_contact(contact_id, request.fields) if contact_id else self.lookup(request)
            if contact is None:
                first, _, last = request.snapshot.full_name.partition(" ")
                initial = {**values, "firstname": first, **({"lastname": last} if last else {}),
                           **({"email": request.snapshot.email} if request.snapshot.email else {}),
                           **({"phone": request.snapshot.phone} if request.snapshot.phone else {})}
                contact = self.request("POST", self.objects_path("contacts"), body={"properties": initial}, write=True, step="CONTACT_CREATE")
                contact_id = remote_id(contact.get("id"))
            else:
                contact_id = remote_id(contact.get("id"))
                marker = properties(contact).get(request.fields["agent_id"])
                if marker not in (None, "", str(request.snapshot.agent_id)):
                    raise HubSpotFailure("failed", "HUBSPOT_IDENTITY_MARKER_CONFLICT")
                if marker in (None, "") and not ((request.snapshot.email and str(properties(contact).get("email", "")).casefold() == request.snapshot.email.casefold()) or same_phone(properties(contact).get("phone"), request.snapshot.phone) or same_phone(properties(contact).get("mobilephone"), request.snapshot.phone)):
                    raise HubSpotFailure("failed", "HUBSPOT_CONTACT_EVIDENCE_MISMATCH")
                # Standard human-entered fields and lifecycle/pipeline values are never patched.
                self.request("PATCH", self.objects_path("contacts") + "/" + contact_id, body={"properties": values}, write=True, step="CONTACT_UPDATE")
            company_id = self.company(request)
            if company_id:
                self.associate("contacts", contact_id, "companies", company_id)
            deal_id = self.deal(request)
            if self.settings.hubspot_deals_enabled and deal_id:
                self.associate("deals", deal_id, "contacts", contact_id)
                if company_id:
                    self.associate("deals", deal_id, "companies", company_id)
            self.request("PATCH", self.objects_path("contacts") + "/" + contact_id, body={"properties": {request.fields["revision"]: request.fingerprint}}, write=True, step="CONTACT_REVISION")
            return AgentDeliveryResult("sent", "HUBSPOT_DELIVERED", contact_id, deal_id, company_id=company_id)
        except HubSpotFailure as error:
            return AgentDeliveryResult(error.status, error.code, contact_id, deal_id, error.delay, company_id)
        except (ValueError, KeyError):
            return AgentDeliveryResult("failed", "HUBSPOT_MAPPING_INVALID", contact_id, deal_id, company_id=company_id)

    def reconcile_agent(self, request: AgentExportRequest) -> AgentDeliveryResult:
        contact_id, company_id, deal_id = request.contact_id, request.company_id, request.opportunity_id
        try:
            self.ensure_portal()
            contact = self.get_contact(contact_id, request.fields) if contact_id else self.marker_contact(request)
            if contact is None or properties(contact).get(request.fields["agent_id"]) != str(request.snapshot.agent_id):
                raise HubSpotFailure("unknown", "HUBSPOT_CONTACT_NOT_CONFIRMED")
            contact_id = remote_id(contact["id"])
            if request.uncertain_code in {"HUBSPOT_CONTACT_CREATE_UNCERTAIN", "HUBSPOT_CONTACT_UPDATE_UNCERTAIN"}:
                return AgentDeliveryResult("retry_wait", "HUBSPOT_CONTACT_CONFIRMED_RETRY_UPDATE", contact_id, deal_id, 1, company_id)
            company_id = self.company(request, reconcile=True)
            if request.uncertain_code in {"HUBSPOT_COMPANY_CREATE_UNCERTAIN", "HUBSPOT_ASSOCIATION_WRITE_UNCERTAIN"} and not deal_id:
                return AgentDeliveryResult("retry_wait", "HUBSPOT_CONTACT_CONFIRMED_RETRY_UPDATE", contact_id, deal_id, 1, company_id)
            deal_id = self.deal(request, reconcile=True)
            associations = (not company_id or self.associated("contacts", contact_id, "companies", company_id)) and (not self.settings.hubspot_deals_enabled or not deal_id or (self.associated("deals", deal_id, "contacts", contact_id) and (not company_id or self.associated("deals", deal_id, "companies", company_id))))
            if properties(contact).get(request.fields["revision"]) == request.fingerprint and associations:
                return AgentDeliveryResult("sent", "HUBSPOT_RECONCILED", contact_id, deal_id, company_id=company_id)
            return AgentDeliveryResult("retry_wait", "HUBSPOT_CONTACT_CONFIRMED_RETRY_UPDATE", contact_id, deal_id, 1, company_id)
        except HubSpotFailure as error:
            return AgentDeliveryResult("unknown", error.code, contact_id, deal_id, error.delay, company_id)
