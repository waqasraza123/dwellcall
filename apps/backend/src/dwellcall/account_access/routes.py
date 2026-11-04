import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.orm import Session, sessionmaker

from dwellcall.account_access.schemas import (
    AccountView, LoginInput, LoginResponse, MfaChallengeResponse, MfaRecoveryInput,
    MfaSetupResponse, MfaStatusResponse, MfaVerifyInput, SignupInput,
)
from dwellcall.account_access.service import AccountAccessService
from dwellcall.errors import ApiError
from dwellcall.settings import ApiSettings


def create_account_router(settings: ApiSettings, sessions: sessionmaker[Session]) -> APIRouter:
    access = AccountAccessService(sessions, settings)

    def portal(key: Annotated[str | None, Header(alias="X-Account-Portal-Key")] = None) -> None:
        expected = settings.account_portal_secret
        if not settings.account_auth_enabled or expected is None or not key or not secrets.compare_digest(key.encode(), expected.get_secret_value().encode()):
            raise ApiError(status_code=404, code="ACCOUNT_UNAVAILABLE", message="Account access is unavailable.")

    router = APIRouter(prefix="/api/v1/account/auth", dependencies=[Depends(portal)])

    def token(authorization: Annotated[str | None, Header()] = None) -> str | None:
        return authorization[7:] if authorization and authorization.startswith("Bearer ") else None

    Token = Annotated[str | None, Depends(token)]

    @router.post("/signup", response_model=MfaChallengeResponse, status_code=201)
    def signup(data: SignupInput) -> MfaChallengeResponse:
        return access.signup(data)

    @router.post("/login", response_model=MfaChallengeResponse)
    def login(data: LoginInput) -> MfaChallengeResponse:
        return access.login(data)

    @router.get("/me", response_model=AccountView)
    def me(value: Token) -> AccountView:
        return access.identity(value)

    @router.post("/logout", status_code=204)
    def logout(value: Token) -> Response:
        access.logout(value)
        return Response(status_code=204)

    @router.get("/mfa/status", response_model=MfaStatusResponse)
    def status(value: Token) -> MfaStatusResponse:
        return access.mfa.status(value)

    @router.post("/mfa/setup", response_model=MfaSetupResponse)
    def setup(value: Token) -> MfaSetupResponse:
        return access.mfa.setup(value)

    @router.post("/mfa/verify", response_model=LoginResponse)
    def verify(data: MfaVerifyInput, value: Token) -> LoginResponse:
        return access.mfa.verify(value, data.code)

    @router.post("/mfa/recover", response_model=MfaChallengeResponse)
    def recover(data: MfaRecoveryInput, value: Token) -> MfaChallengeResponse:
        return access.mfa.recover(value, data.code)

    @router.post("/mfa/cancel", status_code=204)
    def cancel(value: Token) -> Response:
        access.mfa.cancel(value)
        return Response(status_code=204)

    return router
