import pytest
from pydantic import ValidationError

from dwellcall.settings import ApiSettings
from dwellcall.telephony.outbound.destinations import normalize_phone_number, validate_destination
from dwellcall.errors import ApiError
from tests.outbound.helpers import call_input
from dwellcall.telephony.outbound.schemas import CarrierEndedInput


@pytest.mark.parametrize(("value", "expected"), [("+1 (202) 555-0124", "+12025550124"), ("+44 20 7946 0018", "+442079460018")])
def test_normalization_is_canonical_before_fingerprints(value: str, expected: str) -> None:
    assert normalize_phone_number(value) == expected


@pytest.mark.parametrize("value", ["2025550124", "+1", "+12025550124 ext 5", "sip:+12025550124", "+12025550124;123", "+999555555555"])
def test_ambiguous_or_nontelephone_destinations_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_phone_number(value)


@pytest.mark.parametrize("field", ["consent", "recipient_consent_confirmed", "do_not_call_checked"])
@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_consent_is_explicit_and_purpose_specific(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        call_input(**{field: value})
    with pytest.raises(ValidationError):
        call_input(consent_version="listing-discovery-permission")


def test_international_calls_remain_disabled_until_separately_confirmed(outbound_settings: ApiSettings) -> None:
    with pytest.raises(ApiError):
        validate_destination("+923001234567", outbound_settings.outbound_allowed_countries)
    with pytest.raises(ValidationError):
        ApiSettings.model_validate({**outbound_settings.model_dump(), "outbound_allowed_countries": ["US", "PK"]})


def test_live_mock_and_transfer_gates(outbound_settings: ApiSettings) -> None:
    for update in [
        {"outbound_mock_enabled": True}, {"outbound_transfer_enabled": True},
        {"outbound_reserved_cost_cents": 0}, {"outbound_from_number": "+12025550124"},
        {"outbound_max_duration_seconds": 181}, {"outbound_destination_permissions_confirmed": False},
        {"outbound_daily_limit": 6}, {"outbound_number_daily_limit": 2},
    ]:
        with pytest.raises(ValidationError):
            ApiSettings.model_validate({**outbound_settings.model_dump(), **update})


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_carrier_completion_requires_explicit_boolean_confirmation(value: object) -> None:
    with pytest.raises(ValidationError):
        CarrierEndedInput.model_validate({"all_carrier_legs_ended": value})
