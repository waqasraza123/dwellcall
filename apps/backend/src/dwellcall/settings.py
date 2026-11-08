from enum import StrEnum
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from dwellcall.billing.catalog import STRIPE_PRODUCT_ID
from dwellcall.telephony.outbound.settings import OutboundSettings


class RuntimeEnvironment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class DatabaseSslMode(StrEnum):
    DISABLE = "disable"
    REQUIRE = "require"
    VERIFY_CA = "verify-ca"
    VERIFY_FULL = "verify-full"


class CommonSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_environment: RuntimeEnvironment


class DatabaseConnectionSettings(CommonSettings):
    database_url: str
    direct_database_url: str | None = None
    test_database_url: str | None = None
    database_ssl_mode: DatabaseSslMode = DatabaseSslMode.REQUIRE
    database_pool_size: int = Field(default=5, ge=1, le=20)
    database_max_overflow: int = Field(default=2, ge=0, le=20)
    database_pool_timeout_seconds: int = Field(default=10, ge=1, le=60)
    database_pool_recycle_seconds: int = Field(default=300, ge=30, le=3_600)

    @field_validator(
        "database_url",
        "direct_database_url",
        "test_database_url",
    )
    @classmethod
    def validate_postgresql_url(cls, value: str | None) -> str | None:
        if value is None:
            return None

        try:
            parsed_url = make_url(value)
        except ArgumentError as error:
            raise ValueError("database URLs must be valid PostgreSQL URLs") from error
        if parsed_url.drivername not in {"postgresql", "postgresql+psycopg"}:
            raise ValueError("database URLs must use PostgreSQL with psycopg")
        if not parsed_url.database:
            raise ValueError("database URLs must include a database name")
        return value

    @model_validator(mode="after")
    def validate_database_environment(self) -> Self:
        if (
            self.app_environment is RuntimeEnvironment.TEST
            and self.test_database_url is None
        ):
            raise ValueError("TEST_DATABASE_URL is required in the test environment")
        if (
            self.app_environment is RuntimeEnvironment.TEST
            and self.test_database_url is not None
            and any(
                database_target(self.test_database_url) == database_target(url)
                for url in (self.database_url, self.direct_database_url)
                if url is not None
            )
        ):
            raise ValueError(
                "TEST_DATABASE_URL must be isolated from database runtime and "
                "migration URLs"
            )
        if (
            self.app_environment is RuntimeEnvironment.PRODUCTION
            and self.database_ssl_mode is DatabaseSslMode.DISABLE
        ):
            raise ValueError("database SSL cannot be disabled in production")
        return self

    @property
    def runtime_database_url(self) -> str:
        if self.app_environment is RuntimeEnvironment.TEST:
            if self.test_database_url is None:
                raise RuntimeError("test database configuration is unavailable")
            return self.test_database_url
        return self.database_url

    @property
    def migration_database_url(self) -> str:
        if self.app_environment is RuntimeEnvironment.TEST:
            return self.runtime_database_url
        return self.direct_database_url or self.database_url


class ApiSettings(OutboundSettings, DatabaseConnectionSettings):
    billing_enabled: bool = False
    stripe_secret_key: SecretStr | None = None
    stripe_webhook_secret: SecretStr | None = None
    stripe_product_id: str = Field(default=STRIPE_PRODUCT_ID, pattern=r"^[A-Za-z0-9_]+$", max_length=255)
    stripe_pro_price_id: str | None = Field(default=None, pattern=r"^price_[A-Za-z0-9_]+$")
    stripe_team_price_id: str | None = Field(default=None, pattern=r"^price_[A-Za-z0-9_]+$")
    stripe_portal_configuration_id: str | None = Field(default=None, pattern=r"^bpc_[A-Za-z0-9_]+$")
    stripe_portal_pro_configuration_id: str | None = Field(default=None, pattern=r"^bpc_[A-Za-z0-9_]+$")
    stripe_portal_team_configuration_id: str | None = Field(default=None, pattern=r"^bpc_[A-Za-z0-9_]+$")
    stripe_live_mode: bool = False

    @model_validator(mode="after")
    def validate_billing_configuration(self) -> Self:
        if self.stripe_secret_key:
            prefix = "sk_live_" if self.stripe_live_mode else "sk_test_"
            if not self.stripe_secret_key.get_secret_value().startswith(prefix):
                raise ValueError("STRIPE_SECRET_KEY must match STRIPE_LIVE_MODE")
        if self.stripe_pro_price_id and self.stripe_pro_price_id == self.stripe_team_price_id:
            raise ValueError("Pro and Team require different Stripe prices")
        if self.billing_enabled:
            if not self.account_auth_enabled:
                raise ValueError("Billing requires account authentication")
            if not all((self.stripe_secret_key, self.stripe_webhook_secret, self.stripe_pro_price_id,
                        self.stripe_team_price_id, self.stripe_portal_configuration_id,
                        self.stripe_portal_pro_configuration_id, self.stripe_portal_team_configuration_id)):
                raise ValueError("Billing requires the complete Stripe catalog and webhook configuration")
            if self.app_environment is RuntimeEnvironment.PRODUCTION and not self.web_origin.startswith("https://"):
                raise ValueError("Production billing requires an HTTPS WEB_ORIGIN")
        return self

    account_auth_enabled: bool = False
    account_portal_secret: SecretStr | None = Field(default=None, min_length=32)
    account_mfa_encryption_key: SecretStr | None = None

    @model_validator(mode="after")
    def validate_account_security(self) -> Self:
        if self.account_auth_enabled and not (self.account_portal_secret and self.account_mfa_encryption_key):
            raise ValueError("Account authentication requires ACCOUNT_PORTAL_SECRET and ACCOUNT_MFA_ENCRYPTION_KEY")
        if self.account_mfa_encryption_key:
            from cryptography.fernet import Fernet
            try:
                Fernet(self.account_mfa_encryption_key.get_secret_value().encode())
            except (ValueError, TypeError) as error:
                raise ValueError("ACCOUNT_MFA_ENCRYPTION_KEY must be a Fernet key") from error
        if self.account_portal_secret and self.account_portal_secret == self.admin_token:
            raise ValueError("Account portal and admin secrets must differ")
        return self

    api_host: str = Field(default="127.0.0.1", min_length=1)
    api_port: int = Field(default=8000, ge=1, le=65_535)
    web_origin: str = "http://localhost:3000"
    admin_token: SecretStr | None = Field(default=None, min_length=32)
    retell_test_audio_enabled: bool = False
    browser_text_enabled: bool = False
    browser_voice_enabled: bool = False
    browser_mock_enabled: bool = False
    retell_api_key: SecretStr | None = None
    retell_agent_id: str | None = Field(default=None, min_length=1, max_length=200)
    retell_agent_version: int | None = Field(default=None, ge=0)
    retell_websocket_secret: SecretStr | None = Field(default=None, min_length=32)
    llm_api_key: SecretStr | None = None
    llm_model: str = Field(default="gpt-4.1-mini", min_length=1, max_length=100)
    business_name: str = Field(default="DwellCall", min_length=1, max_length=100)
    supported_location: str = Field(default="Austin, TX", min_length=1, max_length=100)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    personality: str = Field(
        default="Warm, concise and thoughtful. Ask one natural question at a time.",
        min_length=1,
        max_length=1000,
    )
    property_catalog_path: Path = Path("data/properties.json")
    conversation_max_duration_seconds: int = Field(default=180, ge=60, le=180)
    conversation_daily_session_limit: int = Field(default=5, ge=1, le=10)
    conversation_max_responses: int = Field(default=20, ge=1, le=20)
    conversation_reserved_cost_cents: int = Field(default=0, ge=0, le=100_000)
    conversation_daily_budget_cents: int = Field(default=0, ge=0, le=100_000)

    @field_validator("web_origin")
    @classmethod
    def validate_web_origin(cls, value: str) -> str:
        parsed_origin = urlsplit(value)
        if (
            parsed_origin.scheme not in {"http", "https"}
            or parsed_origin.hostname is None
            or parsed_origin.username is not None
            or parsed_origin.password is not None
            or parsed_origin.path not in {"", "/"}
            or parsed_origin.query
            or parsed_origin.fragment
        ):
            raise ValueError("WEB_ORIGIN must be an HTTP or HTTPS origin")
        return value.rstrip("/")

    @field_validator(
        "stripe_secret_key",
        "stripe_webhook_secret",
        "stripe_pro_price_id",
        "stripe_team_price_id",
        "stripe_portal_configuration_id",
        "stripe_portal_pro_configuration_id",
        "stripe_portal_team_configuration_id",
        "account_portal_secret",
        "account_mfa_encryption_key",
        "retell_api_key",
        "retell_agent_id",
        "retell_websocket_secret",
        "llm_api_key",
        "admin_token",
        "retell_agent_version",
        mode="before",
    )
    @classmethod
    def normalize_optional(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def validate_private_audio(self) -> Self:
        if self.browser_mock_enabled and (self.app_environment is RuntimeEnvironment.PRODUCTION or self.browser_text_enabled or self.browser_voice_enabled):
            raise ValueError("Browser simulation is development-only and cannot be combined with live browser modes")
        if self.browser_voice_enabled and not self.retell_test_audio_enabled:
            raise ValueError("Browser voice requires the configured private Retell web-call feature")
        if self.browser_text_enabled and (not self.llm_api_key or not self.admin_token):
            raise ValueError("Browser text requires the existing LLM and admin credentials")
        if self.browser_text_enabled or self.browser_mock_enabled:
            if not self.admin_token or not 0 < self.conversation_reserved_cost_cents <= self.conversation_daily_budget_cents:
                raise ValueError("Browser conversations require operator authentication and a positive shared conversation budget")
        if self.outbound_mock_enabled and self.app_environment is RuntimeEnvironment.PRODUCTION:
            raise ValueError("Mock calling is limited to development or isolated tests")
        if self.outbound_enabled:
            if not (self.outbound_public_base_url and (self.outbound_provider != "retell" or self.outbound_sip_username.get_secret_value()) and self.outbound_destination_permissions_confirmed and self.outbound_caller_id_confirmed):
                raise ValueError("Confirm Telnyx destination permissions/rates and caller ID, and configure the public API origin and SIP username")
            if not self.admin_token:
                raise ValueError("Outbound calling requires administrator authentication")
            if self.outbound_provider == "retell" and self.outbound_agent_id == self.retell_agent_id:
                raise ValueError("Outbound calling requires a dedicated agent separate from web calls")
        if not (self.retell_test_audio_enabled or (self.outbound_enabled and self.outbound_provider == "retell")):
            return self
        if not all(
            (
                self.retell_api_key,
                self.retell_websocket_secret,
                self.llm_api_key,
                self.admin_token,
            )
        ):
            raise ValueError(
                "Private audio requires dedicated Retell, LLM and admin credentials"
            )
        if self.retell_test_audio_enabled and (self.retell_agent_version is None or not self.retell_agent_id):
            raise ValueError(
                "Pin RETELL_AGENT_VERSION to the private dashboard test agent version"
            )
        if self.retell_websocket_secret == self.admin_token:
            raise ValueError("WebSocket and operator secrets must differ")
        secret = self.retell_websocket_secret
        if secret and not all(
            c.isascii() and (c.isalnum() or c in "-_")
            for c in secret.get_secret_value()
        ):
            raise ValueError("RETELL_WEBSOCKET_SECRET must be URL-safe")
        if self.retell_test_audio_enabled and not (
            0 < self.conversation_reserved_cost_cents
            <= self.conversation_daily_budget_cents
        ):
            raise ValueError(
                "Set a positive per-session reservation within the daily spending budget"
            )
        return self


def database_target(value: str) -> tuple[str | None, int, str | None]:
    parsed_url = make_url(value)
    host = parsed_url.host.lower() if parsed_url.host is not None else None
    if host is not None:
        first_label, separator, remaining_labels = host.partition(".")
        host = first_label.removesuffix("-pooler") + separator + remaining_labels
    return (
        host,
        parsed_url.port or 5432,
        parsed_url.database,
    )
