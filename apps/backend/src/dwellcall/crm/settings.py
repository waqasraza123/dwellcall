import hashlib
import hmac
import json
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator

from dwellcall.settings import CommonSettings


class CrmSettings(CommonSettings):
    business_name: str = Field(default="DwellCall", min_length=1, max_length=100)
    crm_provider: Literal["none", "gohighlevel", "followupboss", "hubspot"] = "none"
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
    hubspot_api_enabled: bool = False
    hubspot_access_token: SecretStr | None = None
    hubspot_token_type: Literal["service_key", "private_app"] = "service_key"
    hubspot_portal_id: str | None = Field(default=None, pattern=r"^[0-9]{1,20}$")
    hubspot_api_version: Literal["2026-09", "2026-03"] = "2026-09"
    hubspot_declared_scopes: tuple[str, ...] = ()
    hubspot_custom_fields: dict[str, str] = Field(default_factory=dict)
    hubspot_company_mappings: dict[str, str] = Field(default_factory=dict)
    hubspot_lead_source: str = Field(default="DwellCall", min_length=1, max_length=100)
    hubspot_classifications: tuple[str, ...] = ("DwellCall", "Listing Agent")
    hubspot_schema_creation_enabled: bool = False
    hubspot_auto_queue: bool = False
    hubspot_deals_enabled: bool = False
    hubspot_pipeline_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")
    hubspot_stage_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")
    hubspot_qualifying_statuses: tuple[Literal["active", "pending", "sold", "removed"], ...] = ("active",)
    hubspot_qualified_min_listings: int = Field(default=1, ge=1, le=100)
    hubspot_sync_interval_seconds: int = Field(default=60, ge=1, le=86400)
    hubspot_requests_per_second: int = Field(default=4, ge=1, le=4)
    hubspot_phone_calling_codes: tuple[str, ...] = ("1",)
    hubspot_max_lookup_pages: int = Field(default=5, ge=1, le=20)
    followupboss_api_key: SecretStr | None = None
    followupboss_system_name: str | None = Field(default=None, max_length=100)
    followupboss_system_key: SecretStr | None = None
    followupboss_lead_source: str = Field(
        default="DwellCall Demo", min_length=1, max_length=100
    )

    @field_validator(
        "ghl_private_integration_token", "ghl_agency_token", "ghl_location_id", "ghl_company_id",
        "crm_hash_secret", "followupboss_api_key", "followupboss_system_name",
        "followupboss_system_key", "hubspot_access_token", "hubspot_portal_id", mode="before",
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

    @field_validator("hubspot_custom_fields")
    @classmethod
    def validate_hubspot_fields(cls, values: dict[str, str]) -> dict[str, str]:
        from dwellcall.crm.hubspot_mapping import validate_fields
        return validate_fields(values)

    @field_validator("hubspot_company_mappings")
    @classmethod
    def validate_hubspot_companies(cls, values: dict[str, str]) -> dict[str, str]:
        import re
        from dwellcall.listings.normalization import text_key
        if len(values) > 200 or any(not key.strip() or len(key) > 200 or re.fullmatch(r"[0-9]{1,30}", value) is None for key, value in values.items()):
            raise ValueError("Use bounded brokerage names and numeric HubSpot company IDs")
        normalized = {text_key(key): value for key, value in values.items()}
        if len(normalized) != len(values):
            raise ValueError("Brokerage mappings must be unambiguous")
        return normalized

    @field_validator("hubspot_phone_calling_codes")
    @classmethod
    def validate_hubspot_calling_codes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        import re
        if not values or len(values) > 250 or any(re.fullmatch(r"[1-9][0-9]{0,2}", value) is None for value in values):
            raise ValueError("Configure explicit E.164 country calling codes for phone lookups")
        if len(set(values)) != len(values) or any(first != second and first.startswith(second) for first in values for second in values):
            raise ValueError("Calling-code prefixes must be unique and unambiguous")
        return values

    @field_validator("hubspot_classifications")
    @classmethod
    def validate_hubspot_classifications(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) > 20 or any(not value.strip() or len(value) > 100 or ";" in value for value in values):
            raise ValueError("Use at most 20 bounded classification labels without semicolons")
        return tuple(dict.fromkeys(values))

    @model_validator(mode="after")
    def validate_configuration(self) -> Self:
        if self.crm_provider == "none":
            if self.crm_sync_enabled:
                raise ValueError("CRM synchronization requires a selected provider")
            return self
        if self.crm_provider == "hubspot":
            if self.hubspot_api_enabled and not (self.crm_owner_approved and self.hubspot_access_token and self.hubspot_portal_id and self.crm_hash_secret):
                raise ValueError("HubSpot access requires owner approval, a Service Key or private app token, portal ID and hash secret")
            if self.crm_sync_enabled and not (self.hubspot_api_enabled and self.crm_automations_disabled_verified):
                raise ValueError("HubSpot synchronization requires approved API access and automation validation")
            if self.hubspot_deals_enabled and not (self.hubspot_pipeline_id and self.hubspot_stage_id):
                raise ValueError("HubSpot deals require an existing pipeline and stage")
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
        if self.crm_provider == "hubspot":
            return self.hubspot_api_enabled and self.crm_sync_enabled and self.crm_owner_approved and self.crm_automations_disabled_verified
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
        if self.crm_provider == "hubspot":
            if not self.hubspot_portal_id:
                raise ValueError("HubSpot portal ID is unavailable")
            return self.fingerprint("hubspot-portal", self.hubspot_portal_id)
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

    @property
    def agent_provider_selected(self) -> bool:
        return self.crm_provider in {"gohighlevel", "hubspot"}

    @property
    def agent_api_enabled(self) -> bool:
        return self.hubspot_api_enabled if self.crm_provider == "hubspot" else self.ghl_api_enabled

    @property
    def agent_destination_configured(self) -> bool:
        return bool(self.agent_provider_selected and self.crm_hash_secret and (self.hubspot_portal_id if self.crm_provider == "hubspot" else self.ghl_location_id))

    @property
    def agent_fields(self) -> dict[str, str]:
        if self.crm_provider == "hubspot":
            from dwellcall.crm.hubspot_mapping import configured_fields
            return configured_fields(self.hubspot_custom_fields, deals=self.hubspot_deals_enabled)
        return self.ghl_custom_fields

    @property
    def required_agent_fields(self) -> set[str]:
        return set(self.agent_fields) if self.crm_provider == "hubspot" else {"agent_id", "revision", "properties", "brokerage", "sources"}

    @property
    def agent_auto_queue(self) -> bool:
        return self.hubspot_auto_queue if self.crm_provider == "hubspot" else self.ghl_auto_queue

    def agent_code(self, suffix: str) -> str:
        return ("HUBSPOT_" if self.crm_provider == "hubspot" else "GHL_") + suffix
