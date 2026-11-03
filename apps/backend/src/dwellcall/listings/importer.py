import argparse
import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from dwellcall.crm.settings import CrmSettings
from dwellcall.crm.job_execution import JobDeadlineExceeded, create_job_engine
from dwellcall.errors import ApiError
from dwellcall.listings.registry import SYNTHETIC_SOURCE_KEY, SourceRegistryService
from dwellcall.listings.schemas import DiscoveryFilters
from dwellcall.listings.service import ListingIngestionService
from dwellcall.listings.settings import ListingSettings
from dwellcall.settings import DatabaseConnectionSettings


def main() -> None:
    parser = argparse.ArgumentParser(prog="dwellcall-listing-import")
    parser.add_argument("--file", type=Path)
    parser.add_argument("--source", default=SYNTHETIC_SOURCE_KEY)
    parser.add_argument("--request-id", type=UUID)
    parser.add_argument("--filters", type=Path, help="Optional local DiscoveryFilters JSON document")
    parser.add_argument("--purge-expired", action="store_true")
    args = parser.parse_args()
    if not args.purge_expired and (args.file is None or args.request_id is None):
        parser.error("--file and --request-id are required for an import")
    engine = None
    try:
        settings = ListingSettings()
        engine = create_job_engine(DatabaseConnectionSettings())
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        result: dict[str, object]
        if args.purge_expired:
            result = {**SourceRegistryService(sessions).purge(args.source)}
        else:
            suffix = args.file.suffix.lower()
            if suffix not in {".json", ".csv"}:
                raise ValueError("Unsupported file format")
            format: Literal["json", "csv"] = "json" if suffix == ".json" else "csv"
            with args.file.open("rb") as stream:
                content = stream.read(settings.listing_max_import_bytes + 1)
            filters = DiscoveryFilters()
            if args.filters is not None:
                with args.filters.open("rb") as stream:
                    body = stream.read(16385)
                if len(body) > 16384:
                    raise ValueError("Filter file too large")
                filters = DiscoveryFilters.model_validate_json(body)
            result = ListingIngestionService(sessions, settings, CrmSettings()).ingest(args.source, content, format, args.request_id, filters)
        print(json.dumps(result))
    except (ValueError, OSError, SQLAlchemyError, JobDeadlineExceeded, ApiError):
        parser.exit(1, "Listing operation unavailable or invalid; no external provider was contacted. Review configuration and retry the same import request ID.\n")
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    main()
