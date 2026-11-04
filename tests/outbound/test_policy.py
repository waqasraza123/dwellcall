import pytest
from pydantic import ValidationError

from dwellcall.settings import ApiSettings
from dwellcall.telephony.outbound.destinations import normalize_phone_number, validate_destination
from dwellcall.errors import ApiError
from tests.outbound.helpers import call_input
from dwellcall.telephony.outbound.schemas import CarrierEndedInput, ControlsInput


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


@pytest.mark.parametrize("number", ["+442079460018", "+14165550124"])
def test_only_us_destinations_are_supported_even_with_international_flags(outbound_settings: ApiSettings, number: str) -> None:
    with pytest.raises(ApiError):
        validate_destination(number, frozenset({"US", "GB", "CA"}))
    with pytest.raises(ValidationError):
        ApiSettings.model_validate({**outbound_settings.model_dump(), "outbound_allowed_countries": ["US", "GB"], "outbound_confirmed_international_countries": ["GB"]})


def test_transfer_cannot_be_activated_by_configuration_attestations(outbound_settings: ApiSettings) -> None:
    with pytest.raises(ValidationError, match="Outbound transfer is disabled"):
        ApiSettings.model_validate({
            **outbound_settings.model_dump(), "outbound_transfer_enabled": True,
            "outbound_human_number": "+12025550125", "outbound_transfer_compatibility_confirmed": True,
            "outbound_transfer_carrier_limit_confirmed": True, "outbound_transfer_reserved_cost_cents": 100,
        })


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_operator_controls_cannot_enable_human_transfers(value: object) -> None:
    with pytest.raises(ValidationError):
        ControlsInput.model_validate({"calls_paused": False, "transfers_paused": value})


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
