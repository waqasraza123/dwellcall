"""Bounded, owner-invoked polling of bundled synthetic discovery jobs."""
import argparse
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from dwellcall.crm.settings import CrmSettings
from dwellcall.database.connection import create_database_engine
from dwellcall.database.models.workspace import DiscoveryAttempt, DiscoveryJob
from dwellcall.errors import ApiError
from dwellcall.listings.registry import SYNTHETIC_SOURCE_KEY
from dwellcall.listings.settings import ListingSettings
from dwellcall.settings import ApiSettings
from dwellcall.workspace_routes import DiscoveryService, RunInput


def poll_due_jobs(sessions: sessionmaker[Session], listing: ListingSettings, crm: CrmSettings, *, max_jobs: int = 5) -> list[dict[str, object]]:
    if not listing.listing_intelligence_enabled:
        return []
    if not 1 <= max_jobs <= 10:
        raise ValueError("A bounded batch of 1–10 jobs is required")
    now = datetime.now(UTC)
    with sessions() as session:
        last_started = select(func.max(DiscoveryAttempt.started_at)).where(DiscoveryAttempt.job_id == DiscoveryJob.id).correlate(DiscoveryJob).scalar_subquery()
        jobs = session.execute(select(DiscoveryJob.id, DiscoveryJob.poll_interval_minutes, last_started).where(
            DiscoveryJob.enabled.is_(True), DiscoveryJob.source_key == SYNTHETIC_SOURCE_KEY,
            or_(last_started.is_(None), last_started + DiscoveryJob.poll_interval_minutes * text("INTERVAL '1 minute'") <= now),
        ).order_by(last_started.asc().nulls_first(), DiscoveryJob.created_at, DiscoveryJob.id).limit(max_jobs)).all()
    service = DiscoveryService(sessions, listing, crm)
    results: list[dict[str, object]] = []
    for job_id, minutes, last in jobs:
        if len(results) >= max_jobs:
            break
        if last is not None and last + timedelta(minutes=minutes) > now:
            continue
        try:
            result = service.run(job_id, uuid4(), RunInput(), only_if_due=True)
            results.append({"job_id": str(job_id), "status": result["status"], "code": result.get("code")})
        except ApiError as error:
            results.append({"job_id": str(job_id), "status": "blocked", "code": error.code})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-jobs", type=int, choices=range(1, 11), default=5)
    arguments = parser.parse_args()
    api, listing, crm = ApiSettings(), ListingSettings(), CrmSettings()
    engine = create_database_engine(api, service_name="discovery-poll")
    try:
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        print(json.dumps({"mode": "synthetic_only", "results": poll_due_jobs(sessions, listing, crm, max_jobs=arguments.max_jobs)}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
