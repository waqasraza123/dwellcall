import pytest

from dwellcall.settings import ApiSettings, DatabaseConnectionSettings


@pytest.fixture(autouse=True)
def isolate_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(ApiSettings.model_config, "env_file", None)
    monkeypatch.setitem(DatabaseConnectionSettings.model_config, "env_file", None)
    for name in ApiSettings.model_fields:
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
