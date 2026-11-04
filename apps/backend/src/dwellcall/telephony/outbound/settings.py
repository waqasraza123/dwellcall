from typing import Self
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

from dwellcall.telephony.outbound.destinations import destination_country, normalize_phone_number


class OutboundSettings(BaseModel):
    outbound_enabled: bool = False
    outbound_mock_enabled: bool = False
    outbound_agent_id: str | None = Field(default=None, min_length=1, max_length=200)
    outbound_agent_version: int | None = Field(default=None, ge=0)
    outbound_from_number: SecretStr = SecretStr("")
    outbound_allowed_numbers: SecretStr = SecretStr("")
    outbound_suppressed_numbers: SecretStr = SecretStr("")
    outbound_hash_secret: SecretStr | None = Field(default=None, min_length=32)
    outbound_allowed_countries: frozenset[str] = frozenset({"US"})
    outbound_confirmed_international_countries: frozenset[str] = frozenset()
    outbound_destination_permissions_confirmed: bool = False
    outbound_caller_id_confirmed: bool = False
    outbound_sip_username: SecretStr = SecretStr("")
    outbound_telnyx_termination_host: str = "sip.telnyx.com"
    outbound_public_base_url: str | None = None
    outbound_daily_limit: int = Field(default=5, ge=1, le=5)
    outbound_number_daily_limit: int = Field(default=1, ge=1, le=1)
    outbound_cooldown_seconds: int = Field(default=300, ge=300, le=86400)
    outbound_max_duration_seconds: int = Field(default=180, ge=60, le=180)
    outbound_ringing_seconds: int = Field(default=25, ge=10, le=30)
    outbound_reserved_cost_cents: int = Field(default=0, ge=0, le=100000)
    outbound_daily_budget_cents: int = Field(default=0, ge=0, le=100000)
    outbound_retention_days: int = Field(default=7, ge=1, le=30)
    outbound_transfer_enabled: bool = False
    outbound_human_number: SecretStr = SecretStr("")
    outbound_transfer_compatibility_confirmed: bool = False
    outbound_transfer_carrier_limit_confirmed: bool = False
    outbound_transfer_max_seconds: int = Field(default=180, ge=1, le=180)
    outbound_transfer_reserved_cost_cents: int = Field(default=0, ge=0, le=100000)

    @field_validator("outbound_agent_id", "outbound_agent_version", "outbound_hash_secret", "outbound_public_base_url", mode="before")
    @classmethod
    def empty_optional(cls, value: object) -> object:
        return (value.strip() or None) if isinstance(value, str) else value

    @field_validator("outbound_telnyx_termination_host")
    @classmethod
    def telnyx_host(cls, value: str) -> str:
        if value != "sip.telnyx.com" and not (value.endswith(".sip.telnyx.com") and all(c.isalnum() or c in ".-" for c in value)):
            raise ValueError("Use the documented Telnyx regional SIP hostname")
        return value

    @field_validator("outbound_allowed_countries", "outbound_confirmed_international_countries")
    @classmethod
    def countries(cls, value: frozenset[str]) -> frozenset[str]:
        if any(country not in phonenumbers_regions() for country in value):
            raise ValueError("Use supported uppercase ISO country codes")
        return value

    @property
    def allowed_numbers(self) -> frozenset[str]:
        return self._numbers(self.outbound_allowed_numbers)

    @property
    def suppressed_numbers(self) -> frozenset[str]:
        return self._numbers(self.outbound_suppressed_numbers)

    @staticmethod
    def _numbers(secret: SecretStr) -> frozenset[str]:
        return frozenset(normalize_phone_number(value) for value in secret.get_secret_value().split(",") if value.strip())

    @model_validator(mode="after")
    def outbound_configuration(self) -> Self:
        if self.outbound_transfer_enabled:
            raise ValueError("Outbound transfer is disabled permanently; DwellCall is operated only by AI agents")
        if self.outbound_allowed_countries != frozenset({"US"}) or self.outbound_confirmed_international_countries:
            raise ValueError("Outbound calling is restricted to US destinations")
        allowed = self.allowed_numbers
        self.suppressed_numbers
        for number in (self.outbound_from_number, self.outbound_human_number):
            if number.get_secret_value():
                if normalize_phone_number(number.get_secret_value()) != number.get_secret_value():
                    raise ValueError("Configured caller and human numbers must be canonical E.164")
        base = self.outbound_public_base_url
        if base:
            parsed = urlsplit(base)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
                raise ValueError("OUTBOUND_PUBLIC_BASE_URL must be an HTTPS origin")
            self.outbound_public_base_url = base.rstrip("/")
        if self.outbound_mock_enabled and self.outbound_enabled:
            raise ValueError("Mock mode and live calling cannot both be enabled")
        if not (self.outbound_enabled or self.outbound_mock_enabled):
            return self
        if not allowed or not self.outbound_hash_secret:
            raise ValueError("Outbound calling requires an approved allowlist and stable hash secret")
        if not self.outbound_agent_id or self.outbound_agent_version is None or not self.outbound_from_number.get_secret_value():
            raise ValueError("Configure an outbound agent version and imported caller number")
        caller = self.outbound_from_number.get_secret_value()
        human = self.outbound_human_number.get_secret_value()
        if caller in allowed or (human and (human in allowed or human == caller)):
            raise ValueError("Caller, recipients and human destination must differ")
        if any(destination_country(number) not in self.outbound_allowed_countries for number in allowed):
            raise ValueError("Every allowlisted recipient must be in an authorized country")
        if not 0 < self.outbound_reserved_cost_cents <= self.outbound_daily_budget_cents:
            raise ValueError("Set positive calling reservations within the daily budget")
        return self


def phonenumbers_regions() -> frozenset[str]:
    from phonenumbers import SUPPORTED_REGIONS
    return frozenset(SUPPORTED_REGIONS)
