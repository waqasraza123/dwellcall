from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from dwellcall.database.models import ListingSource
from dwellcall.listings.schemas import BusinessContact, SourcePermissionInput


def permission(source: ListingSource) -> SourcePermissionInput:
    return SourcePermissionInput.model_validate(source.permission)


def retained(source: ListingSource, collected_at: datetime, *, display: bool = False) -> bool:
    policy = permission(source)
    return (
        policy.store_allowed and (not display or policy.display_allowed)
        and collected_at + timedelta(days=policy.retention_days) > datetime.now(UTC)
    )


def permitted_geography(data: dict[str, object], policy: SourcePermissionInput) -> bool:
    for field, allowed in (("country", policy.countries), ("state", policy.states), ("city", policy.cities)):
        if allowed and str(data.get(field) or "").casefold() not in {value.casefold() for value in allowed}:
            return False
    return True


def permitted_url(value: str | None, policy: SourcePermissionInput) -> bool:
    if value is None:
        return True
    host = (urlsplit(value).hostname or "").casefold()
    return any(host == allowed.casefold() or host.endswith("." + allowed.casefold()) for allowed in policy.url_hosts)


def verification_status(contact: BusinessContact, policy: SourcePermissionInput) -> str:
    now = datetime.now(UTC)
    verified = (
        policy.trusted_verification and contact.verification == "verified"
        and contact.verified_at is not None
        and now - timedelta(days=policy.retention_days) <= contact.verified_at <= now + timedelta(minutes=5)
    )
    if not verified:
        return "unverified"
    return "synthetic_verified" if policy.data_mode == "synthetic" else "verified"
