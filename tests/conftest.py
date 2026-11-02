from uuid import uuid4

import pytest

from dwellcall.settings import ApiSettings, DatabaseConnectionSettings
from dwellcall.crm.settings import CrmSettings
from dwellcall.crm.contracts import CrmExportRequest
from dwellcall.crm.schemas import ConsultationSnapshot, ExportAuthorization


@pytest.fixture(autouse=True)
def isolate_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(ApiSettings.model_config, "env_file", None)
    monkeypatch.setitem(DatabaseConnectionSettings.model_config, "env_file", None)
    monkeypatch.setitem(CrmSettings.model_config, "env_file", None)
    for name in set(ApiSettings.model_fields) | set(CrmSettings.model_fields):
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
