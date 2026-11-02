import pytest
from pydantic import ValidationError

from dwellcall.settings import ApiSettings


@pytest.mark.parametrize("updates", [
    {"retell_api_key": None}, {"retell_agent_version": None},
    {"admin_token": None}, {"retell_websocket_secret": None},
    {"conversation_reserved_cost_cents": 0},
    {"conversation_daily_budget_cents": 50},
    {"retell_websocket_secret": "b" * 43},
    {"retell_websocket_secret": "/" * 43},
    {"conversation_max_duration_seconds": 181},
])
def test_private_audio_requires_identity_limits_and_separate_secrets(
    settings: ApiSettings, updates: dict[str, object],
) -> None:
    values = settings.model_dump()
    with pytest.raises(ValidationError):
        ApiSettings.model_validate({**values, "retell_test_audio_enabled": True, **updates})
