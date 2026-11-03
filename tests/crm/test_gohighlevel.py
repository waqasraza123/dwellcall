import json
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest

from dwellcall.crm.agent_schemas import AgentContactSnapshot, AgentProperty
from dwellcall.crm.contracts import AgentExportRequest
from dwellcall.crm.providers.gohighlevel import GoHighLevelProvider, owned_fields
from dwellcall.crm.settings import CrmSettings


@pytest.fixture
def agent_request(ghl_settings):
    return AgentExportRequest(uuid4(), ghl_settings.destination, AgentContactSnapshot(
        agent_id=uuid4(), full_name="Fictional Agent", brokerage="Fictional Office",
        email="agent@example.com", phone="+15125550101",
        properties=[AgentProperty(listing_id=uuid4(), source_key="authorized-test", source_listing_id=str(index),
                                  listing_url=f"https://example.com/property/{index}", status="active", permission_version=1)
                    for index in (1, 2)],
        contact_references=[{"source_key": "authorized-test", "source_reference": "fictional-directory", "permission_version": 1}],
    ), "revision-1", ghl_settings.ghl_custom_fields)


class GhlServer:
    def __init__(self, request, *, existing=False):
        self.request = request
        self.calls = []
        self.created = 0
        self.contact = {"id": "contact-1", "locationId": "test-location", "customFields": [],
                        "firstName": "Owner-entered", "lastName": "Name", "email": "owner@example.com",
                        "phone": "+15125550999", "source": "Existing source", "notes": "Owner notes"} if existing else None
        self.opportunities = []

    def __call__(self, request):
        body = json.loads(request.content) if request.content else {}
        self.calls.append((request.method, request.url.path, body))
        assert request.headers["Version"] == "2021-07-28"
        assert request.headers["Authorization"] == "Bearer synthetic-ghl-token"
        path = request.url.path
        if path == "/contacts/search":
            matching = []
            if self.contact and body.get("filters", [{}])[0].get("field", "").startswith("customFields."):
                marker = next((item.get("value") for item in self.contact["customFields"] if item["id"] == "field-agent_id"), None)
                if marker == str(self.request.snapshot.agent_id):
                    matching = [self.contact]
            return httpx.Response(200, json={"contacts": matching, "total": len(matching)})
        if path == "/contacts/" and request.method == "POST":
            self.created += 1
            self.contact = {"id": "contact-1", **body, "customFields": []}
            self.merge(body)
            return httpx.Response(201, json={"contact": self.contact})
        if path == "/contacts/contact-1":
            if request.method == "PUT":
                self.merge(body)
            return httpx.Response(200, json={"contact": self.contact})
        if path == "/contacts/contact-1/tags":
            return httpx.Response(201, json={"tags": ["Owner tag", *body["tags"]]})
        if path == "/opportunities/search":
            return httpx.Response(200, json={"opportunities": self.opportunities})
        if path == "/opportunities/":
            self.opportunities.append({"id": "opportunity-1", **body})
            return httpx.Response(201, json={"opportunity": self.opportunities[0]})
        raise AssertionError("Unexpected mocked route")

    def merge(self, body):
        fields = {item["id"]: item for item in self.contact.get("customFields", [])}
        for item in body.get("customFields", []):
            fields[item["id"]] = {"id": item["id"], "value": item["field_value"]}
        self.contact.update({key: value for key, value in body.items() if key != "customFields"})
        self.contact["customFields"] = list(fields.values())


def test_contact_mapping_associates_multiple_properties_and_replays_without_creation(ghl_settings, agent_request):
    server = GhlServer(agent_request)
    provider = GoHighLevelProvider(ghl_settings, httpx.Client(transport=httpx.MockTransport(server)))
    assert provider.send_agent(agent_request).status == "sent"
    assert provider.send_agent(agent_request).status == "sent"
    assert server.created == 1
    fields = {item["id"]: item["field_value"] for item in owned_fields(agent_request)}
    assert len(json.loads(fields["field-properties"])) == 2
    assert "https://example.com/property/1" in fields["field-properties"]
    assert fields["field-agent_id"] == str(agent_request.snapshot.agent_id)
    assert any(path.endswith("/tags") and body["tags"] == ["DwellCall", "Listing Agent"] for _, path, body in server.calls)


def test_existing_mapped_contact_preserves_manual_fields_notes_and_unrelated_fields(ghl_settings, agent_request):
    server = GhlServer(agent_request, existing=True)
    server.contact["customFields"] = [{"id": "unrelated", "value": "owner value"}]
    provider = GoHighLevelProvider(ghl_settings, httpx.Client(transport=httpx.MockTransport(server)))
    assert provider.send_agent(replace(agent_request, contact_id="contact-1")).status == "sent"
    assert server.created == 0
    assert server.contact["firstName"] == "Owner-entered"
    assert server.contact["email"] == "owner@example.com"
    assert server.contact["source"] == "Existing source"
    assert server.contact["notes"] == "Owner notes"
    assert {"id": "unrelated", "value": "owner value"} in server.contact["customFields"]
    assert all(not ({"name", "email", "phone", "notes", "source", "tags"} & body.keys()) for method, path, body in server.calls if method == "PUT")


@pytest.mark.parametrize("status, expected", [(429, "retry_wait"), (401, "failed"), (403, "failed"), (503, "unknown")])
def test_write_failures_are_classified_without_echoing_provider_data(ghl_settings, agent_request, status, expected):
    server = GhlServer(agent_request, existing=True)

    def handler(request):
        if request.method == "PUT":
            return httpx.Response(status, headers={"Retry-After": "120"}, json={"message": "sensitive-provider-payload"})
        return server(request)

    result = GoHighLevelProvider(ghl_settings, httpx.Client(transport=httpx.MockTransport(handler))).send_agent(replace(agent_request, contact_id="contact-1"))
    assert result.status == expected
    assert "sensitive" not in repr(result)
    if status == 429:
        assert result.retry_after_seconds == 120


def test_ambiguous_create_is_reconciled_before_retry_and_does_not_create_twice(ghl_settings, agent_request):
    server = GhlServer(agent_request)

    def handler(request):
        response = server(request)
        if request.method == "POST" and request.url.path == "/contacts/":
            raise httpx.ReadTimeout("synthetic lost receipt", request=request)
        return response

    provider = GoHighLevelProvider(ghl_settings, httpx.Client(transport=httpx.MockTransport(handler)))
    assert provider.send_agent(agent_request).status == "unknown"
    confirmed = provider.reconcile_agent(agent_request)
    assert confirmed.status == "retry_wait"
    assert confirmed.contact_id == "contact-1"
    assert provider.send_agent(replace(agent_request, contact_id=confirmed.contact_id)).status == "sent"
    assert server.created == 1


def test_no_lookup_result_does_not_prove_an_uncertain_create_was_absent(ghl_settings, agent_request):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"contacts": [], "total": 0})

    result = GoHighLevelProvider(ghl_settings, httpx.Client(transport=httpx.MockTransport(handler))).reconcile_agent(agent_request)
    assert result.status == "unknown"
    assert calls == ["/contacts/search"]


def test_split_email_phone_matches_are_never_upserted_or_merged(ghl_settings, agent_request):
    def handler(request):
        body = json.loads(request.content)
        field = body["filters"][0]["field"]
        return httpx.Response(200, json={"contacts": [] if field.startswith("customFields.") else [{"id": "email-owner" if field == "email" else "phone-owner"}], "total": 0 if field.startswith("customFields.") else 1})

    result = GoHighLevelProvider(ghl_settings, httpx.Client(transport=httpx.MockTransport(handler))).send_agent(agent_request)
    assert result.status == "failed"
    assert result.code == "GHL_CONFLICTING_CONTACT_MATCHES"


def test_optional_opportunity_is_created_once_and_preserved(ghl_settings, agent_request):
    settings = ghl_settings.model_copy(update={"ghl_opportunities_enabled": True, "ghl_pipeline_id": "pipeline-1", "ghl_pipeline_stage_id": "stage-1"})
    server = GhlServer(agent_request)
    provider = GoHighLevelProvider(settings, httpx.Client(transport=httpx.MockTransport(server)))
    result = provider.send_agent(agent_request)
    assert result.opportunity_id == "opportunity-1"
    assert provider.reconcile_agent(replace(agent_request, contact_id=result.contact_id)).status == "sent"
    assert len(server.opportunities) == 1


def test_disabled_ghl_does_not_contact_provider(ghl_settings, agent_request):
    def forbidden(request):
        raise AssertionError("Disabled provider made HTTP call")

    settings = ghl_settings.model_copy(update={"crm_sync_enabled": False})
    assert GoHighLevelProvider(settings, httpx.Client(transport=httpx.MockTransport(forbidden))).send_agent(agent_request).status == "disabled"
    assert CrmSettings(_env_file=None).dispatch_enabled is False


def test_unowned_existing_contact_requires_operator_binding(ghl_settings, agent_request):
    writes = []

    def handler(request):
        if request.url.path == "/contacts/search":
            return httpx.Response(200, json={"contacts": [{"id": "existing"}], "total": 1})
        if request.method != "GET":
            writes.append(request.url.path)
        return httpx.Response(200, json={"contact": {"id": "existing", "locationId": "test-location", "customFields": []}})

    result = GoHighLevelProvider(ghl_settings, httpx.Client(transport=httpx.MockTransport(handler))).send_agent(agent_request)
    assert result.code == "GHL_CONTACT_REVIEW_REQUIRED"
    assert writes == []


def test_connection_failure_before_submission_is_retryable(ghl_settings, agent_request):
    def handler(request):
        raise httpx.ConnectError("synthetic connection failure", request=request)

    result = GoHighLevelProvider(ghl_settings, httpx.Client(transport=httpx.MockTransport(handler))).send_agent(agent_request)
    assert result.status == "retry_wait"
    assert result.code == "GHL_NOT_SUBMITTED"
