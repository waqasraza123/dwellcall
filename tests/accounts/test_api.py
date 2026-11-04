from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.engine import Engine

from dwellcall.account_access import routes
from dwellcall.account_access.schemas import MfaChallengeResponse
from dwellcall.application import create_app
from dwellcall.settings import ApiSettings


def test_portal_gate_and_mfa_challenge_without_database_or_provider_calls(monkeypatch: pytest.MonkeyPatch, settings: ApiSettings) -> None:
    access = Mock()
    access.login.return_value = MfaChallengeResponse(next_action="verify", challenge_token="x" * 43, expires_in=600)
    monkeypatch.setattr(routes, "AccountAccessService", Mock(return_value=access))
    configuration = settings.model_copy(update={"account_auth_enabled": True, "account_portal_secret": SecretStr("p" * 43)})
    app = create_app(configuration, Mock(spec=Engine))
    with TestClient(app) as client:
        assert client.post("/api/v1/account/auth/login", json={"email": "demo@example.com", "password": "synthetic password"}).status_code == 404
        access.login.assert_not_called()
        response = client.post("/api/v1/account/auth/login", headers={"X-Account-Portal-Key": "p" * 43}, json={"email": "demo@example.com", "password": "synthetic password"})
        assert response.status_code == 200
        assert response.json()["mfa_required"] is True
        assert "session_token" not in response.json()
        assert response.headers["cache-control"] == "no-store"
        response = client.post("/api/v1/account/auth/signup", headers={"X-Account-Portal-Key": "p" * 43}, json={"email": "demo@example.com", "password": "synthetic password", "full_name": "Demo", "operator_access": True})
        assert response.status_code == 422
        access.signup.assert_not_called()
        response = client.post("/api/v1/account/auth/login", headers={"X-Account-Portal-Key": "p" * 43}, content=b"x" * 4097)
        assert response.status_code == 413
