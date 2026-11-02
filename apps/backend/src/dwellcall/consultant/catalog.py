from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dwellcall.settings import ApiSettings


Scenario = Literal["renting", "buying", "luxury"]


class Property(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=100)
    neighborhood: str = Field(min_length=1, max_length=100)
    scenarios: tuple[Scenario, ...] = Field(default=("renting",), min_length=1)
    monthly_rent: int | None = Field(default=None, gt=0, le=10_000_000)
    purchase_price: int | None = Field(default=None, gt=0, le=1_000_000_000)
    bedrooms: int = Field(ge=0, le=20)
    bathrooms: float = Field(gt=0, le=20)
    pets_allowed: bool | None = None
    features: tuple[str, ...] = Field(max_length=12)

    @field_validator("features")
    @classmethod
    def bounded_features(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() or len(value) > 120 for value in values):
            raise ValueError("Features must be nonempty and at most 120 characters")
        return values

    @model_validator(mode="after")
    def scenario_prices(self) -> Self:
        if len(set(self.scenarios)) != len(self.scenarios):
            raise ValueError("Property scenarios must be unique")
        if "renting" in self.scenarios and self.monthly_rent is None:
            raise ValueError("Rental examples require monthly_rent")
        if any(item in self.scenarios for item in ("buying", "luxury")) and self.purchase_price is None:
            raise ValueError("Purchase examples require purchase_price")
        return self

    def price_for(self, scenario: Scenario) -> int | None:
        return self.monthly_rent if scenario == "renting" else self.purchase_price


class PropertyCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fictional: Literal[True]
    location: str = Field(min_length=1, max_length=100)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    properties: list[Property] = Field(min_length=1, max_length=100)

    @field_validator("fictional", mode="before")
    @classmethod
    def fictional_only(cls, value: object) -> object:
        if value is not True:
            raise ValueError("This demonstration requires fictional properties")
        return value

    @property
    def scenarios(self) -> tuple[Scenario, ...]:
        available = {scenario for item in self.properties for scenario in item.scenarios}
        ordered: tuple[Scenario, ...] = ("renting", "buying", "luxury")
        return tuple(item for item in ordered if item in available)

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        if len({item.id for item in self.properties}) != len(self.properties):
            raise ValueError("Property IDs must be unique")
        return self


class PropertyRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    scenario: Scenario | None = None
    max_budget: int | None = Field(default=None, ge=1, le=1_000_000_000)
    bedrooms: int | None = Field(default=None, ge=0, le=20)
    location: str | None = Field(default=None, min_length=1, max_length=100)
    neighborhood: str | None = Field(default=None, min_length=1, max_length=100)
    move_in: str | None = Field(default=None, min_length=1, max_length=100)
    pets: bool | None = None
    must_have: tuple[str, ...] = Field(default=(), max_length=12)

    @field_validator("must_have")
    @classmethod
    def bounded_priorities(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() or len(value) > 120 for value in values):
            raise ValueError("Requirements must be nonempty and at most 120 characters")
        return tuple(sorted(set(values), key=str.casefold))

    @property
    def ready(self) -> bool:
        return all(value is not None for value in (self.scenario, self.max_budget, self.bedrooms))


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


def property_matches(
    item: Property, catalog: PropertyCatalog, needs: PropertyRequirements,
) -> bool:
    scenario, budget = needs.scenario, needs.max_budget
    if not needs.ready or scenario is None or budget is None:
        return False
    if needs.location and needs.location.casefold() != catalog.location.casefold():
        return False
    price = item.price_for(scenario)
    return (
        scenario in item.scenarios and price is not None and price <= budget
        and (needs.bedrooms is None or item.bedrooms >= needs.bedrooms)
        and (scenario != "renting" or not needs.pets or item.pets_allowed is True)
        and (not needs.neighborhood or item.neighborhood.casefold() == needs.neighborhood.casefold())
        and all(
            value.casefold() in {feature.casefold() for feature in item.features}
            for value in needs.must_have
        )
    )


def match_properties(
    catalog: PropertyCatalog, needs: PropertyRequirements
) -> list[Property]:
    scenario = needs.scenario
    if scenario is None:
        return []
    return sorted(
        (item for item in catalog.properties if property_matches(item, catalog, needs)),
        key=lambda item: (item.price_for(scenario) or 0, item.id),
    )[:3]


def compare_properties(
    catalog: PropertyCatalog, ids: tuple[str, ...], needs: PropertyRequirements,
) -> list[dict[str, object]]:
    scenario = needs.scenario
    if scenario is None:
        return []
    return [
        {**item.model_dump(mode="json"),
         "comparison_price": item.price_for(scenario),
         "budget_period": "monthly" if scenario == "renting" else "purchase",
         "fits_current_requirements": property_matches(item, catalog, needs) if needs.ready else None}
        for item in catalog.properties
        if item.id in ids[:3] and scenario in item.scenarios
    ]
