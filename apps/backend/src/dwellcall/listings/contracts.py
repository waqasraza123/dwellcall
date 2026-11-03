from dataclasses import dataclass
from typing import Protocol

from dwellcall.listings.schemas import DiscoveryFilters, ListingRecord


@dataclass(frozen=True)
class RowError:
    row: int
    code: str


@dataclass(frozen=True)
class ListingBatch:
    records: tuple[tuple[int, ListingRecord], ...]
    errors: tuple[RowError, ...]
    checkpoint: str
    received: int
    synthetic: bool


class ListingProvider(Protocol):
    def fetch(self, checkpoint: str | None, filters: DiscoveryFilters) -> ListingBatch: ...


@dataclass(frozen=True)
class LicensedFeedConfiguration:
    provider_name: str
    permission_source_key: str
    credential_environment_name: str
    resource: str


class LicensedListingProvider(ListingProvider, Protocol):
    """Future documented/licensed connector; no portal or RESO access is claimed."""

    configuration: LicensedFeedConfiguration
