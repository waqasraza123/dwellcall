import hashlib
import hmac
import json
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator

from dwellcall.settings import CommonSettings


class CrmSettings(CommonSettings):
    business_name: str = Field(default="DwellCall", min_length=1, max_length=100)
    crm_provider: Literal["none", "followupboss"] = "none"
    crm_sync_enabled: bool = False
    crm_owner_approved: bool = False
    crm_core_voice_verified: bool = False
    crm_automations_disabled_verified: bool = False
    crm_hash_secret: SecretStr | None = Field(default=None, min_length=32)
    crm_retention_days: int = Field(default=7, ge=1, le=30)
    crm_max_attempts: int = Field(default=3, ge=1, le=5)
    followupboss_api_key: SecretStr | None = None
    followupboss_system_name: str | None = Field(default=None, max_length=100)
    followupboss_system_key: SecretStr | None = None
    followupboss_lead_source: str = Field(
        default="DwellCall Demo", min_length=1, max_length=100
    )

    @field_validator(
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

    @model_validator(mode="after")
    def validate_configuration(self) -> Self:
        if self.crm_provider == "none":
            if self.crm_sync_enabled:
                raise ValueError("CRM synchronization requires a selected provider")
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
