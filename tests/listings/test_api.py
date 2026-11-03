import asyncio
from unittest.mock import Mock, patch

from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import Engine

from dwellcall.application import create_app
from dwellcall.listings.settings import ListingSettings
from dwellcall.settings import ApiSettings


def test_authentication_precedes_import_body_processing(settings: ApiSettings) -> None:
    engine = Mock(spec=Engine)
    app = create_app(settings, engine)

    async def request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post(
                "/api/v1/intelligence/sources/synthetic-files/imports",
                headers={"Idempotency-Key": "11111111-1111-4111-8111-111111111111"},
                content=b"untrusted body",
            )

    with patch("dwellcall.listings.routes.bounded_body") as body:
        response = asyncio.run(request())
    assert response.status_code == 401
    body.assert_not_called()
    engine.connect.assert_not_called()


def test_viewer_cannot_import_or_view_contact_values(settings: ApiSettings) -> None:
    app = create_app(settings, Mock(spec=Engine), listing_settings=ListingSettings(
        listing_viewer_token="v" * 43,
    ))

    async def requests():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = {"X-Admin-Token": "v" * 43}
            listing = await client.get("/api/v1/intelligence/agents", headers=headers)
            denied = await client.post(
                "/api/v1/intelligence/sources/synthetic-files/imports",
                headers={**headers, "Idempotency-Key": "11111111-1111-4111-8111-111111111111"},
                content=b"{}",
            )
            return listing, denied

    with patch("dwellcall.listings.queries.ListingQueries.agents", return_value={"items": []}) as query:
        listing, denied = asyncio.run(requests())
    assert listing.status_code == 200
    assert listing.headers["Cache-Control"] == "no-store"
    query.assert_called_once_with(1, 25, "synthetic", reveal_contacts=False, q="", state=None)
    assert denied.status_code == 401


def test_voice_is_optional_and_intelligence_can_be_disabled(settings: ApiSettings) -> None:
    app = create_app(settings, Mock(spec=Engine), listing_settings=ListingSettings(
        listing_intelligence_enabled=False,
    ))
    assert all("intelligence" not in route.path for route in app.routes)
    assert all("retell" not in route.path for route in app.routes)


def test_review_inspection_and_resolution_require_admin(settings: ApiSettings) -> None:
    app = create_app(settings, Mock(spec=Engine), listing_settings=ListingSettings(
        listing_viewer_token="v" * 43,
    ))

    async def requests():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            responses = []
            for headers in ({}, {"X-Admin-Token": "v" * 43}):
                responses.append(await client.get(
                    "/api/v1/intelligence/reviews/11111111-1111-4111-8111-111111111111", headers=headers,
                ))
                responses.append(await client.post(
                    "/api/v1/intelligence/reviews/11111111-1111-4111-8111-111111111111/resolve",
                    headers=headers, content=b"untrusted body",
                ))
            return responses

    with patch("dwellcall.listings.routes.bounded_body") as body, patch("dwellcall.listings.reviews.ListingReviewService.resolve") as resolve:
        responses = asyncio.run(requests())
    assert all(response.status_code == 401 for response in responses)
    body.assert_not_called()
    resolve.assert_not_called()


def test_authenticated_review_resolution_validates_body(settings: ApiSettings) -> None:
    app = create_app(settings, Mock(spec=Engine))

    async def requests():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = {"X-Admin-Token": settings.admin_token.get_secret_value()}
            responses = []
            for body in (
                b'{"decision":"approve","evidence_reference":"demo"}',
                b'{"decision":"reject","evidence_reference":"contains spaces"}',
                b'x' * 4097,
            ):
                responses.append(await client.post(
                    "/api/v1/intelligence/reviews/11111111-1111-4111-8111-111111111111/resolve",
                    headers=headers, content=body,
                ))
            return responses

    with patch("dwellcall.listings.reviews.ListingReviewService.resolve") as resolve:
        responses = asyncio.run(requests())
    assert [response.status_code for response in responses] == [422, 422, 413]
    resolve.assert_not_called()


def test_authenticated_review_resolution_passes_typed_decision(settings: ApiSettings) -> None:
    from uuid import UUID

    app = create_app(settings, Mock(spec=Engine))
    review_id = "11111111-1111-4111-8111-111111111111"

    async def request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post(
                f"/api/v1/intelligence/reviews/{review_id}/resolve",
                headers={"X-Admin-Token": settings.admin_token.get_secret_value()},
                json={"decision": "reject", "evidence_reference": "synthetic-case-001"},
            )

    with patch("dwellcall.listings.reviews.ListingReviewService.resolve", return_value={"status": "rejected"}) as resolve:
        response = asyncio.run(request())
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert resolve.call_args.args[0] == UUID(review_id)
    assert resolve.call_args.args[1].decision == "reject"
