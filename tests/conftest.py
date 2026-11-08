from uuid import uuid4

import pytest

from dwellcall.settings import ApiSettings, DatabaseConnectionSettings
from dwellcall.crm.settings import CrmSettings
from dwellcall.crm.contracts import CrmExportRequest
from dwellcall.crm.schemas import ConsultationSnapshot, ExportAuthorization
from dwellcall.listings.settings import ListingSettings


@pytest.fixture(autouse=True)
def isolate_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(ApiSettings.model_config, "env_file", None)
    monkeypatch.setitem(DatabaseConnectionSettings.model_config, "env_file", None)
    monkeypatch.setitem(CrmSettings.model_config, "env_file", None)
    monkeypatch.setitem(ListingSettings.model_config, "env_file", None)
    for name in set(ApiSettings.model_fields) | set(CrmSettings.model_fields) | set(ListingSettings.model_fields):
        monkeypatch.delenv(name.upper(), raising=False)


@pytest.fixture
def settings() -> ApiSettings:
    return ApiSettings(
        _env_file=None,
        app_environment="development",
        database_url="postgresql://synthetic:synthetic@localhost/dwellcall",
        retell_agent_id="agent_dwellcall_test",
        retell_agent_version=0,
        retell_api_key="synthetic-retell-key",
        retell_websocket_secret="a" * 43,
        admin_token="b" * 43,
        llm_api_key="synthetic-llm-key",
        conversation_reserved_cost_cents=100,
        conversation_daily_budget_cents=200,
    )


@pytest.fixture
def outbound_settings(settings: ApiSettings) -> ApiSettings:
    return ApiSettings.model_validate({
        **settings.model_dump(), "outbound_enabled": True, "outbound_provider": "retell",
        "outbound_agent_id": "agent_outbound", "outbound_agent_version": 3,
        "outbound_from_number": "+12025550123",
        "outbound_allowed_numbers": "+12025550124,+12025550126",
        "outbound_hash_secret": "o" * 43,
        "outbound_sip_username": "synthetic-sip-user",
        "outbound_public_base_url": "https://api.dwellcall.test",
        "outbound_reserved_cost_cents": 100, "outbound_daily_budget_cents": 500,
        "outbound_destination_permissions_confirmed": True,
        "outbound_caller_id_confirmed": True,
    })


@pytest.fixture
def crm_settings() -> CrmSettings:
    return CrmSettings(
        _env_file=None, app_environment="test", crm_provider="followupboss",
        crm_sync_enabled=True, crm_owner_approved=True, crm_core_voice_verified=True,
        crm_automations_disabled_verified=True, crm_hash_secret="h" * 43,
        followupboss_api_key="synthetic-fub-api-key",
        followupboss_system_name="DwellCallMock", followupboss_system_key="synthetic-system-key",
    )


@pytest.fixture
def export_request(crm_settings: CrmSettings) -> CrmExportRequest:
    snapshot = ConsultationSnapshot.model_validate({
        "contact": {"first_name": "Demo", "email": "visitor@example.com"},
        "scenario": "renting", "location": "Austin, TX",
        "budget": {"amount": "2300.00", "currency": "USD", "period": "monthly"},
        "requirements": ["One bedroom", "Pets allowed"],
        "summary": "Confirmed fictional rental consultation; no appointment requested.",
    })
    return CrmExportRequest(uuid4(), crm_settings.destination, snapshot)


@pytest.fixture
def authorization(export_request: CrmExportRequest) -> ExportAuthorization:
    return ExportAuthorization(
        call_id="call_crm_mock", snapshot_version=1,
        destination=export_request.destination, snapshot=export_request.snapshot,
        business_name="DwellCall",
        details_confirmed=True, storage_permission=True, crm_permission=True,
        consent_version="dwellcall-crm-v1", permission_reference="synthetic-consent-reference",
    )


@pytest.fixture
def ghl_settings() -> CrmSettings:
    return CrmSettings(
        _env_file=None, app_environment="test", crm_provider="gohighlevel",
        crm_sync_enabled=True, crm_owner_approved=True,
        crm_automations_disabled_verified=True, crm_hash_secret="g" * 43,
        ghl_api_enabled=True, ghl_private_integration_token="synthetic-ghl-token",
        ghl_location_id="test-location",
        ghl_custom_fields={key: "field-" + key for key in ("agent_id", "revision", "properties", "brokerage", "sources")},
    )


@pytest.fixture
def hubspot_settings() -> CrmSettings:
    return CrmSettings(
        _env_file=None, app_environment="test", crm_provider="hubspot",
        crm_sync_enabled=True, crm_owner_approved=True,
        crm_automations_disabled_verified=True, crm_hash_secret="h" * 43,
        hubspot_api_enabled=True, hubspot_access_token="synthetic-hubspot-service-key",
        hubspot_portal_id="12345", hubspot_sync_interval_seconds=1,
    )
