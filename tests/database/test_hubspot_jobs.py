from concurrent.futures import ThreadPoolExecutor
import json
from datetime import UTC, datetime, timedelta
from threading import Barrier
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from dwellcall.crm.agent_jobs import process_agent_jobs, reconcile_job, recover
from dwellcall.crm.agent_service import AgentCrmService, destination_state
from dwellcall.crm.contracts import AgentDeliveryResult
from dwellcall.crm.hubspot_setup import HubSpotConfigurationService, HubSpotPropertyCreation, HubSpotSetupInput
from dwellcall.database.models import AgentCrmDestination, AgentCrmJob, AgentCrmLink, ListingAgent
from dwellcall.errors import ApiError
from dwellcall.listings.registry import SYNTHETIC_PERMISSION, SourceRegistryService
from dwellcall.listings.schemas import SourcePermissionInput
from tests.crm.test_hubspot import HubSpotServer, adapter
from tests.database.test_agent_crm import SOURCE, import_live, live_record as live_record


@pytest.fixture
def hubspot_prepared(sessions, hubspot_settings, live_record):
    SourceRegistryService(sessions).configure(SOURCE, SourcePermissionInput.model_validate({**SYNTHETIC_PERMISSION, "data_mode": "live", "export_allowed": True}))
    with sessions() as session, session.begin():
        destination_state(session, hubspot_settings).configured_at = datetime.now(UTC)
    import_live(sessions, hubspot_settings, [live_record])
    with sessions() as session:
        return session.scalar(select(ListingAgent.id))


def make_due(sessions, settings):
    with sessions() as session, session.begin():
        session.get(AgentCrmDestination, settings.destination).next_attempt_at = datetime.now(UTC)-timedelta(seconds=1)
        for row in session.scalars(select(AgentCrmJob).where(AgentCrmJob.status == "retry_wait")):
            row.next_attempt_at = datetime.now(UTC)-timedelta(seconds=1)


def test_shared_queue_is_idempotent_and_persists_contact_company_and_deal(sessions, hubspot_settings, hubspot_prepared):
    service = AgentCrmService(sessions, hubspot_settings)
    first = service.queue([hubspot_prepared])[0]
    assert service.queue([hubspot_prepared, hubspot_prepared])[0].id == first.id
    provider = Mock()
    provider.send_agent.return_value = AgentDeliveryResult("sent", "HUBSPOT_DELIVERED", "101", "301", company_id="201")
    assert process_agent_jobs(sessions, hubspot_settings, provider).processed == 1
    with sessions() as session:
        link = session.scalar(select(AgentCrmLink))
        assert (link.contact_id, link.company_id, link.opportunity_id) == ("101", "201", "301")
        assert session.get(AgentCrmJob, first.id).payload is None
        assert session.scalar(select(func.count()).select_from(AgentCrmJob)) == 1
    assert service.history(1,25).items[0].company_id == "201"
    assert service.preview(1,25).items[0].last_synced_at is not None


@pytest.mark.parametrize("state", ["suppressed", "ambiguous", "synthetic"])
def test_existing_eligibility_is_rechecked_before_hubspot_http(sessions, hubspot_settings, hubspot_prepared, state):
    service = AgentCrmService(sessions, hubspot_settings)
    service.queue([hubspot_prepared])
    with sessions() as session, session.begin():
        agent = session.get(ListingAgent, hubspot_prepared)
        if state == "suppressed":
            agent.suppressed_at = datetime.now(UTC)
        elif state == "ambiguous":
            agent.review_required = True
        else:
            agent.data_mode = "synthetic"
    provider = Mock()
    process_agent_jobs(sessions, hubspot_settings, provider)
    provider.send_agent.assert_not_called()
    assert service.history(1,25).items[0].status == "cancelled"


def test_hubspot_workers_share_existing_transactional_lock(sessions, hubspot_settings, hubspot_prepared):
    AgentCrmService(sessions, hubspot_settings).queue([hubspot_prepared])
    barrier = Barrier(2)
    provider = Mock()
    provider.send_agent.return_value = AgentDeliveryResult("sent", "HUBSPOT_DELIVERED", "101", company_id="201")
    def run():
        barrier.wait(timeout=10)
        return process_agent_jobs(sessions, hubspot_settings, provider)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [executor.submit(run), executor.submit(run)]
        [result.result(timeout=30) for result in results]
    provider.send_agent.assert_called_once()


def test_provider_backoff_survives_restart(sessions, hubspot_settings, hubspot_prepared):
    AgentCrmService(sessions, hubspot_settings).queue([hubspot_prepared])
    provider = Mock()
    provider.send_agent.return_value = AgentDeliveryResult("retry_wait", "HUBSPOT_RATE_LIMITED", retry_after_seconds=120)
    process_agent_jobs(sessions, hubspot_settings, provider)
    with sessions() as session:
        assert session.get(AgentCrmDestination, hubspot_settings.destination).next_attempt_at > datetime.now(UTC)+timedelta(seconds=100)
    assert process_agent_jobs(sessions, hubspot_settings, provider).processed == 0
    provider.send_agent.assert_called_once()


def test_restart_recovery_blocks_creation_until_operator_reconciliation(sessions, hubspot_settings, hubspot_prepared):
    service = AgentCrmService(sessions, hubspot_settings)
    job = service.queue([hubspot_prepared])[0]
    with sessions() as session, session.begin():
        row = session.get(AgentCrmJob, job.id)
        row.status, row.attempted_at, row.attempt_id = "sending", datetime.now(UTC)-timedelta(seconds=121), uuid4()
    recover(sessions, hubspot_settings)
    with pytest.raises(ApiError):
        service.queue([hubspot_prepared])
    with pytest.raises(ApiError):
        service.retry(job.id, "mock-evidence")
    provider = Mock()
    provider.reconcile_agent.return_value = AgentDeliveryResult("retry_wait", "HUBSPOT_CONTACT_CONFIRMED_RETRY_UPDATE", "101", company_id="201")
    assert reconcile_job(sessions, hubspot_settings, job.id, "mock-lookup", provider).company_id == "201"
    make_due(sessions, hubspot_settings)
    provider.send_agent.return_value = AgentDeliveryResult("sent", "HUBSPOT_DELIVERED", "101", company_id="201")
    process_agent_jobs(sessions, hubspot_settings, provider)
    assert provider.send_agent.call_args.args[0].contact_id == "101"
    assert provider.send_agent.call_args.args[0].company_id == "201"


def test_schema_creation_is_explicit_and_connection_check_is_read_only(sessions, hubspot_settings, monkeypatch):
    monkeypatch.setattr("dwellcall.crm.providers.hubspot.time.sleep", lambda _:None)
    server = HubSpotServer()
    settings = hubspot_settings.model_copy(update={"hubspot_schema_creation_enabled":True})
    provider = adapter(settings, server)
    configuration = HubSpotConfigurationService(sessions, settings)
    first = configuration.setup(HubSpotSetupInput(evidence_reference="mock-inspect"), provider)
    assert first["configured"] is False
    assert all(method == "GET" for method, _, _ in server.calls)
    configuration.create_properties(HubSpotPropertyCreation(evidence_reference="mock-create", approve_external_creation=True), provider)
    second = configuration.setup(HubSpotSetupInput(evidence_reference="mock-inspect-2"), provider)
    assert second["configured"] is True
    before = len([entry for entry in server.calls if entry[0] == "POST"])
    configuration.create_properties(HubSpotPropertyCreation(evidence_reference="mock-replay", approve_external_creation=True), provider)
    assert len([entry for entry in server.calls if entry[0] == "POST"]) == before


def test_unknown_schema_create_is_inspected_and_never_blindly_reposted(sessions, hubspot_settings, monkeypatch):
    import httpx

    monkeypatch.setattr("dwellcall.crm.providers.hubspot.time.sleep", lambda _:None)
    server = HubSpotServer()
    writes = []
    def handler(request):
        if request.method == "POST" and request.url.path.startswith("/crm/properties/"):
            writes.append((request.url.path, json.loads(request.content)["name"]))
            raise httpx.ReadTimeout("mock uncertain schema create", request=request)
        return server(request)
    settings = hubspot_settings.model_copy(update={"hubspot_schema_creation_enabled":True})
    configuration = HubSpotConfigurationService(sessions, settings)
    request = HubSpotPropertyCreation(evidence_reference="mock-schema-unknown", approve_external_creation=True)
    configuration.create_properties(request, adapter(settings, handler))
    assert len(writes) == 1
    configuration.create_properties(request, adapter(settings, handler))
    assert len(writes) == 2
    with sessions() as session:
        state = session.get(AgentCrmDestination, settings.destination)
        assert state.capabilities["schema:contacts:dwellcall_agent_id"] == "unknown"
    # The second explicit call skipped the first uncertain property and reserved a different missing property.
    assert [name for _, name in writes] == ["dwellcall_agent_id", "dwellcall_revision"]


def test_multiple_listings_update_the_same_hubspot_mapping(sessions, hubspot_settings, hubspot_prepared, live_record):
    from copy import deepcopy

    service = AgentCrmService(sessions, hubspot_settings)
    provider = Mock()
    provider.send_agent.return_value = AgentDeliveryResult("sent", "HUBSPOT_DELIVERED", "101", company_id="201")
    service.queue([hubspot_prepared])
    process_agent_jobs(sessions, hubspot_settings, provider)
    extra = deepcopy(live_record)
    extra.update(source_listing_id="hubspot-second", listing_reference="HS-SECOND", street_address="2 Fictional Way")
    import_live(sessions, hubspot_settings, [extra])
    service.queue([hubspot_prepared])
    make_due(sessions, hubspot_settings)
    process_agent_jobs(sessions, hubspot_settings, provider)
    request = provider.send_agent.call_args.args[0]
    assert request.contact_id == "101"
    assert request.company_id == "201"
    assert len({item.listing_id for item in request.snapshot.properties}) == 2
