import hashlib
import json
import re
import unicodedata
from typing import Any

from dwellcall.listings.schemas import DiscoveryFilters


def normalize_display_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def text_key(value: str) -> str:
    return normalize_display_text(value).casefold()


def address_key(data: dict[str, Any]) -> str | None:
    fields = ("street_address", "city", "state", "postal_code", "country")
    if any(not data.get(key) for key in fields):
        return None
    return fingerprint([re.sub(r"[^\w\s#-]", " ", text_key(str(data[key]))).split() for key in fields])


def prepare_record(data: dict[str, Any]) -> dict[str, Any]:
    result = dict(data)
    for key in ("street_address", "city"):
        if isinstance(result.get(key), str):
            result[key] = normalize_display_text(result[key])
    for key in ("state", "country", "currency"):
        if isinstance(result.get(key), str):
            result[key] = result[key].strip().upper()
    for key in ("status", "property_type", "listing_type"):
        if isinstance(result.get(key), str):
            result[key] = result[key].strip().casefold().replace("-", "_").replace(" ", "_")
    price = result.get("price")
    if isinstance(price, str) and re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d{1,2})?", price.strip()):
        result["price"] = price.strip().replace(",", "")
    if isinstance(result.get("agents"), list):
        result["agents"] = [
            {**agent, **{key: normalize_display_text(agent[key]) for key in ("full_name", "brokerage") if isinstance(agent.get(key), str)}}
            if isinstance(agent, dict) else agent for agent in result["agents"]
        ]
    return result


def matches_filters(data: dict[str, Any], filters: DiscoveryFilters) -> bool:
    from decimal import Decimal
    for field, choices in (
        ("state", filters.states), ("city", filters.cities),
        ("postal_code", filters.postal_codes), ("property_type", filters.property_types),
        ("status", filters.statuses), ("listing_type", filters.listing_types),
    ):
        if choices and text_key(str(data.get(field) or "")) not in {text_key(value) for value in choices}:
            return False
    if filters.min_price is not None or filters.max_price is not None:
        if data.get("price") is None or data.get("currency") != filters.currency:
            return False
        price = Decimal(str(data["price"]))
        if filters.min_price is not None and price < filters.min_price:
            return False
        if filters.max_price is not None and price > filters.max_price:
            return False
    return True


