import secrets

from dwellcall.errors import ApiError
from dwellcall.settings import ApiSettings


def require_account_portal(settings: ApiSettings, key: str | None) -> None:
    expected = settings.account_portal_secret
    if not settings.account_auth_enabled or expected is None or not key or not secrets.compare_digest(key.encode(), expected.get_secret_value().encode()):
        raise ApiError(status_code=404, code="ACCOUNT_UNAVAILABLE", message="Account access is unavailable.")


def bearer_token(authorization: str | None) -> str | None:
    return authorization[7:] if authorization and authorization.startswith("Bearer ") else None
