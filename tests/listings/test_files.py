import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from dwellcall.listings.normalization import address_key, matches_filters
from dwellcall.listings.permissions import verification_status
from dwellcall.listings.providers import FileListingProvider, provider_availability
from dwellcall.listings.registry import SYNTHETIC_PERMISSION
from dwellcall.listings.schemas import (
    BusinessContact,
    DiscoveryFilters,
    SourcePermissionInput,
)
from dwellcall.listings.settings import ListingSettings

DATA = Path(__file__).resolve().parents[2] / "data" / "listings"


def parse(content: bytes, format: str = "json"):
    return FileListingProvider(content, format, ListingSettings()).fetch(
        None, DiscoveryFilters(),
    )


@pytest.mark.parametrize("format, count", [("json", 3), ("csv", 2)])
def test_bundled_files_are_usable_synthetic_inputs(format: str, count: int) -> None:
    batch = parse((DATA / f"synthetic-listings.{format}").read_bytes(), format)
    assert batch.synthetic is True
    assert batch.received == len(batch.records) == count
    assert batch.errors == ()
    assert all(record.country == "US" for _, record in batch.records)


def test_missing_fields_remain_unknown_and_coagents_are_preserved() -> None:
    batch = parse((DATA / "synthetic-listings.json").read_bytes())
    assert len(batch.records[1][1].agents) == 2
    assert batch.records[2][1].listing_date is None
    assert batch.records[2][1].agents[0].contacts == ()
    assert "listing_date" not in batch.records[2][1].model_fields_set


def test_decimal_normalization_and_missing_fields_are_not_guessed() -> None:
    content = json.dumps({"synthetic": True, "listings": [{
        "source_listing_id": "demo", "city": "  Austin  ", "state": "tx",
        "price": "685,000.00", "currency": "usd",
    }]}).encode()
    record = parse(content).records[0][1]
    assert record.price == Decimal("685000.00")
    assert (record.city, record.state, record.currency) == ("Austin", "TX", "USD")
    assert record.country is None


@pytest.mark.parametrize("content", [
    b'{"synthetic":false,"listings":[]}',
    b'{"synthetic":true,"synthetic":true,"listings":[]}',
    b'[{"source_listing_id":"x"}]',
    b'{"synthetic":true,"listings":[],"extra":"not accepted"}',
    b'not json',
])
def test_invalid_envelopes_are_rejected(content: bytes) -> None:
    with pytest.raises(ValueError):
        parse(content)


def test_bad_rows_are_reported_without_echoing_the_payload() -> None:
    batch = parse(json.dumps({"synthetic": True, "listings": [
        {"source_listing_id": "valid"},
        {"source_listing_id": "invalid", "private_contact": "do-not-echo"},
        {"source_listing_id": "private-url", "listing_url": "http://127.0.0.1/"},
    ]}).encode())
    assert len(batch.records) == 1
    assert [(error.row, error.code) for error in batch.errors] == [
        (2, "RECORD_INVALID"), (3, "RECORD_INVALID"),
    ]
    assert "do-not-echo" not in repr(batch.errors)


def test_csv_does_not_accept_unattested_business_contacts_or_guess_country() -> None:
    batch = parse(
        b"synthetic,source_listing_id,agent_name,agent_email,agent_direct_phone\n"
        b"true,one,Demo Agent,agent@example.com,5125550101\n", "csv",
    )
    assert not batch.records
    assert batch.errors[0].code == "RECORD_INVALID"


def test_csv_retains_omitted_agents_but_can_explicitly_clear_them() -> None:
    batch = parse(b'synthetic,source_listing_id,agents\ntrue,one,[]\n', "csv")
    record = batch.records[0][1]
    assert "agents" in record.model_fields_set
    assert record.agents == ()
    plain = parse(b"synthetic,source_listing_id\ntrue,one\n", "csv")
    assert "agents" not in plain.records[0][1].model_fields_set


def test_record_limit_is_enforced_before_ingestion() -> None:
    content = json.dumps({"synthetic": True, "listings": [
        {"source_listing_id": "a"}, {"source_listing_id": "b"},
    ]}).encode()
    with pytest.raises(ValueError):
        FileListingProvider(content, "json", ListingSettings(
            listing_max_import_records=1,
        )).fetch(None, DiscoveryFilters())


def test_filters_exclude_unknown_prices_and_currency_mismatches() -> None:
    filters = DiscoveryFilters(min_price=100, max_price=1000)
    assert not matches_filters({}, filters)
    assert not matches_filters({"price": "500", "currency": "CAD"}, filters)
    assert matches_filters({"price": "500", "currency": "USD"}, filters)


def test_unit_information_is_not_removed_from_address_keys() -> None:
    common = {"city": "Austin", "state": "TX", "postal_code": "78704", "country": "US"}
    assert address_key({**common, "street_address": "1 Demo Way Unit 1"}) != address_key(
        {**common, "street_address": "1 Demo Way Unit 2"},
    )


def test_verification_is_a_source_claim_and_demo_data_never_becomes_real_verified() -> None:
    contact = BusinessContact(
        kind="business_email", value="demo@example.com", direct=True,
        published_as_business=True, verification="verified",
        verified_at=datetime.now(UTC), source_reference="synthetic-evidence",
    )
    policy = SourcePermissionInput.model_validate(SYNTHETIC_PERMISSION)
    assert verification_status(contact, policy) == "synthetic_verified"
    assert verification_status(contact, policy.model_copy(update={
        "trusted_verification": False,
    })) == "unverified"
    with pytest.raises(ValidationError):
        BusinessContact.model_validate({
            **contact.model_dump(), "published_as_business": "true",
        })


def test_provider_status_does_not_advertise_any_live_connector() -> None:
    assert all(provider["live_verified"] is False for provider in provider_availability())
    assert next(p for p in provider_availability() if p["provider"] == "zillow")["status"] == "not_integrated"
