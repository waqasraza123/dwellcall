from pydantic import Field, SecretStr, field_validator

from dwellcall.settings import CommonSettings


class ListingSettings(CommonSettings):
    listing_intelligence_enabled: bool = True
    listing_max_import_bytes: int = Field(default=2_097_152, ge=1024, le=4_194_304)
    listing_max_import_records: int = Field(default=250, ge=1, le=500)
    listing_daily_record_limit: int = Field(default=5000, ge=1, le=10000)
    listing_daily_run_limit: int = Field(default=24, ge=1, le=96)
    listing_viewer_token: SecretStr | None = Field(default=None, min_length=32)

    @field_validator("listing_viewer_token", mode="before")
    @classmethod
    def optional_token(cls, value: object) -> object:
        return value.strip() or None if isinstance(value, str) else value
