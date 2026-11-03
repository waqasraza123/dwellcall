import asyncio
from decimal import Decimal
from unittest.mock import Mock, patch

from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import Engine

from dwellcall.application import create_app
from dwellcall.crm.agent_schemas import GhlSetupInput
from dwellcall.listings.settings import ListingSettings
from dwellcall.workspace_routes import JobInput


def test_workspace_auth_precedes_body_database_and_provider(settings):
    engine = Mock(spec=Engine)
    app = create_app(settings, engine, listing_settings=ListingSettings(listing_viewer_token="v" * 43))

    async def requests():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            responses = []
            for headers in ({}, {"X-Admin-Token": "v" * 43}):
                responses.append(await client.get("/api/v1/intelligence/workspace/dashboard", headers=headers))
                responses.append(await client.post("/api/v1/intelligence/workspace/jobs", content=b"private", headers=headers))
                responses.append(await client.get("/api/v1/intelligence/workspace/activity", headers=headers))
            return responses

    with patch("dwellcall.workspace_routes.bounded_body") as body:
        responses = asyncio.run(requests())
    assert all(response.status_code == 401 for response in responses)
    body.assert_not_called()
    engine.connect.assert_not_called()


def test_listing_filters_reach_existing_permission_aware_queries(settings):
    app = create_app(settings, Mock(spec=Engine))

    async def request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get("/api/v1/intelligence/listings", params={"mode": "live", "q": "Austin", "min_price": "200000", "max_price": "800000", "status": "active", "property_type": "condo", "sort": "price_asc", "page": 2}, headers={"X-Admin-Token": settings.admin_token.get_secret_value()})

    with patch("dwellcall.listings.queries.ListingQueries.listings", return_value={"items": [], "total": 0, "page": 2, "page_size": 25}) as query:
        response = asyncio.run(request())
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert query.call_args.args == (2, 25, "live")
    assert query.call_args.kwargs["min_price"] == Decimal("200000")
    assert query.call_args.kwargs["status"] == "active"
    assert query.call_args.kwargs["sort"] == "price_asc"


def test_inverted_listing_ranges_are_rejected_without_queries(settings):
    app = create_app(settings, Mock(spec=Engine))

    async def request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get("/api/v1/intelligence/listings?min_price=500&max_price=100", headers={"X-Admin-Token": settings.admin_token.get_secret_value()})

    with patch("dwellcall.listings.queries.ListingQueries.listings") as query:
        response = asyncio.run(request())
    assert response.status_code == 422
    query.assert_not_called()


def test_dashboard_reads_do_not_dispatch_or_ingest(settings):
    app = create_app(settings, Mock(spec=Engine))

    async def request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get("/api/v1/intelligence/workspace/dashboard?mode=synthetic", headers={"X-Admin-Token": settings.admin_token.get_secret_value()})

    with patch("dwellcall.workspace_queries.WorkspaceQueries.dashboard", return_value={"data_mode": "synthetic", "metrics": {"listings": 0}}) as dashboard, patch("dwellcall.workspace_routes.DiscoveryService.run") as run, patch("dwellcall.crm.agent_routes.process_agent_jobs") as dispatch:
        response = asyncio.run(request())
    assert response.status_code == 200
    dashboard.assert_called_once_with("synthetic")
    run.assert_not_called()
    dispatch.assert_not_called()


def test_job_contract_preserves_zip_and_frequency_without_scheduler():
    job = JobInput.model_validate({"name": "Austin demo", "source_key": "synthetic-files", "poll_interval_minutes": 30, "filters": {"states": ["TX"], "postal_codes": ["78701"], "property_types": ["condo"], "min_price": "200000", "max_price": "700000"}})
    assert job.filters.postal_codes == ("78701",)
    assert job.poll_interval_minutes == 30


def test_ghl_mapping_does_not_accept_unknown_or_duplicate_fields():
    import pytest
    from pydantic import ValidationError
    for mapping in ({"unsupported": "remote"}, {"agent_id": "same", "revision": "same"}):
        with pytest.raises(ValidationError):
            GhlSetupInput(evidence_reference="demo-reference", custom_fields=mapping)


def test_reserved_write_preserves_body_and_passes_typed_input(settings):
    app = create_app(settings, Mock(spec=Engine))
    job_id = "11111111-1111-4111-8111-111111111111"

    async def request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/api/v1/intelligence/workspace/jobs", headers={"X-Admin-Token": settings.admin_token.get_secret_value(), "X-Operator-Action": "reserve", "Idempotency-Key": job_id}, json={"name": "Demo", "source_key": "synthetic-files"})

    with patch("dwellcall.application.reserve_operator_action") as reserve, patch("dwellcall.workspace_routes.DiscoveryService.save", return_value={"id": job_id}) as save:
        response = asyncio.run(request())
    assert response.status_code == 200
    assert reserve.call_args.args[1] == job_id
    assert save.call_args.args[0].name == "Demo"


def test_duplicate_operator_action_cannot_reenter_the_mutation(settings):
    from dwellcall.errors import ApiError

    app = create_app(settings, Mock(spec=Engine))

    async def request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/api/v1/crm/ghl/jobs/process", headers={"X-Admin-Token": settings.admin_token.get_secret_value(), "X-Operator-Action": "reserve", "Idempotency-Key": "11111111-1111-4111-8111-111111111111"}, json={})

    with patch("dwellcall.application.reserve_operator_action", side_effect=ApiError(status_code=409, code="ACTION_ALREADY_SUBMITTED", message="Inspect history")), patch("dwellcall.crm.agent_routes.process_agent_jobs") as dispatch:
        response = asyncio.run(request())
    assert response.status_code == 409
    assert response.headers["Cache-Control"] == "no-store"
    dispatch.assert_not_called()
