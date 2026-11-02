from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dwellcall.settings import ApiSettings


class RentalProperty(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=100)
    neighborhood: str = Field(min_length=1, max_length=100)
    monthly_rent: int = Field(gt=0, le=10_000_000)
    bedrooms: int = Field(ge=0, le=20)
    bathrooms: float = Field(gt=0, le=20)
    pets_allowed: bool
    features: list[str] = Field(max_length=12)


class PropertyCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fictional: Literal[True]
    location: str = Field(min_length=1, max_length=100)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    properties: list[RentalProperty] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        if len({item.id for item in self.properties}) != len(self.properties):
            raise ValueError("Property IDs must be unique")
        return self


class RentalRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_monthly_rent: int | None = Field(ge=1, le=10_000_000)
    bedrooms: int | None = Field(ge=0, le=20)
    neighborhood: str | None = Field(max_length=100)
    move_in: str | None = Field(max_length=100)
    pets: bool | None


def load_catalog(settings: ApiSettings) -> PropertyCatalog:
    path: Path = settings.property_catalog_path
    if path.stat().st_size > 256_000:
        raise ValueError("Property catalog exceeds the size limit")
    catalog = PropertyCatalog.model_validate_json(path.read_text(encoding="utf-8"))
    if (
        catalog.location != settings.supported_location
        or catalog.currency != settings.currency
    ):
        raise ValueError(
            "Catalog location and currency must match the business configuration"
        )
    return catalog


def match_properties(
    catalog: PropertyCatalog, needs: RentalRequirements
) -> list[RentalProperty]:
    return sorted(
        (
            item
            for item in catalog.properties
            if (
                needs.max_monthly_rent is None
                or item.monthly_rent <= needs.max_monthly_rent
            )
            and (needs.bedrooms is None or item.bedrooms >= needs.bedrooms)
            and (not needs.pets or item.pets_allowed)
            and (
                not needs.neighborhood
                or item.neighborhood.casefold() == needs.neighborhood.casefold()
            )
        ),
        key=lambda item: (item.monthly_rent, item.id),
    )[:3]
