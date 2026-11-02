import pytest

from dwellcall.consultant.catalog import (
    Property, PropertyRequirements, compare_properties, load_catalog, match_properties,
)
from dwellcall.settings import ApiSettings


def needs(**updates: object) -> PropertyRequirements:
    values: dict[str, object] = {
        "scenario": "renting", "max_budget": 2300, "bedrooms": 1, "neighborhood": None,
        "move_in": None, "pets": None,
    }
    return PropertyRequirements.model_validate({**values, **updates})


def test_budget_bedrooms_and_pets_are_hard_filters(settings: ApiSettings) -> None:
    catalog = load_catalog(settings)
    assert [p.id for p in match_properties(catalog, needs(
        max_budget=2300, bedrooms=1, pets=True,
    ))] == ["rental-willow-flat"]
    assert match_properties(catalog, needs(max_budget=2000, bedrooms=2)) == []
    assert match_properties(catalog, needs(neighborhood="Unlisted district")) == []


def test_catalog_must_match_configured_business_location(settings: ApiSettings) -> None:
    changed = settings.model_copy(update={"supported_location": "Another location"})
    with pytest.raises(ValueError, match="must match"):
        load_catalog(changed)


def test_buying_and_luxury_use_purchase_prices_without_mixing_rent(settings: ApiSettings) -> None:
    catalog = load_catalog(settings)
    buying = needs(scenario="buying", max_budget=600000, bedrooms=3)
    assert [item.id for item in match_properties(catalog, buying)] == ["purchase-maple-residence"]
    luxury = needs(scenario="luxury", max_budget=2000000, bedrooms=3, must_have=["Private pool"])
    assert [item.id for item in match_properties(catalog, luxury)] == ["luxury-juniper-estate"]
    assert match_properties(catalog, needs(scenario="buying", max_budget=2300)) == []


def test_unknown_location_or_feature_is_not_silently_relaxed(settings: ApiSettings) -> None:
    catalog = load_catalog(settings)
    assert match_properties(catalog, needs(location="Another city")) == []
    assert match_properties(catalog, needs(must_have=["Undocumented feature"])) == []
    assert match_properties(catalog, PropertyRequirements()) == []


def test_comparison_marks_over_budget_and_ignores_fabricated_ids(settings: ApiSettings) -> None:
    catalog = load_catalog(settings)
    comparison = compare_properties(catalog, (
        "luxury-juniper-estate", "luxury-sky-residence", "invented-listing",
    ), needs(scenario="luxury", max_budget=2000000, bedrooms=3))
    assert len(comparison) == 2
    assert comparison[0]["fits_current_requirements"] is True
    assert comparison[1]["fits_current_requirements"] is False
    assert comparison[1]["comparison_price"] == 2450000
    assert all(item["budget_period"] == "purchase" for item in comparison)


def test_catalog_requires_a_price_for_each_scenario() -> None:
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Property.model_validate({
            "id": "example", "name": "Example", "neighborhood": "Example",
            "scenarios": ["buying"], "monthly_rent": 2000,
            "bedrooms": 2, "bathrooms": 1, "features": [],
        })


def test_business_location_currency_and_catalog_are_configurable(
    settings: ApiSettings, tmp_path,
) -> None:
    catalog = load_catalog(settings)
    configured = catalog.model_copy(update={"location": "Lahore", "currency": "PKR"})
    path = tmp_path / "properties.json"
    path.write_text(configured.model_dump_json(), encoding="utf-8")
    replacement = settings.model_copy(update={
        "business_name": "Example Property Desk", "supported_location": "Lahore",
        "currency": "PKR", "property_catalog_path": path,
    })
    assert load_catalog(replacement).location == "Lahore"
    assert match_properties(load_catalog(replacement), needs(location="Lahore"))
