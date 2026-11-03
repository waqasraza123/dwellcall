from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID
from urllib.parse import urlsplit
import ipaddress

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

SourceKey = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
Identifier = Annotated[str, Field(min_length=1, max_length=128)]
ListingStatus = Literal["active", "pending", "sold", "removed", "unknown"]
PropertyType = Literal["single_family", "condo", "townhouse", "multifamily", "land", "other"]
ContactKind = Literal["business_email", "direct_business_phone", "office_phone", "professional_mobile"]


def reference_url(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlsplit(value)
    host = (parsed.hostname or "").rstrip(".")
    if any(ord(char) < 32 for char in value) or parsed.port not in {None, 80, 443}:
        raise ValueError("Reference contains unsupported controls or port")
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise ValueError("A public HTTP(S) reference without credentials is required")
    if host.casefold() in {"localhost", "localhost.localdomain"} or host.casefold().endswith((".local", ".internal")):
        raise ValueError("Local references are not supported")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("Private IP references are not supported")
    return value


class RecordModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ReviewResolutionInput(RecordModel):
    decision: Literal["approve", "reject"]
    candidate_id: UUID | None = None
    evidence_reference: str = Field(pattern=r"^[A-Za-z0-9_-]{1,160}$")

    @model_validator(mode="after")
    def candidate_for_approval(self) -> Self:
        if (self.decision == "approve") != (self.candidate_id is not None):
            raise ValueError("Approval requires one proposed candidate; rejection has no candidate")
        return self


class AgentIdentifier(RecordModel):
    namespace: SourceKey
    value: Identifier


class BusinessContact(RecordModel):
    kind: ContactKind
    value: str = Field(min_length=1, max_length=254)
    published_as_business: Literal[True]
    direct: bool = False
    verification: Literal["verified", "unverified"] = "unverified"
    verified_at: AwareDatetime | None = None
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    source_reference: str = Field(min_length=1, max_length=160)
    source_url: str | None = Field(default=None, max_length=2000)

    _url = field_validator("source_url")(reference_url)

    @field_validator("verified_at")
    @classmethod
    def utc_verified(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None

    @field_validator("published_as_business", mode="before")
    @classmethod
    def explicit_business(cls, value: object) -> object:
        if value is not True:
            raise ValueError("Only explicitly published professional business contacts are accepted")
        return value

    @model_validator(mode="after")
    def validate_contact(self) -> Self:
        import re
        from pydantic import TypeAdapter
        if self.kind == "business_email":
            self.value = str(TypeAdapter(EmailStr).validate_python(self.value)).casefold()
        elif re.fullmatch(r"\+[1-9][0-9]{7,14}", self.value) is None:
            raise ValueError("Telephone values require explicit E.164 format; no country is inferred")
        if self.kind == "office_phone" and self.direct:
            raise ValueError("Office numbers cannot be direct-person identity evidence")
        if self.verification == "verified" and self.verified_at is None:
            raise ValueError("Source-declared verification requires a verification timestamp")
        return self


class AgentRecord(RecordModel):
    source_agent_id: Identifier | None = None
    identifiers: tuple[AgentIdentifier, ...] = Field(default=(), max_length=8)
    full_name: str = Field(min_length=1, max_length=200)
    brokerage: str | None = Field(default=None, max_length=200)
    profile_url: str | None = Field(default=None, max_length=2000)
    contacts: tuple[BusinessContact, ...] = Field(default=(), max_length=10)

    _url = field_validator("profile_url")(reference_url)

    @model_validator(mode="after")
    def distinct_evidence(self) -> Self:
        if len({item.namespace for item in self.identifiers}) != len(self.identifiers):
            raise ValueError("Provide one identifier per authority namespace")
        if len({(item.kind, item.value) for item in self.contacts}) != len(self.contacts):
            raise ValueError("Contact entries must be unique")
        return self


class ListingRecord(RecordModel):
    source_listing_id: Identifier
    listing_namespace: SourceKey | None = None
    listing_reference: Identifier | None = None
    street_address: str | None = Field(default=None, max_length=240)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    postal_code: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    price: Decimal | None = Field(default=None, gt=0, le=999_999_999_999, decimal_places=2)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    listing_date: date | None = None
    source_updated_at: AwareDatetime | None = None
    bedrooms: int | None = Field(default=None, ge=0, le=100)
    bathrooms: Decimal | None = Field(default=None, gt=0, le=100, decimal_places=2)
    interior_sqft: Decimal | None = Field(default=None, gt=0, le=10_000_000, decimal_places=2)
    property_type: PropertyType | None = None
    listing_type: Literal["sale", "rent"] | None = None
    listing_url: str | None = Field(default=None, max_length=2000)
    status: ListingStatus | None = None
    agents: tuple[AgentRecord, ...] = Field(default=(), max_length=10)
    metadata: dict[Literal["feed_name", "record_type", "office_id", "attribution"], str] = Field(default_factory=dict, max_length=4)

    _url = field_validator("listing_url")(reference_url)

    @field_validator("source_updated_at")
    @classmethod
    def utc_updated(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None

    @field_validator("price", "bathrooms", "interior_sqft")
    @classmethod
    def canonical_decimal(cls, value: Decimal | None) -> Decimal | None:
        return value.quantize(Decimal("0.01")) if value is not None else None

    @field_validator("metadata")
    @classmethod
    def bounded_metadata(cls, values: dict[str, str]) -> dict[str, str]:
        if any(len(value) > 200 for value in values.values()):
            raise ValueError("Metadata values must be bounded")
        return values

    @model_validator(mode="after")
    def evidence_pair(self) -> Self:
        if (self.listing_namespace is None) != (self.listing_reference is None):
            raise ValueError("Listing namespace and reference must be supplied together")
        return self


class DiscoveryFilters(RecordModel):
    states: tuple[str, ...] = Field(default=(), max_length=20)
    cities: tuple[str, ...] = Field(default=(), max_length=20)
    postal_codes: tuple[str, ...] = Field(default=(), max_length=20)
    min_price: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, gt=0)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    property_types: tuple[PropertyType, ...] = Field(default=(), max_length=6)
    statuses: tuple[ListingStatus, ...] = Field(default=(), max_length=5)
    listing_types: tuple[Literal["sale", "rent"], ...] = Field(default=(), max_length=2)

    @model_validator(mode="after")
    def ordered_prices(self) -> Self:
        if self.min_price is not None and self.max_price is not None and self.min_price > self.max_price:
            raise ValueError("Minimum price cannot exceed maximum price")
        return self


class SourcePermissionInput(RecordModel):
    provider: Literal["file", "licensed_feed"] = "file"
    data_mode: Literal["synthetic", "live"] = "synthetic"
    enabled: bool = False
    access_confirmed: bool = False
    permission_reference: str = Field(pattern=r"^[A-Za-z0-9_-]{1,160}$")
    retrieve_allowed: bool = False
    store_allowed: bool = False
    display_allowed: bool = False
    export_allowed: bool = False
    contacts_allowed: bool = False
    trusted_verification: bool = False
    countries: tuple[str, ...] = Field(min_length=1, max_length=20)
    states: tuple[str, ...] = Field(default=(), max_length=20)
    cities: tuple[str, ...] = Field(default=(), max_length=20)
    identifier_namespaces: tuple[SourceKey, ...] = Field(default=(), max_length=20)
    url_hosts: tuple[str, ...] = Field(default=(), max_length=20)
    retention_days: int = Field(default=30, ge=1, le=365)
    attribution: str = Field(min_length=1, max_length=240)
    poll_interval_minutes: int = Field(default=60, ge=15, le=1440)

    @field_validator("url_hosts")
    @classmethod
    def valid_hosts(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        import re
        if any(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}[A-Za-z0-9]", value) is None or ".." in value for value in values):
            raise ValueError("Provide explicit DNS reference hosts without wildcards or paths")
        return tuple(value.casefold().rstrip(".") for value in values)

    @model_validator(mode="after")
    def explicit_access(self) -> Self:
        if self.enabled and not (self.access_confirmed and self.retrieve_allowed and self.store_allowed):
            raise ValueError("Activation requires confirmed retrieval/storage permission")
        return self
