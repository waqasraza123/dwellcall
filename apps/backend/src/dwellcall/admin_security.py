import secrets

from dwellcall.errors import ApiError
from dwellcall.settings import ApiSettings


def require_admin_token(settings: ApiSettings, supplied_token: str | None) -> None:
    expected = settings.admin_token
    if (
        expected is None
        or len(expected.get_secret_value()) < 32
        or supplied_token is None
        or not secrets.compare_digest(
            supplied_token.encode(), expected.get_secret_value().encode()
        )
    ):
        raise ApiError(
            status_code=401,
            code="ADMIN_AUTH_REQUIRED",
            message="Administrator authentication is required",
        )
