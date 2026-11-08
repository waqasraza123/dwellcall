from unittest.mock import Mock
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from dwellcall.account_access.schemas import AccountView
from dwellcall.account_access.service import AccountAccessService, unauthorized
from dwellcall.errors import ApiError, api_error_handler
from dwellcall.settings import ApiSettings
from dwellcall.telephony.outbound.review_routes import create_lead_review_router
from dwellcall.telephony.outbound.reviews import CallLeadReviewService


def test_account_portal_and_approved_mfa_identity_are_required(outbound_settings, monkeypatch):
    settings = ApiSettings.model_validate({**outbound_settings.model_dump(), "account_auth_enabled": True,
        "account_portal_secret": "p" * 43, "account_mfa_encryption_key": Fernet.generate_key().decode()})
    calls = Mock()
    calls.sessions = Mock()
    identity = Mock(side_effect=unauthorized())
    monkeypatch.setattr(AccountAccessService, "identity", identity)
    read = Mock()
    monkeypatch.setattr(CallLeadReviewService, "get", read)
    app = FastAPI()
    @app.exception_handler(ApiError)
    async def handle(request: Request, error: ApiError):
        return await api_error_handler(request, error)
    app.include_router(create_lead_review_router(settings, calls))
    path = "/api/v1/account/call-leads/" + str(uuid4())
    with TestClient(app) as client:
        assert client.get(path, headers={"X-Admin-Token": "b" * 43}).status_code == 404
        identity.assert_not_called()
        headers = {"X-Account-Portal-Key": "p" * 43, "Authorization": "Bearer revoked-synthetic-session"}
        assert client.get(path, headers=headers).status_code == 401
        identity.assert_called_with("revoked-synthetic-session")
        identity.side_effect = None
        identity.return_value = AccountView(id=uuid4(), full_name="Synthetic", email="synthetic@example.test", operator_access=False)
        assert client.get(path, headers=headers).status_code == 403
    read.assert_not_called()
