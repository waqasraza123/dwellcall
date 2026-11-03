import secrets
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from dwellcall.admin_security import require_admin_token
from dwellcall.crm.settings import CrmSettings
from dwellcall.crm.job_execution import JobDeadlineExceeded
from dwellcall.errors import ApiError
from dwellcall.listings.providers import provider_availability
from dwellcall.listings.queries import ListingQueries
from dwellcall.listings.registry import SourceRegistryService
from dwellcall.listings.reviews import ListingReviewService
from dwellcall.listings.schemas import DiscoveryFilters, ReviewResolutionInput, SourceKey, SourcePermissionInput
from dwellcall.listings.service import ListingIngestionService
from dwellcall.listings.settings import ListingSettings
from dwellcall.settings import ApiSettings


async def bounded_body(request: Request, limit: int) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > limit:
            raise ApiError(status_code=413, code="IMPORT_TOO_LARGE", message="Import exceeds the configured size limit")
        body.extend(chunk)
    return bytes(body)


def create_listing_router(api: ApiSettings, sessions: sessionmaker[Session], settings: ListingSettings, crm_settings: CrmSettings | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/intelligence")
    ingestion, registry, queries = ListingIngestionService(sessions, settings, crm_settings), SourceRegistryService(sessions), ListingQueries(sessions, crm_settings)
    review_service = ListingReviewService(sessions)

    def admin(response: Response, token: Annotated[str | None, Header(alias="X-Admin-Token")] = None) -> None:
        require_admin_token(api, token)
        response.headers["Cache-Control"] = "no-store"

    def reader(response: Response, token: Annotated[str | None, Header(alias="X-Admin-Token")] = None) -> Literal["admin", "viewer"]:
        response.headers["Cache-Control"] = "no-store"
        if api.admin_token is not None and token is not None and secrets.compare_digest(token.encode(), api.admin_token.get_secret_value().encode()):
            require_admin_token(api, token)
            return "admin"
        expected = settings.listing_viewer_token
        if expected is not None and token is not None and secrets.compare_digest(token.encode(), expected.get_secret_value().encode()):
            return "viewer"
        raise ApiError(status_code=401, code="OPERATOR_AUTH_REQUIRED", message="Operator authentication is required")

    @router.get("/providers", dependencies=[Depends(reader)])
    def providers() -> dict[str, object]:
        return {"providers": provider_availability(), "primary_crm": "gohighlevel", "listing_crm_state": "implemented_unverified_disabled_by_default", "outreach_enabled": False}

    @router.get("/sources", dependencies=[Depends(admin)])
    def sources() -> list[dict[str, object]]:
        return queries.sources()

    @router.put("/sources/{key}", dependencies=[Depends(admin)])
    async def configure(key: SourceKey, request: Request) -> dict[str, object]:
        try:
            config = SourcePermissionInput.model_validate_json(await bounded_body(request, 16384))
        except ValidationError:
            raise ApiError(status_code=422, code="SOURCE_PERMISSION_INVALID", message="Provide a valid, explicit source permission registry entry") from None
        return await run_in_threadpool(registry.configure, key, config)

    @router.post("/sources/{key}/imports", dependencies=[Depends(admin)])
    async def ingest(
        key: SourceKey, request: Request,
        request_id: Annotated[UUID, Header(alias="Idempotency-Key")],
        format: Literal["csv", "json"] = "json",
        state: str | None = Query(default=None, max_length=2),
        city: str | None = Query(default=None, max_length=120),
        min_price: str | None = Query(default=None, max_length=20),
        max_price: str | None = Query(default=None, max_length=20),
        currency: str = Query(default="USD", max_length=3),
        property_type: str | None = Query(default=None, max_length=30),
        status: str | None = Query(default=None, max_length=20),
    ) -> dict[str, object]:
        try:
            filters = DiscoveryFilters.model_validate({
                "states": [state.upper()] if state else [], "cities": [city] if city else [],
                "min_price": min_price, "max_price": max_price, "currency": currency,
                "property_types": [property_type] if property_type else [], "statuses": [status] if status else [],
            })
        except ValidationError:
            raise ApiError(status_code=422, code="DISCOVERY_FILTERS_INVALID", message="Provide valid geographic, price and type filters") from None
        content = await bounded_body(request, settings.listing_max_import_bytes)
        try:
            return await run_in_threadpool(ingestion.ingest, key, content, format, request_id, filters)
        except JobDeadlineExceeded:
            raise ApiError(status_code=503, code="IMPORT_BUDGET_EXCEEDED", message="Import rolled back; retry the same request ID with a smaller bounded file") from None

    @router.get("/listings")
    def listings(
        role: Annotated[str, Depends(reader)], page: int = Query(default=1, ge=1),
        page_size: int = Query(default=25, ge=1, le=100), mode: Literal["synthetic", "live"] = "synthetic",
    ) -> dict[str, object]:
        return queries.listings(page, page_size, mode)

    @router.get("/agents")
    def agents(
        role: Annotated[str, Depends(reader)], page: int = Query(default=1, ge=1),
        page_size: int = Query(default=25, ge=1, le=100), mode: Literal["synthetic", "live"] = "synthetic",
    ) -> dict[str, object]:
        return queries.agents(page, page_size, mode, reveal_contacts=role == "admin")

    @router.post("/agents/{agent_id}/suppress", dependencies=[Depends(admin)])
    def suppress(agent_id: UUID) -> dict[str, bool]:
        return registry.suppress(agent_id)

    @router.post("/sources/{key}/purge", dependencies=[Depends(admin)])
    def purge(key: SourceKey, expired_only: bool = True) -> dict[str, int | bool]:
        return registry.purge(key, expired_only=expired_only)

    @router.get("/runs", dependencies=[Depends(admin)])
    def runs() -> list[dict[str, object]]:
        return queries.runs()

    @router.get("/reviews", dependencies=[Depends(admin)])
    def reviews() -> list[dict[str, object]]:
        return queries.reviews()

    @router.get("/reviews/{review_id}", dependencies=[Depends(admin)])
    def inspect_review(review_id: UUID) -> dict[str, object]:
        return review_service.inspect(review_id)

    @router.post("/reviews/{review_id}/resolve", dependencies=[Depends(admin)])
    async def resolve_review(review_id: UUID, request: Request) -> dict[str, object]:
        try:
            resolution = ReviewResolutionInput.model_validate_json(await bounded_body(request, 4096))
        except ValidationError:
            raise ApiError(status_code=422, code="REVIEW_RESOLUTION_INVALID", message="Provide approve/candidate or reject and an opaque evidence reference") from None
        return await run_in_threadpool(review_service.resolve, review_id, resolution)

    return router
