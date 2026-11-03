import asyncio
from unittest.mock import Mock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy.engine import Engine

from dwellcall.application import create_app
from dwellcall.crm.hubspot_setup import HubSpotPropertyCreation, HubSpotSetupInput
from dwellcall.crm.settings import CrmSettings


def test_hubspot_requires_admin_before_body_or_database(settings, hubspot_settings):
    engine = Mock(spec=Engine)
    app = create_app(settings, engine, hubspot_settings)
    async def request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return [await client.get("/api/v1/crm/hubspot/status"), await client.post("/api/v1/crm/hubspot/setup", content=b"private"), await client.post("/api/v1/crm/hubspot/properties/create", content=b"private"), await client.post("/api/v1/crm/hubspot/agents/queue", content=b"private")]
    with patch("dwellcall.crm.agent_routes.bounded_body") as body:
        responses = asyncio.run(request())
    assert all(row.status_code == 401 for row in responses)
    body.assert_not_called()
    engine.connect.assert_not_called()


def test_disabled_hubspot_status_has_no_credentials_or_provider_calls(settings):
    engine = Mock(spec=Engine)
    app = create_app(settings, engine)
    async def request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get("/api/v1/crm/hubspot/status", headers={"X-Admin-Token":settings.admin_token.get_secret_value()})
    with patch("dwellcall.crm.providers.hubspot.HubSpotProvider.request") as remote:
        response = asyncio.run(request())
    assert response.status_code == 200
    assert response.json()["selected"] is False
    assert response.json()["credentials_configured"] is False
    assert response.headers["Cache-Control"] == "no-store"
    remote.assert_not_called()
    engine.connect.assert_not_called()


def test_provider_routing_cannot_dispatch_hubspot_through_ghl_action(settings, hubspot_settings):
    app = create_app(settings, Mock(spec=Engine), hubspot_settings)
    async def request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/api/v1/crm/ghl/jobs/process", headers={"X-Admin-Token":settings.admin_token.get_secret_value()})
    with patch("dwellcall.crm.agent_routes.process_agent_jobs") as worker:
        response = asyncio.run(request())
    assert response.status_code == 409
    worker.assert_not_called()


def test_read_only_validation_never_creates_schema(settings, hubspot_settings):
    app = create_app(settings, Mock(spec=Engine), hubspot_settings)
    async def request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/api/v1/crm/hubspot/setup", headers={"X-Admin-Token":settings.admin_token.get_secret_value()}, json={"evidence_reference":"mock-read-only"})
    with patch("dwellcall.crm.hubspot_setup.HubSpotConfigurationService.setup", return_value={"configured":False}) as setup, patch("dwellcall.crm.hubspot_setup.HubSpotConfigurationService.create_properties") as create:
        response = asyncio.run(request())
    assert response.status_code == 200
    assert setup.call_args.args[0].evidence_reference == "mock-read-only"
    create.assert_not_called()


@pytest.mark.parametrize("approval", [False, "true", 1])
def test_schema_creation_requires_literal_operator_approval(approval):
    with pytest.raises(ValidationError):
        HubSpotPropertyCreation(evidence_reference="mock-case", approve_external_creation=approval)


def test_mapping_cannot_claim_standard_human_entered_fields():
    with pytest.raises(ValidationError):
        HubSpotSetupInput(evidence_reference="mock-case", custom_fields={"full_name":"firstname"})
    with pytest.raises(ValidationError):
        HubSpotSetupInput(evidence_reference="mock-case", custom_fields={"agent_id":"dwellcall_same", "revision":"dwellcall_same"})


def test_hubspot_defaults_do_not_activate_live_writes():
    settings = CrmSettings(_env_file=None, crm_provider="hubspot")
    assert settings.dispatch_enabled is False
    assert settings.hubspot_schema_creation_enabled is False
    assert settings.hubspot_token_type == "service_key"
