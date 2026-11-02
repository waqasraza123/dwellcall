import pytest

from dwellcall.consultant.catalog import RentalRequirements, load_catalog, match_properties
from dwellcall.settings import ApiSettings


def needs(**updates: object) -> RentalRequirements:
    values: dict[str, object] = {
        "max_monthly_rent": None, "bedrooms": None, "neighborhood": None,
        "move_in": None, "pets": None,
    }
    return RentalRequirements.model_validate({**values, **updates})


def test_budget_bedrooms_and_pets_are_hard_filters(settings: ApiSettings) -> None:
    catalog = load_catalog(settings)
    assert [p.id for p in match_properties(catalog, needs(
        max_monthly_rent=2300, bedrooms=1, pets=True,
    ))] == ["rental-willow-flat"]
    assert match_properties(catalog, needs(max_monthly_rent=2000, bedrooms=2)) == []
    assert match_properties(catalog, needs(neighborhood="Unlisted district")) == []


def test_catalog_must_match_configured_business_location(settings: ApiSettings) -> None:
    changed = settings.model_copy(update={"supported_location": "Another location"})
    with pytest.raises(ValueError, match="must match"):
        load_catalog(changed)
