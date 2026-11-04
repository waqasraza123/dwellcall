import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from dwellcall.account_access.mfa import AccountMfaService
from dwellcall.account_access.passwords import hash_password, verify_password
from dwellcall.account_access.schemas import AccountView, LoginInput, LoginResponse, MfaChallengeResponse, SignupInput
from dwellcall.database.models.account import Account, AccountAuthLimit, AccountLoginSession
from dwellcall.database.models.account_mfa import AccountMfaFactor
from dwellcall.errors import ApiError
from dwellcall.settings import ApiSettings

SESSION_LIFETIME_SECONDS = 8 * 60 * 60


def unauthorized() -> ApiError:
    return ApiError(status_code=401, code="ACCOUNT_AUTH_REQUIRED", message="Sign in to continue.")


def account_view(account: Account) -> AccountView:
    return AccountView(id=account.id, full_name=account.full_name, email=account.email, operator_access=account.operator_access)


class AccountAccessService:
    def __init__(self, sessions: sessionmaker[Session], settings: ApiSettings) -> None:
        self.sessions = sessions
        self.settings = settings
        self.mfa = AccountMfaService(sessions, settings, self._issue_session)

    def _throttle(self, email: str) -> None:
        for key, limit, seconds in [
            ("all", 30, 60),
            (hashlib.sha256(email.encode()).hexdigest(), 5, 15 * 60),
        ]:
            now = datetime.now(UTC)
            with self.sessions() as session, session.begin():
                session.execute(insert(AccountAuthLimit).values(
                    key=key, attempts=0, window_started_at=now,
                ).on_conflict_do_nothing())
                row = session.get(AccountAuthLimit, key, with_for_update=True)
                if row is None:
                    raise RuntimeError("Authentication rate limit unavailable")
                if row.window_started_at + timedelta(seconds=seconds) <= now:
                    row.attempts = 0
                    row.window_started_at = now
                if row.attempts >= limit:
                    raise ApiError(status_code=429, code="AUTH_RATE_LIMITED", message="Too many attempts. Please try again later.", headers={"Retry-After": str(seconds)})
                row.attempts += 1

    def signup(self, request: SignupInput) -> MfaChallengeResponse:
        self.mfa.vault()
        email = str(request.email).casefold()
        self._throttle(email)
        password_hash = hash_password(request.password.get_secret_value())
        try:
            with self.sessions() as session, session.begin():
                account = Account(full_name=request.full_name, email=email, password_hash=password_hash, operator_access=False, created_at=datetime.now(UTC))
                session.add(account)
                session.flush()
                return self.mfa.start(session, account)
        except IntegrityError as error:
            raise ApiError(status_code=409, code="ACCOUNT_UNAVAILABLE", message="We could not create an account with those details. Try signing in instead.") from error

    def login(self, request: LoginInput) -> MfaChallengeResponse:
        email = str(request.email).casefold()
        self._throttle(email)
        with self.sessions() as session, session.begin():
            account = session.scalar(select(Account).where(Account.email == email))
            matches = verify_password(request.password.get_secret_value(), account.password_hash if account else None)
            if not matches or account is None or account.disabled_at is not None:
                raise ApiError(status_code=401, code="INVALID_CREDENTIALS", message="That email and password do not match. Please try again.")
            return self.mfa.start(session, account)

    @staticmethod
    def _issue_session(session: Session, account: Account, mfa_version: int) -> LoginResponse:
        factor = session.get(AccountMfaFactor, account.id)
        if factor is None or factor.enabled_at is None or factor.version != mfa_version:
            raise unauthorized()
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        session.add(AccountLoginSession(account_id=account.id, token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=now + timedelta(seconds=SESSION_LIFETIME_SECONDS), mfa_verified_at=now, mfa_version=mfa_version))
        return LoginResponse(user=account_view(account), session_token=token, expires_in=SESSION_LIFETIME_SECONDS)

    def identity(self, token: str | None) -> AccountView:
        if not token or len(token) > 128:
            raise unauthorized()
        with self.sessions() as session:
            account = session.scalar(select(Account)
                .join(AccountLoginSession, AccountLoginSession.account_id == Account.id)
                .join(AccountMfaFactor, AccountMfaFactor.account_id == Account.id)
                .where(AccountLoginSession.token_hash == hashlib.sha256(token.encode()).hexdigest(), AccountLoginSession.revoked_at.is_(None), AccountLoginSession.expires_at > datetime.now(UTC), AccountLoginSession.mfa_verified_at.is_not(None), AccountLoginSession.mfa_version == AccountMfaFactor.version, AccountMfaFactor.enabled_at.is_not(None), Account.disabled_at.is_(None)))
            if account is None:
                raise unauthorized()
            return account_view(account)

    def logout(self, token: str | None) -> None:
        if not token or len(token) > 128:
            return
        with self.sessions() as session, session.begin():
            row = session.scalar(select(AccountLoginSession).where(AccountLoginSession.token_hash == hashlib.sha256(token.encode()).hexdigest()).with_for_update())
            if row:
                row.revoked_at = datetime.now(UTC)
