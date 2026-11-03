import hashlib
import hmac
import json
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator

from dwellcall.settings import CommonSettings


class CrmSettings(CommonSettings):
    business_name: str = Field(default="DwellCall", min_length=1, max_length=100)
    crm_provider: Literal["none", "gohighlevel", "followupboss"] = "none"
    crm_sync_enabled: bool = False
    crm_owner_approved: bool = False
    crm_core_voice_verified: bool = False
    crm_automations_disabled_verified: bool = False
    crm_hash_secret: SecretStr | None = Field(default=None, min_length=32)
    crm_retention_days: int = Field(default=7, ge=1, le=30)
    crm_max_attempts: int = Field(default=3, ge=1, le=5)
    ghl_private_integration_token: SecretStr | None = None
    ghl_location_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")
    ghl_api_enabled: bool = False
    ghl_auto_queue: bool = False
    ghl_custom_fields: dict[str, str] = Field(default_factory=dict)
    ghl_tags: tuple[str, ...] = ("DwellCall", "Listing Agent")
    ghl_lead_source: str = Field(default="DwellCall", min_length=1, max_length=100)
    ghl_declared_scopes: tuple[str, ...] = ()
    ghl_opportunities_enabled: bool = False
    ghl_pipeline_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")
    ghl_pipeline_stage_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")
    ghl_qualifying_statuses: tuple[Literal["active", "pending", "sold", "removed"], ...] = ("active",)
    ghl_qualified_min_listings: int = Field(default=1, ge=1, le=100)
    ghl_provisioning_enabled: bool = False
    ghl_agency_token: SecretStr | None = None
    ghl_company_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")
    followupboss_api_key: SecretStr | None = None
    followupboss_system_name: str | None = Field(default=None, max_length=100)
    followupboss_system_key: SecretStr | None = None
    followupboss_lead_source: str = Field(
        default="DwellCall Demo", min_length=1, max_length=100
    )

    @field_validator(
        "ghl_private_integration_token", "ghl_agency_token", "ghl_location_id", "ghl_company_id",
        "crm_hash_secret", "followupboss_api_key", "followupboss_system_name",
        "followupboss_system_key", mode="before",
    )
    @classmethod
    def normalize_optional(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("followupboss_system_name", "followupboss_lead_source")
    @classmethod
    def safe_header(cls, value: str | None) -> str | None:
        if value is not None and any(ord(char) < 32 or ord(char) > 126 for char in value):
            raise ValueError("CRM identity must contain printable ASCII only")
        return value

    @field_validator("ghl_custom_fields")
    @classmethod
    def validate_ghl_fields(cls, values: dict[str, str]) -> dict[str, str]:
        import re

        allowed = {"agent_id", "revision", "properties", "brokerage", "sources"}
        if set(values) - allowed or any(re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is None for value in values.values()):
            raise ValueError("GHL field mappings require supported DwellCall keys and field IDs")
        if len(set(values.values())) != len(values):
            raise ValueError("GHL field IDs must be distinct")
        return values

    @field_validator("ghl_tags")
    @classmethod
    def validate_ghl_tags(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) > 20 or any(not value.strip() or len(value) > 100 for value in values):
            raise ValueError("Provide at most 20 bounded GHL tags")
        return tuple(dict.fromkeys(values))

    @model_validator(mode="after")
    def validate_configuration(self) -> Self:
        if self.crm_provider == "none":
            if self.crm_sync_enabled:
                raise ValueError("CRM synchronization requires a selected provider")
            return self
        if self.crm_provider == "gohighlevel":
            if self.ghl_api_enabled and not self.crm_owner_approved:
                raise ValueError("GHL API access requires explicit owner approval")
            if self.ghl_api_enabled and not (self.ghl_private_integration_token and self.ghl_location_id and self.crm_hash_secret):
                raise ValueError("GHL API access requires a private integration token, location ID and CRM hash secret")
            if self.crm_sync_enabled and not (self.ghl_api_enabled and self.crm_owner_approved and self.crm_automations_disabled_verified):
                raise ValueError("GHL sync requires API activation, owner approval and automation validation")
            if self.ghl_opportunities_enabled and not (self.ghl_pipeline_id and self.ghl_pipeline_stage_id):
                raise ValueError("GHL opportunities require an existing pipeline and stage")
            return self
        if not all((self.crm_hash_secret, self.followupboss_api_key,
                    self.followupboss_system_name, self.followupboss_system_key)):
            raise ValueError("Follow Up Boss credentials, registered system and hash secret are required")
        if self.crm_sync_enabled and not all((
            self.crm_owner_approved, self.crm_core_voice_verified,
            self.crm_automations_disabled_verified,
        )):
            raise ValueError("CRM sync requires owner approval, core acceptance and automation validation")
        return self

    @property
    def dispatch_enabled(self) -> bool:
        if self.crm_provider == "gohighlevel":
            return self.ghl_api_enabled and self.crm_sync_enabled and self.crm_owner_approved and self.crm_automations_disabled_verified
        return (
            self.crm_provider == "followupboss" and self.crm_sync_enabled
            and self.crm_owner_approved and self.crm_core_voice_verified
            and self.crm_automations_disabled_verified
        )

    def fingerprint(self, purpose: str, value: str) -> str:
        if self.crm_hash_secret is None:
            raise ValueError("CRM hash secret is unavailable")
        return hmac.new(
            self.crm_hash_secret.get_secret_value().encode(),
            f"dwellcall/crm/v1/{purpose}:{value}".encode(),
            hashlib.sha256,
        ).hexdigest()

    @property
    def destination(self) -> str:
        if self.crm_provider == "gohighlevel":
            if not self.ghl_location_id:
                raise ValueError("GHL location ID is unavailable")
            return self.fingerprint("ghl-location", self.ghl_location_id)
        if self.followupboss_api_key is None or self.followupboss_system_key is None:
            raise ValueError("CRM destination credentials are unavailable")
        return self.fingerprint("destination", json.dumps({
            "provider": self.crm_provider,
            "business": self.business_name,
            "api_key": self.followupboss_api_key.get_secret_value(),
            "system": self.followupboss_system_name,
            "system_key": self.followupboss_system_key.get_secret_value(),
            "source": self.followupboss_lead_source,
        }, sort_keys=True))
