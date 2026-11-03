import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from dwellcall.crm.agent_jobs import process_agent_jobs, reconcile_job, recover
from dwellcall.crm.agent_mapping import AgentIneligible, export_snapshot
from dwellcall.crm.agent_schemas import GhlSetupInput
from dwellcall.crm.agent_service import AgentCrmService, destination_state
from dwellcall.crm.contracts import AgentDeliveryResult
from dwellcall.crm.ghl_setup import GhlConfigurationService
from dwellcall.crm.providers.gohighlevel import FIELD_DEFINITIONS, GoHighLevelProvider
from dwellcall.database.models import (
    AgentCrmAudit, AgentCrmDestination, AgentCrmJob, AgentCrmLink,
    ListingAgent, ListingContactEvidence, ListingReview, ListingSource,
)
from dwellcall.errors import ApiError
from dwellcall.listings.registry import SYNTHETIC_PERMISSION, SourceRegistryService
from dwellcall.listings.schemas import SourcePermissionInput
from dwellcall.listings.service import ListingIngestionService, ingestion_lock
from dwellcall.listings.settings import ListingSettings

SOURCE = "authorized-test-files"


@pytest.fixture
def live_record():
    row = json.loads((Path(__file__).resolve().parents[2] / "data/listings/synthetic-listings.json").read_text())["listings"][0]
    row["source_updated_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    for contact in row["agents"][0]["contacts"]:
        contact.update(verification="verified", verified_at=datetime.now(UTC).isoformat())
    return row


@pytest.fixture
def prepared(sessions, ghl_settings, live_record):
    policy = SourcePermissionInput.model_validate({**SYNTHETIC_PERMISSION, "data_mode": "live", "export_allowed": True})
    SourceRegistryService(sessions).configure(SOURCE, policy)
    with sessions() as session, session.begin():
        ingestion_lock(session)
        state = destination_state(session, ghl_settings)
        state.configured_at = datetime.now(UTC)
    import_live(sessions, ghl_settings, [live_record])
    with sessions() as session:
        return session.scalar(select(ListingAgent.id))


def import_live(sessions, settings, rows, request_id=None):
    return ListingIngestionService(sessions, ListingSettings(), settings).ingest(
        SOURCE, json.dumps({"synthetic": False, "listings": rows}).encode(), "json", request_id or uuid4(),
    )


def test_multiple_listings_queue_one_identity_and_update_existing_contact(sessions, ghl_settings, prepared, live_record):
    second = deepcopy(live_record)
    second.update(source_listing_id="second", listing_reference="SECOND", street_address="2 Fictional Way")
    import_live(sessions, ghl_settings, [second])
    service = AgentCrmService(sessions, ghl_settings)
    first = service.queue([prepared])[0]
    assert service.queue([prepared])[0].id == first.id
    with sessions() as session:
        snapshot = export_snapshot(session, prepared)
        assert len(snapshot.properties) == 2
        assert session.scalar(select(func.count()).select_from(AgentCrmLink)) == 1
        assert session.scalar(select(func.count()).select_from(AgentCrmJob)) == 1
    provider = Mock()
    provider.send_agent.return_value = AgentDeliveryResult("sent", "GHL_DELIVERED", "ghl-contact")
    assert process_agent_jobs(sessions, ghl_settings, provider).processed == 1
    third = deepcopy(second)
    third.update(source_listing_id="third", listing_reference="THIRD", street_address="3 Fictional Way")
    import_live(sessions, ghl_settings, [third])
    service.queue([prepared])
    process_agent_jobs(sessions, ghl_settings, provider)
    request = provider.send_agent.call_args.args[0]
    assert request.contact_id == "ghl-contact"
    assert len(request.snapshot.properties) == 3


def test_import_reservations_are_transactional_and_request_replay_does_not_requeue(sessions, ghl_settings, prepared, live_record, monkeypatch):
    from dwellcall.listings import service as listing_service

    settings = ghl_settings.model_copy(update={"ghl_auto_queue": True})
    updated = deepcopy(live_record)
    updated.update(price="700000.00", source_updated_at=datetime.now(UTC).isoformat())
    request_id = uuid4()
    first = import_live(sessions, settings, [updated], request_id)
    assert first["crm"]["queued"] == 1
    assert import_live(sessions, settings, [updated], request_id)["replayed"] is True
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(AgentCrmJob)) == 1
    changed = deepcopy(updated)
    changed["agents"][0]["contacts"][0]["source_reference"] = "different-evidence"
    original = listing_service.audit

    def fail(session, source, event, details):
        if event == "LISTING_IMPORT_COMPLETED":
            raise RuntimeError("synthetic precommit failure")
        return original(session, source, event, details)

    with monkeypatch.context() as context:
        context.setattr(listing_service, "audit", fail)
        with pytest.raises(RuntimeError):
            import_live(sessions, settings, [changed])
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(AgentCrmJob)) == 1


@pytest.mark.parametrize("reason", ["suppressed", "ambiguous", "unverified", "revoked", "review", "synthetic"])
def test_ineligible_agents_are_excluded_and_reserved_jobs_recheck_before_http(sessions, ghl_settings, prepared, live_record, reason):
    service = AgentCrmService(sessions, ghl_settings)
    row = service.queue([prepared])[0]
    with sessions() as session, session.begin():
        agent = session.get(ListingAgent, prepared)
        if reason == "suppressed":
            agent.suppressed_at = datetime.now(UTC)
        elif reason == "ambiguous":
            agent.review_required = True
        elif reason == "synthetic":
            agent.data_mode = "synthetic"
        elif reason == "unverified":
            for contact in session.scalars(select(ListingContactEvidence)):
                contact.verification_status = "unverified"
        elif reason == "revoked":
            source = session.get(ListingSource, SOURCE)
            source.permission = {**source.permission, "export_allowed": False}
        else:
            session.add(ListingReview(id=uuid4(), source_key=SOURCE, source_listing_id=live_record["source_listing_id"],
                                      reason="CONFLICTING_AGENT_IDENTITIES", fingerprint="test-review", candidate_ids=[str(prepared)],
                                      snapshot={}, status="rejected", resolution={}, created_at=datetime.now(UTC)))
    provider = Mock()
    process_agent_jobs(sessions, ghl_settings, provider)
    provider.send_agent.assert_not_called()
    assert service.history(1, 25).items[0].status == "cancelled"
    assert service.preview(1, 25).items[0].eligible is False


def test_shared_phone_is_not_an_exportable_person_identity(sessions, ghl_settings, prepared, live_record):
    second = deepcopy(live_record)
    second.update(source_listing_id="other", listing_reference="OTHER", street_address="2 Fictional Way")
    second["agents"][0].update(source_agent_id="different-agent", identifiers=[], full_name="Other Fictional Agent")
    for contact in second["agents"][0]["contacts"]:
        contact["verification"] = "unverified"
    import_live(sessions, ghl_settings, [second])
    with sessions() as session, pytest.raises(AgentIneligible, match="SHARED_CONTACT_IDENTITY"):
        export_snapshot(session, prepared)


def test_concurrent_workers_and_queue_replays_do_not_duplicate_jobs_or_sends(sessions, ghl_settings, prepared):
    service = AgentCrmService(sessions, ghl_settings)
    first = service.queue([prepared])[0]
    assert service.queue([prepared, prepared])[0].id == first.id
    barrier = Barrier(2)
    provider = Mock()
    provider.send_agent.return_value = AgentDeliveryResult("sent", "GHL_DELIVERED", "ghl-contact")

    def run():
        barrier.wait(timeout=10)
        return process_agent_jobs(sessions, ghl_settings, provider)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run), executor.submit(run)]
        [future.result(timeout=30) for future in futures]
    provider.send_agent.assert_called_once()
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(AgentCrmJob)) == 1


def test_rate_limit_backoff_survives_worker_restart(sessions, ghl_settings, prepared):
    service = AgentCrmService(sessions, ghl_settings)
    service.queue([prepared])
    provider = Mock()
    provider.send_agent.return_value = AgentDeliveryResult("retry_wait", "GHL_RATE_LIMITED", retry_after_seconds=120)
    process_agent_jobs(sessions, ghl_settings, provider)
    with sessions() as session:
        assert session.get(AgentCrmDestination, ghl_settings.destination).next_attempt_at > datetime.now(UTC) + timedelta(seconds=100)
    assert process_agent_jobs(sessions, ghl_settings, provider).processed == 0
    provider.send_agent.assert_called_once()


def test_interrupted_and_uncertain_jobs_block_new_reservations_until_lookup(sessions, ghl_settings, prepared):
    service = AgentCrmService(sessions, ghl_settings)
    job = service.queue([prepared])[0]
    with sessions() as session, session.begin():
        row = session.get(AgentCrmJob, job.id)
        row.status, row.attempted_at, row.attempt_id = "sending", datetime.now(UTC) - timedelta(seconds=121), uuid4()
    recover(sessions, ghl_settings)
    with pytest.raises(ApiError) as error:
        service.queue([prepared])
    assert error.value.code == "GHL_OUTCOME_UNRESOLVED"
    provider = Mock()
    provider.reconcile_agent.return_value = AgentDeliveryResult("unknown", "GHL_CONTACT_NOT_CONFIRMED")
    assert reconcile_job(sessions, ghl_settings, job.id, "test-investigation", provider).status == "unknown"
    provider.reconcile_agent.return_value = AgentDeliveryResult("retry_wait", "GHL_CONTACT_CONFIRMED_RETRY_UPDATE", "ghl-contact", retry_after_seconds=1)
    assert reconcile_job(sessions, ghl_settings, job.id, "test-found-contact", provider).contact_id == "ghl-contact"
    with sessions() as session, session.begin():
        session.get(AgentCrmJob, job.id).next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    provider.send_agent.return_value = AgentDeliveryResult("sent", "GHL_DELIVERED", "ghl-contact")
    process_agent_jobs(sessions, ghl_settings, provider)
    assert provider.send_agent.call_args.args[0].contact_id == "ghl-contact"


def test_operator_cannot_retry_unknown_but_can_retry_confirmed_failure(sessions, ghl_settings, prepared):
    service = AgentCrmService(sessions, ghl_settings)
    job = service.queue([prepared])[0]
    with sessions() as session, session.begin():
        row = session.get(AgentCrmJob, job.id)
        row.status, row.code = "unknown", "GHL_WRITE_UNCERTAIN"
    with pytest.raises(ApiError, match="Only retained"):
        service.retry(job.id, "synthetic-evidence")
    with sessions() as session, session.begin():
        row = session.get(AgentCrmJob, job.id)
        row.status, row.code = "failed", "GHL_REJECTED_401"
        session.get(AgentCrmDestination, ghl_settings.destination).paused = True
    assert service.retry(job.id, "synthetic-token-rotation").status == "retry_wait"
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(AgentCrmAudit).where(AgentCrmAudit.event_type == "GHL_OPERATOR_RETRY")) == 1


def test_setup_discovers_owned_fields_and_read_permissions_without_writes(sessions, ghl_settings):
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/locations/test-location":
            return httpx.Response(200, json={"location": {"id": "test-location", "settings": {"allowDuplicateContact": False}}})
        if request.url.path == "/contacts/search":
            return httpx.Response(200, json={"contacts": [], "total": 0})
        return httpx.Response(200, json={"customFields": [
            {"id": ghl_settings.ghl_custom_fields[key], "name": name, "dataType": kind, "model": "contact"}
            for key, (name, kind) in FIELD_DEFINITIONS.items()
        ]})

    provider = GoHighLevelProvider(ghl_settings, httpx.Client(transport=httpx.MockTransport(handler)))
    result = GhlConfigurationService(sessions, ghl_settings).setup(GhlSetupInput(evidence_reference="synthetic-setup"), provider)
    assert result["configured"] is True
    assert result["write_scopes_verified"] is False
    assert all(method == "GET" or path == "/contacts/search" for method, path in calls)


def test_local_queue_lock_prevents_concurrent_duplicate_reservations(sessions, ghl_settings, prepared):
    with sessions() as session, session.begin():
        ingestion_lock(session)
        with pytest.raises(ApiError) as error:
            AgentCrmService(sessions, ghl_settings).queue([prepared])
        assert error.value.code == "INGESTION_BUSY"
    AgentCrmService(sessions, ghl_settings).queue([prepared])
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(AgentCrmJob)) == 1


def test_provisioning_requires_approval_and_never_repeats_an_uncertain_create(sessions, ghl_settings):
    from dwellcall.crm.agent_schemas import LocationProvisionInput

    request = LocationProvisionInput(
        evidence_reference="synthetic-owner-approval", approve_external_creation=True,
        agency_scope_confirmed=True, plan_permits_provisioning=True, plan_evidence_reference="synthetic-plan",
        name="Fictional Account", address="1 Fictional Way", city="Austin", state="TX",
        country="US", postal_code="78701", timezone="America/Chicago",
    )
    with pytest.raises(ApiError) as error:
        GhlConfigurationService(sessions, ghl_settings).provision(request)
    assert error.value.code == "GHL_PROVISIONING_NOT_APPROVED"
    configuration = ghl_settings.model_copy(update={"ghl_provisioning_enabled": True,
                                                   "ghl_agency_token": ghl_settings.ghl_private_integration_token,
                                                   "ghl_company_id": "synthetic-company", "ghl_declared_scopes": ("locations.write",)})
    calls = []

    def handler(request):
        calls.append(request.url.path)
        raise httpx.ReadTimeout("synthetic uncertain provisioning", request=request)

    provider = GoHighLevelProvider(configuration, httpx.Client(transport=httpx.MockTransport(handler)))
    service = GhlConfigurationService(sessions, configuration)
    assert service.provision(request, provider)["operation"]["status"] == "unknown"
    assert service.provision(request, provider)["replayed"] is True
    assert calls == ["/locations/"]


def test_operator_binding_unblocks_only_the_confirmed_existing_contact(sessions, ghl_settings, prepared):
    from dwellcall.crm.agent_schemas import ContactBinding

    service = AgentCrmService(sessions, ghl_settings)
    job = service.queue([prepared])[0]
    with sessions() as session, session.begin():
        row = session.get(AgentCrmJob, job.id)
        row.status, row.code = "failed", "GHL_CONTACT_REVIEW_REQUIRED"
        snapshot = export_snapshot(session, prepared)
    provider = Mock()
    provider.get_contact.return_value = {"id": "owner-contact", "locationId": "test-location", "email": snapshot.email, "customFields": []}
    GhlConfigurationService(sessions, ghl_settings).bind(prepared, ContactBinding(
        contact_id="owner-contact", evidence_reference="synthetic-owner-binding",
    ), provider)
    provider.send_agent.assert_not_called()
    with sessions() as session:
        assert session.get(AgentCrmJob, job.id).status == "retry_wait"
    worker = Mock()
    worker.send_agent.return_value = AgentDeliveryResult("sent", "GHL_DELIVERED", "owner-contact")
    process_agent_jobs(sessions, ghl_settings, worker)
    assert worker.send_agent.call_args.args[0].contact_id == "owner-contact"
