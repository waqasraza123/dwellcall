import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal

from dwellcall.crm.contracts import AgentExportRequest
from dwellcall.listings.normalization import text_key

ObjectType = Literal["contacts", "companies", "deals"]


@dataclass(frozen=True)
class HubSpotField:
    object_type: ObjectType
    label: str
    type: str = "string"
    field_type: str = "text"
    unique: bool = False


FIELDS: dict[str, HubSpotField] = {
    "agent_id": HubSpotField("contacts", "DwellCall Agent ID", unique=True),
    "revision": HubSpotField("contacts", "DwellCall Revision"),
    "full_name": HubSpotField("contacts", "DwellCall Full Name"),
    "verified_email": HubSpotField("contacts", "DwellCall Verified Business Email"),
    "verified_phone": HubSpotField("contacts", "DwellCall Verified Professional Phone"),
    "brokerage": HubSpotField("contacts", "DwellCall Brokerage"),
    "listing_count": HubSpotField("contacts", "DwellCall Listing Count", "number", "number"),
    "primary_listing_url": HubSpotField("contacts", "DwellCall Primary Listing URL"),
    "property_locations": HubSpotField("contacts", "DwellCall Property Locations", field_type="textarea"),
    "listing_references": HubSpotField("contacts", "DwellCall Listing References", field_type="textarea"),
    "lead_source": HubSpotField("contacts", "DwellCall Lead Source"),
    "verification_status": HubSpotField("contacts", "DwellCall Verification Status"),
    "last_discovery": HubSpotField("contacts", "DwellCall Last Discovery", "datetime", "date"),
    "classification": HubSpotField("contacts", "DwellCall Classification"),
    "sources": HubSpotField("contacts", "DwellCall Contact Provenance", field_type="textarea"),
    "company_name": HubSpotField("companies", "DwellCall Brokerage Name"),
    "company_key": HubSpotField("companies", "DwellCall Company Key", unique=True),
    "deal_key": HubSpotField("deals", "DwellCall Deal Key", unique=True),
    "deal_listings": HubSpotField("deals", "DwellCall Listing References", field_type="textarea"),
}


def validate_fields(values: dict[str, str]) -> dict[str, str]:
    if set(values) - FIELDS.keys() or any(re.fullmatch(r"dwellcall_[a-z0-9_]{1,80}", name) is None for name in values.values()):
        raise ValueError("Map only supported keys to DwellCall-owned custom properties")
    for object_type in ("contacts", "companies", "deals"):
        names = [name for key, name in values.items() if FIELDS[key].object_type == object_type]
        if len(names) != len(set(names)):
            raise ValueError("Property names must be distinct within each HubSpot object")
    return values


def configured_fields(overrides: dict[str, str], *, deals: bool) -> dict[str, str]:
    validate_fields(overrides)
    return {key: overrides.get(key, "dwellcall_" + key) for key, spec in FIELDS.items() if deals or spec.object_type != "deals"}


def brokerage_key(brokerage: str) -> str:
    return hashlib.sha256(text_key(brokerage).encode()).hexdigest()


def listing_references(request: AgentExportRequest) -> str:
    return json.dumps([{"listing_id": str(item.listing_id), "source": item.source_key,
                        "reference": item.source_listing_id, "url": item.listing_url}
                       for item in request.snapshot.properties], sort_keys=True, separators=(",", ":"))


def owned_properties(request: AgentExportRequest, lead_source: str, classifications: tuple[str, ...]) -> dict[str, str]:
    snapshot = request.snapshot
    locations = sorted({", ".join(filter(None, (item.street_address, item.city, item.state, item.postal_code))) for item in snapshot.properties} - {""})
    values = {
        "agent_id": str(snapshot.agent_id), "full_name": snapshot.full_name,
        "verified_email": snapshot.email or "", "verified_phone": snapshot.phone or "",
        "brokerage": snapshot.brokerage or "", "listing_count": str(len({item.listing_id for item in snapshot.properties})),
        "primary_listing_url": next((item.listing_url for item in snapshot.properties if item.listing_url), ""),
        "property_locations": json.dumps(locations, separators=(",", ":")), "listing_references": listing_references(request),
        "lead_source": lead_source, "verification_status": "verified_business_contact",
        "classification": ";".join(classifications), "sources": json.dumps(snapshot.contact_references, sort_keys=True, separators=(",", ":")),
    }
    if snapshot.last_discovered_at:
        values["last_discovery"] = str(int(snapshot.last_discovered_at.timestamp() * 1000))
    if any(len(value.encode()) > 50000 for value in values.values()):
        raise ValueError("HUBSPOT_FIELD_CAPACITY_EXCEEDED")
    return {request.fields[key]: value for key, value in values.items()}
