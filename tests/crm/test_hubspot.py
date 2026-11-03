import json
from dataclasses import replace
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest

from dwellcall.crm.agent_schemas import AgentContactSnapshot, AgentProperty
from dwellcall.crm.contracts import AgentExportRequest
from dwellcall.crm.hubspot_mapping import FIELDS, brokerage_key, owned_properties
from dwellcall.crm.providers.hubspot import HubSpotProvider


@pytest.fixture(autouse=True)
def no_rate_limit_sleep(monkeypatch):
    monkeypatch.setattr("dwellcall.crm.providers.hubspot.time.sleep", lambda _: None)


@pytest.fixture
def hubspot_request(hubspot_settings):
    return AgentExportRequest(uuid4(), hubspot_settings.destination, AgentContactSnapshot(
        agent_id=uuid4(), full_name="Fictional Agent", brokerage="Fictional Brokerage",
        email="agent@example.com", phone="+15125550101", last_discovered_at=datetime.now(UTC),
        properties=[AgentProperty(listing_id=uuid4(), source_key="mock-authorized", source_listing_id=str(index),
                                  listing_url=f"https://example.com/property/{index}", street_address=f"{index} Fictional Way",
                                  city="Austin", state="TX", postal_code="78701", status="active", permission_version=1)
                    for index in (1, 2)],
        contact_references=[{"source_key": "mock-authorized", "source_reference": "mock-business-contact", "permission_version": 1}],
    ), "revision-one", hubspot_settings.agent_fields)


class HubSpotServer:
    def __init__(self):
        self.records = {kind: {} for kind in ("contacts", "companies", "deals")}
        self.associations = set()
        self.calls = []
        self.created = {kind: 0 for kind in self.records}
        self.custom_properties = {}

    def __call__(self, request):
        assert request.headers["Authorization"] == "Bearer synthetic-hubspot-service-key"
        assert request.url.host == "api.hubapi.com"
        body = json.loads(request.content) if request.content else {}
        path, method = request.url.path, request.method
        self.calls.append((method, path, body))
        if path.startswith("/account-info/"):
            return httpx.Response(200, json={"portalId": 12345})
        parts = path.split("/")
        if path.startswith("/crm/properties/"):
            kind = parts[4]
            if method == "POST":
                self.custom_properties[(kind, body["name"])] = body
                return httpx.Response(201, json=body)
            if len(parts) == 6:
                item = self.custom_properties.get((kind, parts[5]))
                return httpx.Response(200 if item else 404, json=item or {})
            return httpx.Response(200, json={"results": [value for (object_type, _), value in self.custom_properties.items() if object_type == kind]})
        if path.startswith("/crm/pipelines/"):
            return httpx.Response(200, json={"id": "pipeline", "stages": [{"id": "stage"}]})
        assert path.startswith("/crm/objects/2026-09/")
        kind = parts[4]
        if len(parts) >= 8 and parts[6] == "associations":
            source_id = parts[5]
            if method == "GET":
                to_type = parts[7]
                return httpx.Response(200, json={"results": [{"toObjectId": int(to_id)} for from_kind, from_id, target, to_id in self.associations if (from_kind, from_id, target) == (kind, source_id, to_type)]})
            assert parts[7] == "default"
            self.associations.add((kind, source_id, parts[8], parts[9]))
            return httpx.Response(200, json={})
        if len(parts) == 6 and parts[5] == "search":
            rows = list(self.records[kind].values())
            if "query" in body:
                rows = [row for row in rows if str(body["query"]) in ''.join(c for c in str(row["properties"].get("phone", "")) if c.isdigit())]
            else:
                filters = body.get("filterGroups", [{}])[0].get("filters", [])
                rows = [row for row in rows if all(str(row["properties"].get(f["propertyName"], "")).casefold() == str(f["value"]).casefold() for f in filters)]
            return httpx.Response(200, json={"results": rows, "total": len(rows)})
        if len(parts) == 5:
            if method == "GET":
                return httpx.Response(200, json={"results": list(self.records[kind].values())[:1]})
            props = body["properties"]
            marker = {"contacts": "dwellcall_agent_id", "companies": "dwellcall_company_key", "deals": "dwellcall_deal_key"}[kind]
            if any(row["properties"].get(marker) == props.get(marker) for row in self.records[kind].values()):
                return httpx.Response(409, json={})
            self.created[kind] += 1
            identifier = str({"contacts": 100, "companies": 200, "deals": 300}[kind] + self.created[kind])
            record = {"id": identifier, "properties": dict(props), "archived": False}
            self.records[kind][identifier] = record
            return httpx.Response(201, json=record)
        identifier = parts[5]
        key = request.url.params.get("idProperty")
        record = next((row for row in self.records[kind].values() if row["properties"].get(key) == identifier), None) if key else self.records[kind].get(identifier)
        if record is None:
            return httpx.Response(404, json={})
        if method == "PATCH":
            assert all(name.startswith("dwellcall_") for name in body["properties"])
            record["properties"].update(body["properties"])
        return httpx.Response(200, json=record)


def adapter(settings, server):
    return HubSpotProvider(settings, httpx.Client(transport=httpx.MockTransport(server)))


def test_contact_company_mapping_multiple_listings_and_idempotent_replay(hubspot_settings, hubspot_request):
    server = HubSpotServer()
    provider = adapter(hubspot_settings, server)
    first = provider.send_agent(hubspot_request)
    second = provider.send_agent(hubspot_request)
    assert first.status == second.status == "sent"
    assert server.created == {"contacts": 1, "companies": 1, "deals": 0}
    assert ("contacts", first.contact_id, "companies", first.company_id) in server.associations
    contact = server.records["contacts"][first.contact_id]["properties"]
    assert contact["dwellcall_listing_count"] == "2"
    assert len(json.loads(contact["dwellcall_listing_references"])) == 2
    assert "Austin" in contact["dwellcall_property_locations"]
    assert contact["dwellcall_lead_source"] == "DwellCall"
    assert contact["dwellcall_revision"] == hubspot_request.fingerprint


def test_mapped_contact_preserves_human_values_and_unrelated_properties(hubspot_settings, hubspot_request):
    server = HubSpotServer()
    server.records["contacts"]["99"] = {"id": "99", "properties": {"firstname": "Human", "lastname": "Name", "email": "owner@example.com", "phone": "+15125550999", "notes": "Owner notes", "dwellcall_agent_id": str(hubspot_request.snapshot.agent_id), "lifecycle_stage": "customer"}}
    result = adapter(hubspot_settings, server).send_agent(replace(hubspot_request, contact_id="99"))
    assert result.status == "sent"
    values = server.records["contacts"]["99"]["properties"]
    assert values["firstname"] == "Human"
    assert values["email"] == "owner@example.com"
    assert values["notes"] == "Owner notes"
    assert values["dwellcall_verified_email"] == hubspot_request.snapshot.email


def test_unowned_email_match_requires_explicit_binding(hubspot_settings, hubspot_request):
    server = HubSpotServer()
    server.records["contacts"]["99"] = {"id": "99", "properties": {"email": hubspot_request.snapshot.email}}
    result = adapter(hubspot_settings, server).send_agent(hubspot_request)
    assert result.code == "HUBSPOT_CONTACT_REVIEW_REQUIRED"
    assert not any(method in {"PATCH", "PUT"} or (method == "POST" and not path.endswith("search")) for method, path, _ in server.calls)


def test_existing_company_name_is_not_silently_claimed(hubspot_settings, hubspot_request):
    server = HubSpotServer()
    server.records["companies"]["77"] = {"id": "77", "properties": {"name": "Fictional Brokerage"}}
    result = adapter(hubspot_settings, server).send_agent(hubspot_request)
    assert result.code == "HUBSPOT_COMPANY_REVIEW_REQUIRED"
    configured = hubspot_settings.model_copy(update={"hubspot_company_mappings": {"fictional brokerage": "77"}})
    result = adapter(configured, server).send_agent(replace(hubspot_request, contact_id=result.contact_id))
    assert result.status == "sent"
    assert result.company_id == "77"
    assert server.records["companies"]["77"]["properties"] == {"name": "Fictional Brokerage"}


@pytest.mark.parametrize("status,expected", [(401,"failed"),(403,"failed"),(429,"retry_wait"),(503,"unknown")])
def test_write_errors_do_not_echo_credentials_or_remote_payload(hubspot_settings, hubspot_request, status, expected):
    server = HubSpotServer()
    def handler(request):
        if request.method == "POST" and request.url.path.endswith("/contacts"):
            return httpx.Response(status, headers={"Retry-After":"120"}, json={"message":"private provider payload"})
        return server(request)
    result = adapter(hubspot_settings, handler).send_agent(hubspot_request)
    assert result.status == expected
    assert "private provider" not in repr(result)
    assert "synthetic-hubspot" not in repr(result)
    if status == 429:
        assert result.retry_after_seconds == 120


def test_unknown_contact_create_is_looked_up_before_restarting_unattempted_steps(hubspot_settings, hubspot_request):
    server = HubSpotServer()
    def handler(request):
        response = server(request)
        if request.method == "POST" and request.url.path.endswith("/contacts"):
            raise httpx.ReadTimeout("lost mock receipt", request=request)
        return response
    provider = adapter(hubspot_settings, handler)
    result = provider.send_agent(hubspot_request)
    assert result.status == "unknown"
    recovered = provider.reconcile_agent(replace(hubspot_request, uncertain_code=result.code))
    assert recovered.status == "retry_wait"
    assert recovered.contact_id == "101"
    assert provider.send_agent(replace(hubspot_request, contact_id=recovered.contact_id)).status == "sent"
    assert server.created["contacts"] == 1


def test_empty_lookup_never_proves_unknown_create_failed(hubspot_settings, hubspot_request):
    server = HubSpotServer()
    result = adapter(hubspot_settings, server).reconcile_agent(hubspot_request)
    assert result.status == "unknown"
    assert server.created == {"contacts": 0, "companies": 0, "deals": 0}


def test_optional_deal_created_once_and_human_stage_is_preserved(hubspot_settings, hubspot_request):
    settings = hubspot_settings.model_copy(update={"hubspot_deals_enabled": True, "hubspot_pipeline_id": "pipeline", "hubspot_stage_id": "stage"})
    request = replace(hubspot_request, fields=settings.agent_fields)
    server = HubSpotServer()
    provider = adapter(settings, server)
    first = provider.send_agent(request)
    assert first.opportunity_id
    server.records["deals"][first.opportunity_id]["properties"]["dealstage"] = "human-stage"
    second = provider.send_agent(replace(request, contact_id=first.contact_id, opportunity_id=first.opportunity_id, company_id=first.company_id))
    assert second.status == "sent"
    assert server.created["deals"] == 1
    assert server.records["deals"][first.opportunity_id]["properties"]["dealstage"] == "human-stage"
    assert ("deals", first.opportunity_id, "contacts", first.contact_id) in server.associations


def test_contact_create_does_not_invent_email_for_phone_only_agent(hubspot_settings, hubspot_request):
    request = replace(hubspot_request, snapshot=hubspot_request.snapshot.model_copy(update={"email": None}))
    server = HubSpotServer()
    result = adapter(hubspot_settings, server).send_agent(request)
    assert result.status == "sent"
    assert "email" not in server.records["contacts"][result.contact_id]["properties"]


def test_disabled_provider_never_calls_http(hubspot_settings, hubspot_request):
    forbidden = Mock(side_effect=AssertionError("HTTP was not authorized"))
    settings = hubspot_settings.model_copy(update={"crm_sync_enabled": False})
    assert adapter(settings, forbidden).send_agent(hubspot_request).status == "disabled"
    forbidden.assert_not_called()


def test_wrong_account_is_rejected_before_any_write(hubspot_settings, hubspot_request):
    calls = []
    def handler(request):
        calls.append(request.method)
        return httpx.Response(200, json={"portalId": 999})
    assert adapter(hubspot_settings, handler).send_agent(hubspot_request).code == "HUBSPOT_PORTAL_MISMATCH"
    assert calls == ["GET"]


def test_search_pages_are_followed_and_bounded(hubspot_settings):
    calls = []
    def handler(request):
        body = json.loads(request.content); calls.append(body.get("after"))
        return httpx.Response(200, json={"results": [{"id": "1" if "after" not in body else "2", "properties": {}}], **({"paging": {"next": {"after": "100"}}} if "after" not in body else {})})
    assert len(adapter(hubspot_settings, handler).search("contacts", {})) == 2
    assert calls == [None, "100"]


def test_bundled_synthetic_data_can_be_demonstrated_only_through_mock_transport(hubspot_settings):
    document = json.loads((Path(__file__).resolve().parents[2] / "data/listings/synthetic-listings.json").read_text())
    listing = deepcopy(document["listings"][0])
    agent = listing["agents"][0]
    snapshot = AgentContactSnapshot(agent_id=uuid4(), full_name=agent["full_name"], brokerage=agent.get("brokerage"), email=next((item["value"] for item in agent.get("contacts", []) if item["kind"] == "business_email"), None), phone=next((item["value"] for item in agent.get("contacts", []) if item["kind"] == "direct_business_phone"), None), properties=[AgentProperty(listing_id=uuid4(), source_key="synthetic-files", source_listing_id=listing["source_listing_id"], listing_url=listing.get("listing_url"), status="active", permission_version=1)], contact_references=[])
    request = AgentExportRequest(uuid4(), hubspot_settings.destination, snapshot, "mock-only", hubspot_settings.agent_fields)
    server = HubSpotServer()
    assert adapter(hubspot_settings, server).send_agent(request).status == "sent"
    assert document["synthetic"] is True


def test_custom_mapping_keeps_complete_multiple_listing_references_in_owned_properties(hubspot_settings, hubspot_request):
    overrides = {"listing_references": "dwellcall_property_refs", "full_name": "dwellcall_exact_name"}
    fields = {**hubspot_settings.agent_fields, **overrides}
    mapped = owned_properties(replace(hubspot_request, fields=fields), "DwellCall", ("Listing Agent",))
    assert mapped["dwellcall_exact_name"] == "Fictional Agent"
    assert len(json.loads(mapped["dwellcall_property_refs"])) == 2
    assert "email" not in mapped and "phone" not in mapped
    assert brokerage_key(" Fictional  Brokerage ") == brokerage_key("fictional brokerage")
    assert FIELDS["agent_id"].unique is True


def test_read_failure_and_connection_failure_are_safe_without_mutations(hubspot_settings, hubspot_request):
    def handler(request):
        raise httpx.ConnectError("mock connection unavailable", request=request)
    result = adapter(hubspot_settings, handler).send_agent(hubspot_request)
    assert result.status == "retry_wait"
    assert result.code == "HUBSPOT_NOT_SUBMITTED"


def test_company_creation_timeout_needs_company_lookup_before_retry(hubspot_settings, hubspot_request):
    server = HubSpotServer()
    def handler(request):
        response = server(request)
        if request.method == "POST" and request.url.path.endswith("/companies"):
            raise httpx.ReadTimeout("mock company receipt lost", request=request)
        return response
    provider = adapter(hubspot_settings, handler)
    result = provider.send_agent(hubspot_request)
    assert result.status == "unknown"
    reconciled = provider.reconcile_agent(replace(hubspot_request, contact_id=result.contact_id, uncertain_code=result.code))
    assert reconciled.company_id == "201"
    assert reconciled.status == "retry_wait"
    assert provider.send_agent(replace(hubspot_request, contact_id=reconciled.contact_id, company_id=reconciled.company_id)).status == "sent"
    assert server.created["companies"] == 1


def test_split_email_and_phone_matches_never_merge_agents(hubspot_settings, hubspot_request):
    server = HubSpotServer()
    server.records["contacts"]["91"] = {"id":"91", "properties":{"email":hubspot_request.snapshot.email}}
    server.records["contacts"]["92"] = {"id":"92", "properties":{"phone":hubspot_request.snapshot.phone}}
    result = adapter(hubspot_settings, server).send_agent(hubspot_request)
    assert result.code == "HUBSPOT_CONFLICTING_CONTACT_MATCHES"
    assert server.created["contacts"] == 0


def test_owned_company_updates_preserve_human_company_name(hubspot_settings, hubspot_request):
    server = HubSpotServer()
    provider = adapter(hubspot_settings, server)
    first = provider.send_agent(hubspot_request)
    company = server.records["companies"][first.company_id]["properties"]
    company["name"] = "Human company name"
    company["dwellcall_company_name"] = "Old DwellCall value"
    assert provider.send_agent(replace(hubspot_request, contact_id=first.contact_id, company_id=first.company_id)).status == "sent"
    assert company["name"] == "Human company name"
    assert company["dwellcall_company_name"] == hubspot_request.snapshot.brokerage


def test_lost_deal_receipt_is_reconciled_without_duplicate_deal(hubspot_settings, hubspot_request):
    settings = hubspot_settings.model_copy(update={"hubspot_deals_enabled":True,"hubspot_pipeline_id":"pipeline","hubspot_stage_id":"stage"})
    request = replace(hubspot_request, fields=settings.agent_fields)
    server = HubSpotServer()
    def handler(message):
        response = server(message)
        if message.method == "POST" and message.url.path.endswith("/deals"):
            raise httpx.ReadTimeout("mock lost deal receipt", request=message)
        return response
    provider = adapter(settings, handler)
    first = provider.send_agent(request)
    assert first.status == "unknown"
    confirmed = provider.reconcile_agent(replace(request, contact_id=first.contact_id, company_id=first.company_id, uncertain_code=first.code))
    assert confirmed.opportunity_id == "301"
    assert confirmed.status == "retry_wait"
    final = provider.send_agent(replace(request, contact_id=confirmed.contact_id, company_id=confirmed.company_id, opportunity_id=confirmed.opportunity_id))
    assert final.status == "sent"
    assert server.created["deals"] == 1


def test_phone_search_uses_national_digits_and_checks_full_returned_number(hubspot_settings, hubspot_request):
    server = HubSpotServer()
    server.records["contacts"]["99"] = {"id":"99", "properties":{"phone":"+1 (512) 555-0101"}}
    result = adapter(hubspot_settings, server).send_agent(hubspot_request)
    assert result.code == "HUBSPOT_CONTACT_REVIEW_REQUIRED"
    queries = [body["query"] for _, path, body in server.calls if path.endswith("/contacts/search") and "query" in body]
    assert queries == ["5125550101"]
    assert server.created["contacts"] == 0


def test_local_phone_without_country_evidence_cannot_authorize_merge_or_creation(hubspot_settings, hubspot_request):
    server = HubSpotServer()
    server.records["contacts"]["99"] = {"id":"99", "properties":{"phone":"(512) 555-0101"}}
    result = adapter(hubspot_settings, server).send_agent(hubspot_request)
    assert result.code == "HUBSPOT_CONTACT_COUNTRY_AMBIGUOUS"
    assert server.created["contacts"] == 0
