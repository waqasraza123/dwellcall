import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from dwellcall.database.models import (
    ListingAgent, ListingContactEvidence, ListingEntity, ListingImportRun,
    ListingObservation, ListingRevision, ListingSource,
)
from dwellcall.errors import ApiError
from dwellcall.listings.queries import ListingQueries
from dwellcall.listings.registry import SYNTHETIC_SOURCE_KEY, SourceRegistryService
from dwellcall.listings.schemas import DiscoveryFilters, SourcePermissionInput
from dwellcall.listings.service import ListingIngestionService, ingestion_lock
from dwellcall.listings.settings import ListingSettings

SOURCE = SYNTHETIC_SOURCE_KEY


@pytest.fixture
def record() -> dict:
    path = Path(__file__).resolve().parents[2] / "data/listings/synthetic-listings.json"
    data = json.loads(path.read_text())["listings"][0]
    data["source_updated_at"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    return data


def ingest(
    sessions: sessionmaker[Session], records: list[dict], *,
    request_id: UUID | None = None, source: str = SOURCE,
    filters: DiscoveryFilters | None = None,
) -> dict:
    return ListingIngestionService(sessions, ListingSettings()).ingest(
        source, json.dumps({"synthetic": True, "listings": records}).encode(),
        "json", request_id or uuid4(), filters,
    )


def later(record: dict, **patch: object) -> dict:
    return {**deepcopy(record), **patch, "source_updated_at": (
        datetime.fromisoformat(record["source_updated_at"]) + timedelta(minutes=1)
    ).isoformat()}


def test_replays_and_new_requests_do_not_duplicate_records(sessions, record) -> None:
    request_id = uuid4()
    first = ingest(sessions, [record], request_id=request_id)
    replay = ingest(sessions, [record], request_id=request_id)
    duplicate = ingest(sessions, [record])
    assert first["new_listings"] == first["new_agents"] == 1
    assert replay["run_id"] == first["run_id"]
    assert replay["replayed"] is True
    assert duplicate["duplicates"] == 1
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(ListingImportRun)) == 2
        assert session.scalar(select(func.count()).select_from(ListingEntity)) == 1
        assert session.scalar(select(func.count()).select_from(ListingRevision)) == 1
    with pytest.raises(ApiError) as error:
        ingest(sessions, [later(record, price="600000.00")], request_id=request_id)
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_price_and_status_updates_preserve_unknown_and_omitted_fields(sessions, record) -> None:
    filters = DiscoveryFilters(statuses=("active",), min_price=600000)
    ingest(sessions, [record], filters=filters)
    updated = later(record, price="590000.00")
    assert ingest(sessions, [updated], filters=filters)["updated"] == 1
    removed = {
        "source_listing_id": record["source_listing_id"], "status": "removed",
        "source_updated_at": later(updated)["source_updated_at"],
    }
    assert ingest(sessions, [removed], filters=filters)["updated"] == 1
    item = ListingQueries(sessions).listings(1, 25, "synthetic")["items"][0]
    assert item["property"]["street_address"] == record["street_address"]
    assert item["property"]["price"] == "590000.00"
    assert item["property"]["status"] == "removed"
    assert item["agent_ids"]
    assert ingest(sessions, [record])["stale"] == 1
    with sessions() as session:
        assert session.scalar(select(ListingEntity.price)) == Decimal("590000.00")
        assert any("price_changed" in row.events for row in session.scalars(select(ListingRevision)))


def test_shared_agents_coagents_and_missing_contacts(sessions, record) -> None:
    other = deepcopy(record)
    other.update(source_listing_id="other", listing_reference="DEMO-OTHER", street_address="2 Fictional Way")
    other["agents"].append({"source_agent_id": "coagent", "full_name": "Co Agent (Fictional)"})
    result = ingest(sessions, [record, other])
    assert result["new_listings"] == result["new_agents"] == 2
    agents = ListingQueries(sessions).agents(1, 25, "synthetic", reveal_contacts=True)["items"]
    assert sorted(len(row["listing_ids"]) for row in agents) == [1, 2]
    assert next(row for row in agents if row["full_name"].startswith("Co"))["contacts"] == []
    assert all(row["outreach_permission"] is False for row in agents)


def test_same_address_and_same_name_are_insufficient_identity(sessions, record) -> None:
    other = deepcopy(record)
    other.update(source_listing_id="relisted", listing_reference="DEMO-RELISTED")
    other["agents"][0]["source_agent_id"] = "different-person"
    other["agents"][0]["identifiers"] = []
    other["agents"][0]["contacts"] = [{
        "kind": "office_phone", "value": "+15125550100", "published_as_business": True,
        "verification": "verified", "verified_at": datetime.now(UTC).isoformat(),
        "source_reference": "synthetic-office",
    }]
    result = ingest(sessions, [record, other])
    assert result["new_listings"] == result["new_agents"] == 2
    assert result["reviews"] >= 1
    assert result["status"] == "partial"
    assert any(row["reason"] == "ADDRESS_ONLY_NOT_MERGED" for row in ListingQueries(sessions).reviews())


def test_cross_source_merge_requires_approved_listing_evidence(sessions, record) -> None:
    ingest(sessions, [record])
    with sessions() as session:
        source = session.get(ListingSource, SOURCE)
        policy = SourcePermissionInput.model_validate(source.permission)
    SourceRegistryService(sessions).configure("second-demo", policy)
    other = deepcopy(record)
    other["source_listing_id"] = "other-source-id"
    result = ingest(sessions, [other], source="second-demo")
    assert result["linked_sources"] == 1
    assert result["new_agents"] == 0
    assert ListingQueries(sessions).listings(1, 25, "synthetic")["total"] == 1
    conflict = later(other, street_address="999 Conflicting Street")
    assert ingest(sessions, [conflict], source="second-demo")["reviews"] == 1


def test_conflicting_verified_contacts_are_held_for_review(sessions, record) -> None:
    one = deepcopy(record)
    two = deepcopy(record)
    two.update(source_listing_id="two", listing_reference="DEMO-TWO", street_address="2 Fictional Way")
    two["agents"][0].update(source_agent_id="second-agent", identifiers=[], full_name="Other Agent (Fictional)")
    for index, value in enumerate((one, two)):
        value["agents"][0]["contacts"] = [{
            "kind": "business_email", "value": f"demo-{index}@example.com",
            "direct": True, "published_as_business": True, "verification": "verified",
            "verified_at": datetime.now(UTC).isoformat(), "source_reference": "synthetic-directory",
        }]
    ingest(sessions, [one, two])
    conflict = later(one)
    conflict["agents"][0]["contacts"] = two["agents"][0]["contacts"]
    result = ingest(sessions, [conflict])
    assert result["reviews"] == 1
    assert any(row["reason"] == "CONFLICTING_AGENT_IDENTITIES" for row in ListingQueries(sessions).reviews())
    agents = ListingQueries(sessions).agents(1, 25, "synthetic", reveal_contacts=True)["items"]
    assert all(contact["verification_status"] != "verified" for row in agents for contact in row["contacts"])


def test_permissions_masking_suppression_and_deletion(sessions, record) -> None:
    ingest(sessions, [record])
    queries = ListingQueries(sessions)
    agent = queries.agents(1, 25, "synthetic", reveal_contacts=False)["items"][0]
    assert all(contact["value"] == "[restricted]" for contact in agent["contacts"])
    registry = SourceRegistryService(sessions)
    registry.suppress(UUID(agent["id"]))
    ingest(sessions, [later(record)])
    assert queries.agents(1, 25, "synthetic", reveal_contacts=True)["items"][0]["contacts"] == []
    with sessions() as session:
        policy = SourcePermissionInput.model_validate(session.get(ListingSource, SOURCE).permission)
    revoked = policy.model_copy(update={"display_allowed": False})
    registry.configure(SOURCE, revoked)
    assert queries.listings(1, 25, "synthetic")["items"] == []
    registry.configure(SOURCE, policy)
    registry.purge(SOURCE, expired_only=False)
    assert queries.listings(1, 25, "synthetic")["total"] == 0
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(ListingContactEvidence)) == 0
        assert session.scalar(select(ListingAgent.suppressed_at)) is not None


def test_expired_data_is_hidden_and_owner_maintenance_removes_it(sessions, record) -> None:
    ingest(sessions, [record])
    with sessions() as session, session.begin():
        for observation in session.scalars(select(ListingObservation)):
            observation.collected_at = datetime.now(UTC) - timedelta(days=31)
    assert ListingQueries(sessions).listings(1, 25, "synthetic")["total"] == 0
    result = SourceRegistryService(sessions).purge(SOURCE)
    assert result["observations_removed"] == 1


def test_busy_import_can_be_retried_without_duplicate_run(sessions, record) -> None:
    request_id = uuid4()
    with sessions() as session, session.begin():
        ingestion_lock(session)
        with pytest.raises(ApiError) as error:
            ingest(sessions, [record], request_id=request_id)
        assert error.value.code == "INGESTION_BUSY"
    assert ingest(sessions, [record], request_id=request_id)["new_listings"] == 1


def test_unexpected_failure_rolls_back_whole_import_and_checkpoint(sessions, record, monkeypatch) -> None:
    from dwellcall.listings import service

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic crash before commit")

    with monkeypatch.context() as context:
        context.setattr(service, "materialize_listing", fail)
        with pytest.raises(RuntimeError):
            ingest(sessions, [record])
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(ListingImportRun)) == 0
        assert session.scalar(select(func.count()).select_from(ListingEntity)) == 0
        assert session.get(ListingSource, SOURCE).checkpoint is None
    assert ingest(sessions, [record])["new_listings"] == 1


def test_row_validation_errors_and_provider_gates_are_visible(sessions, record) -> None:
    result = ingest(sessions, [record, {"source_listing_id": "bad", "price": -1}])
    assert result["new_listings"] == 1
    assert result["status"] == "partial"
    assert result["errors"] == [{"row": 2, "code": "RECORD_INVALID"}]
    with sessions() as session:
        policy = SourcePermissionInput.model_validate(session.get(ListingSource, SOURCE).permission)
    SourceRegistryService(sessions).configure("future-feed", policy.model_copy(update={
        "provider": "licensed_feed", "data_mode": "live",
    }))
    with pytest.raises(ApiError) as error:
        ingest(sessions, [record], source="future-feed")
    assert error.value.code == "PROVIDER_UNAVAILABLE"


def weak_record(record: dict) -> dict:
    value = deepcopy(record)
    value["agents"][0].pop("source_agent_id", None)
    value["agents"][0]["identifiers"] = []
    return value


def resolve(sessions, review: dict, decision: str = "approve", candidate: str | None = None):
    from dwellcall.listings.reviews import ListingReviewService
    from dwellcall.listings.schemas import ReviewResolutionInput

    return ListingReviewService(sessions).resolve(UUID(review["id"]), ReviewResolutionInput(
        decision=decision, candidate_id=UUID(candidate or review["candidate_ids"][0]) if decision == "approve" else None,
        evidence_reference="synthetic-operator-evidence",
    ))


def test_weak_identity_never_uses_verified_contacts_to_merge_or_enrich(sessions, record) -> None:
    one = weak_record(record)
    one["agents"][0]["contacts"] = [{
        "kind": "business_email", "value": "weak-demo@example.com", "direct": True,
        "published_as_business": True, "verification": "verified",
        "verified_at": datetime.now(UTC).isoformat(), "source_reference": "synthetic-directory",
    }]
    two = deepcopy(one)
    two.update(source_listing_id="weak-two", listing_reference="DEMO-WEAK-TWO", street_address="2 Fictional Way")
    assert ingest(sessions, [one, two])["new_agents"] == 2
    agents = ListingQueries(sessions).agents(1, 25, "synthetic", reveal_contacts=True)["items"]
    assert len(agents) == 2
    assert all(agent["review_required"] and not agent["crm_export_eligible"] and not agent["contacts"] for agent in agents)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(ListingContactEvidence)) == 0
    assert ingest(sessions, [one, two])["duplicates"] == 2


def test_shared_brokerage_phone_does_not_merge_agents(sessions, record) -> None:
    one = weak_record(record)
    one["agents"][0]["contacts"] = [{
        "kind": "office_phone", "value": "+15125550100", "published_as_business": True,
        "source_reference": "synthetic-office",
    }]
    two = deepcopy(one)
    two.update(source_listing_id="office-two", listing_reference="DEMO-OFFICE-TWO", street_address="2 Fictional Way")
    two["agents"][0]["full_name"] = "Different Fictional Agent"
    assert ingest(sessions, [one, two])["new_agents"] == 2
    assert all(row["review_required"] for row in ListingQueries(sessions).agents(1, 25, "synthetic", reveal_contacts=True)["items"])


def test_duplicate_agent_keys_are_held_without_creating_contacts(sessions, record) -> None:
    record["agents"].append(deepcopy(record["agents"][0]))
    assert ingest(sessions, [record])["new_agents"] == 0
    assert ingest(sessions, [record])["duplicates"] == 1
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(ListingContactEvidence)) == 0


def test_weak_suppression_survives_updates_replays_purge_and_new_id(sessions, record) -> None:
    from dwellcall.database.models import ListingAgentIdentity

    weak = weak_record(record)
    request_id = uuid4()
    ingest(sessions, [weak], request_id=request_id)
    queries = ListingQueries(sessions)
    agent = queries.agents(1, 25, "synthetic", reveal_contacts=True)["items"][0]
    registry = SourceRegistryService(sessions)
    registry.suppress(UUID(agent["id"]))
    ingest(sessions, [weak], request_id=request_id)
    ingest(sessions, [later(weak)])
    registry.purge(SOURCE, expired_only=False)
    promoted = later(weak)
    promoted["agents"][0]["source_agent_id"] = "new-unproven-id"
    assert ingest(sessions, [promoted])["new_agents"] == 0
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(ListingAgent)) == 1
        assert session.get(ListingAgent, UUID(agent["id"])).suppressed_at is not None
        assert session.scalar(select(func.count()).select_from(ListingContactEvidence)) == 0
        assert session.scalar(select(ListingAgentIdentity.id).where(ListingAgentIdentity.namespace == "source:" + SOURCE)) is None


def test_weak_approval_is_scoped_to_exact_evidence_and_cannot_unsuppress(sessions, record) -> None:
    from dwellcall.listings.reviews import ListingReviewService

    weak = weak_record(record)
    ingest(sessions, [weak])
    queries = ListingQueries(sessions)
    review = queries.reviews()[0]
    inspected = ListingReviewService(sessions).inspect(UUID(review["id"]))
    assert inspected["candidates"]
    assert "contacts" not in inspected["evidence"]["agent"]
    result = resolve(sessions, review)
    assert result["requires_reimport"] is True
    assert resolve(sessions, review)["resolution"] == result["resolution"]
    ingest(sessions, [weak])
    approved = queries.agents(1, 25, "synthetic", reveal_contacts=True)["items"][0]
    assert approved["review_required"] is False
    assert approved["contacts"]
    changed = later(weak)
    changed["agents"][0]["contacts"][0]["source_reference"] = "changed-evidence"
    ingest(sessions, [changed])
    held = queries.agents(1, 25, "synthetic", reveal_contacts=True)["items"][0]
    assert held["review_required"] is True
    assert held["contacts"] == []
    SourceRegistryService(sessions).suppress(UUID(approved["id"]))
    pending = next(row for row in queries.reviews() if row["status"] == "pending")
    with pytest.raises(ApiError) as error:
        resolve(sessions, pending)
    assert error.value.code == "AGENT_SUPPRESSED"
    ingest(sessions, [weak])
    with sessions() as session:
        assert session.get(ListingAgent, UUID(approved["id"])).suppressed_at is not None


def test_conflicting_ids_can_be_rejected_without_reassigning_identities(sessions, record) -> None:
    from dwellcall.database.models import ListingAgentIdentity

    second = deepcopy(record)
    second.update(source_listing_id="second", listing_reference="DEMO-SECOND", street_address="2 Fictional Way")
    second["agents"][0].update(source_agent_id="second-agent", identifiers=[], contacts=[])
    ingest(sessions, [record, second])
    conflict = later(record)
    conflict["agents"][0]["source_agent_id"] = "second-agent"
    ingest(sessions, [conflict])
    queries = ListingQueries(sessions)
    review = next(row for row in queries.reviews() if row["reason"] == "CONFLICTING_AGENT_IDENTITIES")
    with sessions() as session:
        before = {(row.namespace, row.identifier): row.agent_id for row in session.scalars(select(ListingAgentIdentity))}
    resolve(sessions, review, "reject")
    ingest(sessions, [later(conflict)])
    assert len([row for row in queries.reviews() if row["reason"] == "CONFLICTING_AGENT_IDENTITIES"]) == 1
    with sessions() as session:
        assert {(row.namespace, row.identifier): row.agent_id for row in session.scalars(select(ListingAgentIdentity))} == before
    assert all(not row["crm_export_eligible"] for row in queries.agents(1, 25, "synthetic", reveal_contacts=True)["items"])


def test_listing_match_approval_applies_on_reimport_and_is_audited_once(sessions, record) -> None:
    from dwellcall.database.models import ListingAuditEvent

    ingest(sessions, [record])
    other = deepcopy(record)
    other.update(source_listing_id="relist", listing_namespace=None, listing_reference=None)
    ingest(sessions, [other])
    queries = ListingQueries(sessions)
    review = next(row for row in queries.reviews() if row["reason"] == "ADDRESS_ONLY_NOT_MERGED")
    with sessions() as session:
        target = session.scalar(select(ListingObservation.listing_id).where(ListingObservation.source_listing_id == record["source_listing_id"]))
    resolve(sessions, review, candidate=str(target))
    request_id = uuid4()
    ingest(sessions, [other], request_id=request_id)
    ingest(sessions, [other], request_id=request_id)
    ingest(sessions, [other])
    with sessions() as session:
        assert session.scalar(select(ListingObservation.listing_id).where(ListingObservation.source_listing_id == "relist")) == target
        assert session.scalar(select(func.count()).select_from(ListingAuditEvent).where(ListingAuditEvent.event_type == "LISTING_REVIEW_RESOLVED")) == 1
        assert session.scalar(select(func.count()).select_from(ListingAuditEvent).where(ListingAuditEvent.event_type == "LISTING_REVIEW_APPLIED")) == 1


def test_concurrent_review_decisions_have_one_immutable_winner(sessions, record) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from dwellcall.database.models import ListingAuditEvent

    ingest(sessions, [weak_record(record)])
    review = ListingQueries(sessions).reviews()[0]
    barrier = Barrier(2)

    def attempt(decision):
        barrier.wait(timeout=10)
        try:
            return resolve(sessions, review, decision)["status"]
        except ApiError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(attempt, decision) for decision in ("approve", "reject")]
        results = [future.result(timeout=20) for future in futures]
    assert sum(value in {"approved", "rejected"} for value in results) == 1
    assert any(value in {"INGESTION_BUSY", "REVIEW_ALREADY_RESOLVED"} for value in results)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(ListingAuditEvent).where(ListingAuditEvent.event_type == "LISTING_REVIEW_RESOLVED")) == 1
    winner = next(value for value in results if value in {"approved", "rejected"})
    with pytest.raises(ApiError) as error:
        resolve(sessions, review, "reject" if winner == "approved" else "approve")
    assert error.value.code == "REVIEW_ALREADY_RESOLVED"


def test_suppression_aliases_block_new_ids_and_changed_brokerage(sessions, record) -> None:
    ingest(sessions, [record])
    queries = ListingQueries(sessions)
    agent_id = UUID(queries.agents(1, 25, "synthetic", reveal_contacts=True)["items"][0]["id"])
    registry = SourceRegistryService(sessions)
    registry.suppress(agent_id)
    changed = later(record)
    changed["agents"][0].update(source_agent_id="reissued-id", identifiers=[], brokerage="Changed Fictional Office")
    assert ingest(sessions, [changed])["new_agents"] == 0
    registry.purge(SOURCE, expired_only=False)
    elsewhere = deepcopy(changed)
    elsewhere.update(source_listing_id="elsewhere", listing_reference="DEMO-ELSEWHERE", street_address="2 Fictional Way")
    assert ingest(sessions, [elsewhere])["new_agents"] == 0
    with sessions() as session:
        assert session.get(ListingAgent, agent_id).suppressed_at is not None
        assert session.scalar(select(func.count()).select_from(ListingContactEvidence).where(ListingContactEvidence.active.is_(True))) == 0


def test_approved_conflict_binds_observation_without_reassigning_global_ids(sessions, record) -> None:
    from dwellcall.database.models import ListingAgentIdentity, ListingAgentObservation

    second = deepcopy(record)
    second.update(source_listing_id="second", listing_reference="DEMO-SECOND", street_address="2 Fictional Way")
    second["agents"][0].update(source_agent_id="second-agent", identifiers=[], contacts=[])
    ingest(sessions, [record, second])
    with sessions() as session:
        identities = {(row.namespace, row.identifier): row.agent_id for row in session.scalars(select(ListingAgentIdentity))}
        target = next(row.agent_id for row in session.scalars(select(ListingAgentIdentity)) if row.identifier == "second-agent")
    conflict = later(record)
    conflict["agents"][0]["source_agent_id"] = "second-agent"
    ingest(sessions, [conflict])
    review = next(row for row in ListingQueries(sessions).reviews() if row["reason"] == "CONFLICTING_AGENT_IDENTITIES")
    resolve(sessions, review, candidate=str(target))
    ingest(sessions, [conflict])
    with sessions() as session:
        assert {(row.namespace, row.identifier): row.agent_id for row in session.scalars(select(ListingAgentIdentity))} == identities
        assert session.scalar(select(ListingAgentObservation.agent_id).join(ListingObservation, ListingObservation.id == ListingAgentObservation.observation_id).where(
            ListingObservation.source_listing_id == record["source_listing_id"], ListingAgentObservation.active.is_(True),
        )) == target


def test_review_resolution_shares_import_lock_and_rolls_back_with_audit(sessions, record, monkeypatch) -> None:
    from dwellcall.database.models import ListingReview
    from dwellcall.listings import reviews

    ingest(sessions, [weak_record(record)])
    review = ListingQueries(sessions).reviews()[0]
    with sessions() as session, session.begin():
        ingestion_lock(session)
        with pytest.raises(ApiError) as error:
            resolve(sessions, review)
        assert error.value.code == "INGESTION_BUSY"

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    with monkeypatch.context() as context:
        context.setattr(reviews, "audit", fail)
        with pytest.raises(RuntimeError):
            resolve(sessions, review)
    with sessions() as session:
        assert session.get(ListingReview, UUID(review["id"])).status == "pending"
    assert resolve(sessions, review)["status"] == "approved"
