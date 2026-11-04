from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from dwellcall.account_access.mfa_crypto import hotp
from dwellcall.account_access.schemas import LoginInput, SignupInput
from dwellcall.account_access.service import AccountAccessService
from dwellcall.database.models.account import Account, AccountLoginSession
from dwellcall.database.models.account_mfa import AccountMfaFactor, AccountMfaChallenge
from dwellcall.errors import ApiError
from dwellcall.settings import ApiSettings


def service(sessions: sessionmaker[Session], settings: ApiSettings) -> AccountAccessService:
    return AccountAccessService(sessions, settings.model_copy(update={"account_mfa_encryption_key": SecretStr(Fernet.generate_key().decode())}))


def enrolled(access: AccountAccessService):
    challenge = access.signup(SignupInput(email="demo@example.com", password="synthetic password for enrollment", full_name="Demo"))
    setup = access.mfa.setup(challenge.challenge_token)
    result = access.mfa.verify(challenge.challenge_token, hotp(setup.secret, int(datetime.now(UTC).timestamp() // 30)))
    return challenge, result


def test_mfa_is_required_and_replay_cannot_create_another_session(sessions, settings) -> None:
    access = service(sessions, settings)
    challenge, result = enrolled(access)
    with pytest.raises(ApiError):
        access.identity(challenge.challenge_token)
    with pytest.raises(ApiError):
        access.mfa.verify(challenge.challenge_token, "000000")
    assert not access.identity(result.session_token).operator_access
    with sessions() as session:
        saved = session.scalar(select(AccountLoginSession))
        assert saved is not None and saved.token_hash != result.session_token
        factor = session.scalar(select(AccountMfaFactor))
        assert factor is not None and factor.secret_ciphertext is not None


def test_role_changes_disable_and_logout_apply_to_existing_sessions(sessions, settings) -> None:
    access = service(sessions, settings)
    _, result = enrolled(access)
    with sessions() as session, session.begin():
        account = session.get(Account, result.user.id)
        account.operator_access = True
    assert access.identity(result.session_token).operator_access
    with sessions() as session, session.begin():
        account = session.get(Account, result.user.id)
        account.operator_access = False
    assert not access.identity(result.session_token).operator_access
    access.logout(result.session_token)
    with pytest.raises(ApiError):
        access.identity(result.session_token)


def test_invalid_mfa_attempts_persist_and_lock_the_factor(sessions, settings) -> None:
    access = service(sessions, settings)
    challenge = access.signup(SignupInput(email="demo@example.com", password="synthetic password for lockout", full_name="Demo"))
    with sessions() as session, session.begin():
        row = session.scalar(select(AccountMfaChallenge))
        row.secret_ciphertext = access.mfa.vault().encrypt("A" * 32, f"{row.account_id}:pending:{row.id}")
    for _ in range(5):
        with pytest.raises(ApiError):
            access.mfa.verify(challenge.challenge_token, "invalid")
    with sessions() as session:
        factor = session.scalar(select(AccountMfaFactor))
        assert factor.failed_attempts == 5
        assert factor.locked_until > datetime.now(UTC)


def test_recovery_revokes_sessions_and_requires_replacement_enrollment(sessions, settings) -> None:
    access = service(sessions, settings)
    _, result = enrolled(access)
    login = access.login(LoginInput(email="DEMO@example.com", password="synthetic password for enrollment"))
    replacement = access.mfa.recover(login.challenge_token, result.recovery_codes[0])
    assert replacement.next_action == "enroll"
    with pytest.raises(ApiError):
        access.identity(result.session_token)
    with pytest.raises(ApiError):
        access.identity(replacement.challenge_token)
    setup = access.mfa.setup(replacement.challenge_token)
    fresh = access.mfa.verify(replacement.challenge_token, hotp(setup.secret, int(datetime.now(UTC).timestamp() // 30)))
    assert fresh.recovery_codes != result.recovery_codes
    assert access.identity(fresh.session_token).id == result.user.id
    login = access.login(LoginInput(email="demo@example.com", password="synthetic password for enrollment"))
    with pytest.raises(ApiError):
        access.mfa.recover(login.challenge_token, result.recovery_codes[0])


def test_expired_and_disabled_accounts_cannot_authenticate(sessions, settings) -> None:
    access = service(sessions, settings)
    _, result = enrolled(access)
    with sessions() as session, session.begin():
        saved = session.scalar(select(AccountLoginSession))
        saved.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(ApiError):
        access.identity(result.session_token)
    with sessions() as session, session.begin():
        saved = session.scalar(select(AccountLoginSession))
        saved.expires_at = datetime.now(UTC) + timedelta(hours=1)
        session.get(Account, result.user.id).disabled_at = datetime.now(UTC)
    with pytest.raises(ApiError):
        access.identity(result.session_token)
