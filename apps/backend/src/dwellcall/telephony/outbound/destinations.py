import re

import phonenumbers

from dwellcall.errors import ApiError

E164 = re.compile(r"\+[1-9][0-9]{7,14}\Z")


def normalize_phone_number(value: str) -> str:
    value = value.strip()
    if not value.startswith("+") or re.fullmatch(r"\+[0-9 ().-]+", value) is None:
        raise ValueError("Include the country code with +; extensions are not supported")
    try:
        number = phonenumbers.parse(value, None)
    except phonenumbers.NumberParseException:
        raise ValueError("Use a complete international telephone number") from None
    normalized = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
    if number.extension or not E164.fullmatch(normalized) or not phonenumbers.is_valid_number(number):
        raise ValueError("Use a valid telephone numbering range without an extension")
    if phonenumbers.number_type(number) not in {
        phonenumbers.PhoneNumberType.FIXED_LINE,
        phonenumbers.PhoneNumberType.MOBILE,
        phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE,
    }:
        raise ValueError("Only mobile and landline destinations are supported")
    return normalized


def destination_country(value: str) -> str:
    return phonenumbers.region_code_for_number(phonenumbers.parse(value, None)) or "ZZ"


def validate_destination(value: str, countries: frozenset[str]) -> None:
    if destination_country(value) != "US" or "US" not in countries:
        raise ApiError(status_code=422, code="OUTBOUND_DESTINATION_UNSUPPORTED",
                       message="Outbound calling is restricted to US destinations")
