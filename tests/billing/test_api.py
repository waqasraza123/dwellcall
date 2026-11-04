from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import SecretStr

from dwellcall.account_access.schemas import AccountView
from dwellcall.billing import routes
from dwellcall.errors import ApiError, api_error_handler
from dwellcall.settings import ApiSettings


def test_catalog_is_public_but_checkout_requires_approved_session(monkeypatch: pytest.MonkeyPatch, settings: ApiSettings) -> None:
    access, service = Mock(), Mock()
    user_id = uuid4()
    access.identity.return_value = AccountView(id=user_id, full_name="Synthetic owner", email="demo@example.com", operator_access=False)
    service.create_checkout.return_value = "https://checkout.stripe.com/synthetic"
    monkeypatch.setattr(routes, "AccountAccessService", Mock(return_value=access))
    monkeypatch.setattr(routes, "BillingService", Mock(return_value=service))
    configuration = settings.model_copy(update={"account_auth_enabled": True, "account_portal_secret": SecretStr("p" * 43)})
    app = FastAPI()
    @app.exception_handler(ApiError)
    async def error_handler(request: Request, error: ApiError):
        return await api_error_handler(request, error)
    app.include_router(routes.create_billing_router(configuration, Mock()))
    payload = {"plan": "pro", "request_id": str(uuid4())}
    headers = {"X-Account-Portal-Key": "p" * 43, "Authorization": "Bearer synthetic_session"}
    with TestClient(app) as client:
        assert client.get("/api/v1/billing/plans").status_code == 200
        assert client.post("/api/v1/account/billing/checkout", json=payload).status_code == 404
        access.identity.assert_not_called()
        assert client.post("/api/v1/account/billing/checkout", headers=headers, json=payload).status_code == 403
        service.create_checkout.assert_not_called()
        access.identity.return_value = access.identity.return_value.model_copy(update={"operator_access": True})
        assert client.post("/api/v1/account/billing/checkout", headers=headers, json={**payload, "account_id": str(uuid4())}).status_code == 422
        assert client.post("/api/v1/account/billing/checkout", headers=headers, json=payload).status_code == 200
        assert service.create_checkout.call_args.args[:2] == (user_id, "demo@example.com")
        access.identity.assert_called_with("synthetic_session")
