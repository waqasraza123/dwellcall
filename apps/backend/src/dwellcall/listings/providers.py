import csv
import hashlib
import io
import json
from decimal import Decimal
from typing import Any, Literal

from pydantic import ValidationError

from dwellcall.listings.contracts import ListingBatch, RowError
from dwellcall.listings.normalization import prepare_record
from dwellcall.listings.schemas import DiscoveryFilters, ListingRecord
from dwellcall.listings.settings import ListingSettings


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("DUPLICATE_JSON_KEYS")
    return result


class FileListingProvider:
    def __init__(self, content: bytes, format: Literal["csv", "json"], settings: ListingSettings, *, synthetic: bool = True) -> None:
        if len(content) > settings.listing_max_import_bytes:
            raise ValueError("IMPORT_TOO_LARGE")
        self.content, self.format, self.settings = content, format, settings
        self.synthetic = synthetic

    @staticmethod
    def _csv_agent(row: dict[str, str]) -> list[dict[str, Any]]:
        if not row.get("agent_name"):
            if any(value for key, value in row.items() if key.startswith("agent_")):
                raise ValueError("AGENT_NAME_REQUIRED")
            return []
        agent: dict[str, Any] = {"full_name": row["agent_name"]}
        for column, field in (("agent_source_id", "source_agent_id"), ("agent_brokerage", "brokerage"), ("agent_profile_url", "profile_url")):
            if row.get(column):
                agent[field] = row[column]
        contacts = []
        for column, kind in (("agent_email", "business_email"), ("agent_direct_phone", "direct_business_phone"), ("agent_office_phone", "office_phone"), ("agent_professional_mobile", "professional_mobile")):
            if row.get(column):
                if row.get("agent_contact_is_business", "").casefold() != "true":
                    raise ValueError("BUSINESS_CONTACT_PERMISSION_REQUIRED")
                contacts.append({
                    "kind": kind, "value": row[column], "published_as_business": True,
                    "direct": kind in {"direct_business_phone", "professional_mobile"} or (kind == "business_email" and row.get("agent_email_is_direct", "").casefold() == "true"),
                    "verification": "unverified", "source_reference": f"csv-column:{column}",
                })
        if contacts:
            agent["contacts"] = contacts
        return [agent]

    def fetch(self, checkpoint: str | None, filters: DiscoveryFilters) -> ListingBatch:
        try:
            text = self.content.decode("utf-8-sig")
            if self.format == "json":
                document = json.loads(text, object_pairs_hook=unique_object, parse_float=Decimal)
                if not isinstance(document, dict) or set(document) != {"synthetic", "listings"} or document["synthetic"] is not self.synthetic or not isinstance(document["listings"], list):
                    raise ValueError("SYNTHETIC_DOCUMENT_REQUIRED")
                rows = document["listings"]
            else:
                reader = csv.DictReader(io.StringIO(text, newline=""))
                fields = reader.fieldnames or []
                agent_fields = {"agent_name", "agent_source_id", "agent_brokerage", "agent_profile_url", "agent_email", "agent_direct_phone", "agent_office_phone", "agent_professional_mobile", "agent_contact_is_business", "agent_email_is_direct"}
                if not {"synthetic", "source_listing_id"} <= set(fields) or len(fields) != len(set(fields)) or not set(fields) <= (set(ListingRecord.model_fields) | agent_fields | {"synthetic"}):
                    raise ValueError("CSV_COLUMNS_INVALID")
                rows = []
                for row in reader:
                    if len(rows) >= self.settings.listing_max_import_records:
                        raise ValueError("IMPORT_RECORD_LIMIT")
                    if None in row:
                        raise ValueError("CSV_COLUMNS_INVALID")
                    rows.append(row)
        except (UnicodeError, json.JSONDecodeError, csv.Error, RecursionError):
            raise ValueError("IMPORT_FORMAT_INVALID") from None
        if len(rows) > self.settings.listing_max_import_records:
            raise ValueError("IMPORT_RECORD_LIMIT")
        records, errors = [], []
        for number, raw in enumerate(rows, start=1):
            try:
                if not isinstance(raw, dict):
                    raise ValueError("RECORD_INVALID")
                item = dict(raw)
                if self.format == "csv":
                    if str(item.pop("synthetic", "")).casefold() != ("true" if self.synthetic else "false"):
                        raise ValueError("SYNTHETIC_RECORD_REQUIRED")
                    item = {key: value for key, value in item.items() if value not in {None, ""}}
                    if "agents" in item and any(key.startswith("agent_") for key in item):
                        raise ValueError("CONFLICTING_AGENT_COLUMNS")
                    agents = self._csv_agent(item) if "agents" not in item else json.loads(item["agents"], object_pairs_hook=unique_object, parse_float=Decimal)
                    has_agent_fields = any(key.startswith("agent_") for key in item)
                    item = {key: value for key, value in item.items() if not key.startswith("agent_")}
                    if agents or has_agent_fields or "agents" in item:
                        item["agents"] = agents
                    if "metadata" in item:
                        item["metadata"] = json.loads(item["metadata"], object_pairs_hook=unique_object)
                record = ListingRecord.model_validate(prepare_record(item))
                records.append((number, record))
            except (ValidationError, ValueError, TypeError, RecursionError):
                errors.append(RowError(number, "RECORD_INVALID"))
        return ListingBatch(tuple(records), tuple(errors), hashlib.sha256(self.content).hexdigest(), len(rows), self.synthetic)


def provider_availability() -> list[dict[str, str | bool]]:
    return [
        {"provider": "file", "status": "implemented_unverified", "mode": "synthetic_or_authorized_live", "live_verified": False},
        {"provider": "licensed_feed", "status": "awaiting_authorized_connector", "mode": "live", "live_verified": False},
        *[{"provider": name, "status": "not_integrated", "mode": "live", "live_verified": False} for name in ("zillow", "realtor.com", "redfin", "homes.com")],
    ]
