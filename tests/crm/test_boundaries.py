from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.engine import Engine

from dwellcall.application import create_app
from dwellcall.crm.jobs import process_crm_jobs
from dwellcall.crm.schemas import ExportAuthorization
from dwellcall.crm.settings import CrmSettings
from dwellcall.settings import ApiSettings


def test_none_needs_no_credentials_database_work_or_routes(settings: ApiSettings) -> None:
    configuration = CrmSettings(_env_file=None, app_environment="test")
    sessions = Mock(side_effect=AssertionError("Disabled CRM accessed database"))
    assert process_crm_jobs(sessions, configuration).status == "disabled"
    app = create_app(settings, Mock(spec=Engine), configuration)
    with TestClient(app) as client:
        assert client.get("/api/v1/crm/admin/destination").status_code == 404


@pytest.mark.parametrize("field", ["details_confirmed", "storage_permission", "crm_permission"])
@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_permission_must_be_separate_explicit_true(
    authorization: ExportAuthorization, field: str, value: object,
) -> None:
    payload = authorization.model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError):
        ExportAuthorization.model_validate(payload)


@pytest.mark.parametrize("field", [
    "crm_owner_approved", "crm_core_voice_verified", "crm_automations_disabled_verified",
])
def test_enabled_sync_requires_every_owner_gate(crm_settings: CrmSettings, field: str) -> None:
    values = crm_settings.model_dump()
    values[field] = False
    with pytest.raises(ValidationError):
        CrmSettings.model_validate(values)


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CrmSettings(_env_file=None, app_environment="test", crm_provider="other")


@pytest.mark.parametrize("field", [
    "followupboss_api_key", "followupboss_system_name", "followupboss_system_key",
    "crm_hash_secret",
])
def test_selected_provider_requires_registered_credentials(
    crm_settings: CrmSettings, field: str,
) -> None:
    values = crm_settings.model_dump()
    values[field] = None
    with pytest.raises(ValidationError):
        CrmSettings.model_validate(values)


def test_fictional_flag_and_field_allowlist_cannot_be_overridden(
    authorization: ExportAuthorization,
) -> None:
    payload = authorization.model_dump(mode="json")
    payload["snapshot"]["fictional_properties"] = False
    with pytest.raises(ValidationError):
        ExportAuthorization.model_validate(payload)
    payload = authorization.model_dump(mode="json")
    payload["snapshot"]["campaign"] = {"name": "unrelated"}
    with pytest.raises(ValidationError):
        ExportAuthorization.model_validate(payload)


def test_authentication_runs_before_crm_body_parsing_or_database(
    settings: ApiSettings, crm_settings: CrmSettings,
) -> None:
    engine = Mock(spec=Engine)
    app = create_app(settings, engine, crm_settings)
    with TestClient(app) as client:
        response = client.post("/api/v1/crm/admin/exports", content="not-json")
    assert response.status_code == 401
    engine.connect.assert_not_called()


def test_consent_errors_do_not_echo_personal_input(
    settings: ApiSettings, crm_settings: CrmSettings,
) -> None:
    app = create_app(settings, Mock(spec=Engine), crm_settings)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/crm/admin/exports",
            headers={"X-Admin-Token": "b" * 43},
            json={"snapshot": {"contact": {"email": "private-value"}}},
        )
    assert response.status_code == 422
    assert "private-value" not in response.text
