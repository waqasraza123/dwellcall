from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from dwellcall.crm.settings import CrmSettings
from dwellcall.database.models import ListingSource
from dwellcall.database.models.workspace import DiscoveryAttempt, DiscoveryJob
from dwellcall.errors import ApiError
from dwellcall.listings.queries import ListingQueries
from dwellcall.listings.registry import SYNTHETIC_SOURCE_KEY
from dwellcall.listings.settings import ListingSettings
from dwellcall.operator_actions import reserve_operator_action
from dwellcall.workspace_queries import WorkspaceQueries
from dwellcall.workspace_routes import DiscoveryService, JobInput, RunInput


def test_job_survives_refresh_rejects_stale_edits_and_replays_run(sessions):
    service = DiscoveryService(sessions, ListingSettings(), CrmSettings())
    job = service.save(JobInput(name="Demo market", source_key=SYNTHETIC_SOURCE_KEY))
    job_id = UUID(job["id"])
    with sessions() as session:
        assert session.get(DiscoveryJob, job_id).name == "Demo market"
    with pytest.raises(ApiError) as conflict:
        service.save(JobInput(name="Stale", source_key=SYNTHETIC_SOURCE_KEY), job_id)
    assert conflict.value.code == "JOB_CHANGED"
    request_id = uuid4()
    first = service.run(job_id, request_id, RunInput())
    second = service.run(job_id, request_id, RunInput())
    assert first["id"] == second["id"]
    with sessions() as session:
        assert len(list(session.scalars(select(DiscoveryAttempt)))) == 1
    assert job["scheduling_active"] is False


def test_duplicate_action_is_reserved_durably_before_mutation(sessions):
    key = str(uuid4())
    reserve_operator_action(sessions, key, "POST /crm/process", b"{}")
    with pytest.raises(ApiError) as conflict:
        reserve_operator_action(sessions, key, "POST /crm/process", b"{}")
    assert conflict.value.code == "ACTION_ALREADY_SUBMITTED"


def test_current_source_rights_control_filter_results_details_and_metrics(sessions):
    service = DiscoveryService(sessions, ListingSettings(), CrmSettings())
    job = service.save(JobInput(name="Demo", source_key=SYNTHETIC_SOURCE_KEY))
    outcome = service.run(UUID(job["id"]), uuid4(), RunInput())
    assert outcome["status"] in {"completed", "partial"}
    queries = ListingQueries(sessions)
    page = queries.listings(1, 25, "synthetic", q="Austin", sort="price_asc")
    assert page["total"] > 0
    workspace = WorkspaceQueries(sessions, CrmSettings())
    assert workspace.dashboard("synthetic")["metrics"]["verified_agents"] == 0
    listing_id = UUID(page["items"][0]["id"])
    assert workspace.listing(listing_id, "synthetic")["id"] == str(listing_id)
    with sessions() as session, session.begin():
        source = session.get(ListingSource, SYNTHETIC_SOURCE_KEY)
        source.permission = {**source.permission, "display_allowed": False}
    assert queries.listings(1, 25, "synthetic", q="Austin")["total"] == 0
    assert workspace.dashboard("synthetic")["metrics"]["listings"] == 0
    with pytest.raises(ApiError):
        workspace.listing(listing_id, "synthetic")


def test_disabled_discovery_job_cannot_run(sessions):
    service = DiscoveryService(sessions, ListingSettings(), CrmSettings())
    job = service.save(JobInput(name="Disabled", source_key=SYNTHETIC_SOURCE_KEY, enabled=False))
    with pytest.raises(ApiError) as blocked:
        service.run(UUID(job["id"]), uuid4(), RunInput())
    assert blocked.value.code == "JOB_DISABLED"


def test_demo_polling_respects_frequency_and_does_not_repeat_due_job(sessions):
    from dwellcall.discovery_worker import poll_due_jobs

    service = DiscoveryService(sessions, ListingSettings(), CrmSettings())
    service.save(JobInput(name="Demo polling", source_key=SYNTHETIC_SOURCE_KEY, poll_interval_minutes=60))
    first = poll_due_jobs(sessions, ListingSettings(), CrmSettings(), max_jobs=1)
    second = poll_due_jobs(sessions, ListingSettings(), CrmSettings(), max_jobs=1)
    assert len(first) == 1
    assert second == []
