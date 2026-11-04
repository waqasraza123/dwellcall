from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from dwellcall.account_access.mfa_crypto import MfaVault, hotp, new_recovery_codes, new_totp_secret, valid_totp_counter
from dwellcall.account_access.passwords import hash_password, verify_password
from dwellcall.account_access.schemas import SignupInput
from dwellcall.settings import ApiSettings


def test_scrypt_and_unknown_account_reject_invalid_passwords() -> None:
    encoded = hash_password("synthetic password for unit specification")
    assert verify_password("synthetic password for unit specification", encoded)
    assert not verify_password("wrong", encoded)
    assert not verify_password("wrong", None)
    assert not verify_password("wrong", "invalid")


def test_totp_replay_and_secret_context() -> None:
    secret = new_totp_secret()
    code = hotp(secret, 100)
    assert valid_totp_counter(secret, code, 3000, None) == 100
    assert valid_totp_counter(secret, code, 3000, 100) is None
    vault = MfaVault(Fernet.generate_key().decode())
    encrypted = vault.encrypt(secret, "account-a")
    assert secret not in encrypted
    assert vault.decrypt(encrypted, "account-a") == secret
    with pytest.raises(ValueError):
        vault.decrypt(encrypted, "account-b")
    codes = new_recovery_codes()
    assert len(set(codes)) == 10
    account_id = uuid4()
    assert vault.recovery_hash(account_id, codes[0]) == vault.recovery_hash(account_id, codes[0].upper())
    assert vault.recovery_hash(account_id, codes[0]) != vault.recovery_hash(uuid4(), codes[0])


def test_signup_cannot_set_its_operator_role() -> None:
    with pytest.raises(ValidationError):
        SignupInput(email="demo@example.com", password="synthetic password", full_name="Demo", operator_access=True)
    with pytest.raises(ValidationError):
        SignupInput(email="demo@example.com", password="short", full_name="Demo")


def test_auth_activation_requires_separate_valid_secrets(settings: ApiSettings) -> None:
    values = settings.model_dump()
    with pytest.raises(ValidationError):
        ApiSettings.model_validate({**values, "account_auth_enabled": True})
    with pytest.raises(ValidationError):
        ApiSettings.model_validate({**values, "account_auth_enabled": True, "account_portal_secret": settings.admin_token, "account_mfa_encryption_key": Fernet.generate_key().decode()})
    with pytest.raises(ValidationError):
        ApiSettings.model_validate({**values, "account_mfa_encryption_key": "invalid"})
