from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.cors import CORSMiddleware

from dwellcall.account_access.routes import create_account_router
from dwellcall.billing.routes import create_billing_router
from dwellcall.crm.agent_routes import create_agent_crm_router, create_crm_provider_router
from dwellcall.crm.routes import create_crm_router
from dwellcall.crm.settings import CrmSettings
from dwellcall.database.connection import DatabaseReadinessError, check_database_readiness
from dwellcall.errors import ApiError, api_error_handler
from dwellcall.listings.routes import create_listing_router
from dwellcall.listings.settings import ListingSettings
from dwellcall.settings import ApiSettings
from dwellcall.workspace_routes import create_workspace_router
from dwellcall.operator_actions import reserve_operator_action


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: Literal["api"]
    environment: str


class ReadinessResponse(HealthResponse):
    database: Literal["ready"]


def create_app(
    settings: ApiSettings,
    database_engine: Engine,
    crm_settings: CrmSettings | None = None,
    listing_settings: ListingSettings | None = None,
) -> FastAPI:
    session_factory = sessionmaker(
        bind=database_engine, class_=Session, expire_on_commit=False,
    )
    gateway = None
    consultant = None
    from dwellcall.telephony.outbound.provider import create_outbound_provider
    from dwellcall.telephony.outbound.routes import create_outbound_router
    from dwellcall.telephony.outbound.service import OutboundCallService

    outbound = OutboundCallService(session_factory, settings, create_outbound_provider(settings))
    if settings.retell_test_audio_enabled or (settings.outbound_enabled and settings.outbound_provider == "retell") or settings.browser_text_enabled:
        from dwellcall.consultant.catalog import load_catalog
        from dwellcall.consultant.graph import PropertyConsultant
        consultant = PropertyConsultant(settings, load_catalog(settings))
    if settings.retell_test_audio_enabled or (settings.outbound_provider == "retell" and (settings.outbound_enabled or (settings.retell_api_key and settings.outbound_agent_id))):
        from dwellcall.telephony.retell.provider import RetellGateway

        gateway = RetellGateway(settings)

    from dwellcall.conversations.provider import BrowserProvider
    from dwellcall.conversations.routes import create_conversation_router
    from dwellcall.conversations.service import BrowserConversationService

    browser = BrowserConversationService(session_factory, settings, consultant, BrowserProvider(settings, gateway) if gateway else None)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if consultant is not None:
                await consultant.close()
            if gateway is not None:
                await gateway.close()
            database_engine.dispose()

    application = FastAPI(
        title="DwellCall API", version="0.1.0", docs_url=None, redoc_url=None,
        openapi_url=None, lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type", "X-Correlation-ID", "X-Admin-Token", "Idempotency-Key"],
        expose_headers=["X-Correlation-ID"],
    )
    crm = crm_settings or CrmSettings(
        app_environment=settings.app_environment, business_name=settings.business_name,
    )
    if crm.crm_provider == "followupboss":
        if settings.admin_token is None or len(settings.admin_token.get_secret_value()) < 32:
            raise ValueError("CRM administration requires a strong ADMIN_TOKEN")
        application.include_router(create_crm_router(settings, session_factory, crm))
    application.include_router(create_account_router(settings, session_factory))
    application.include_router(create_billing_router(settings, session_factory))
    application.include_router(create_crm_provider_router(settings, crm))
    application.include_router(create_agent_crm_router(settings, session_factory, crm))
    application.include_router(create_agent_crm_router(settings, session_factory, crm, provider_name="hubspot"))
    application.include_router(create_outbound_router(settings, outbound))
    from dwellcall.telephony.outbound.review_routes import create_lead_review_router
    application.include_router(create_lead_review_router(settings, outbound))
    from dwellcall.telephony.outbound.demo_routes import create_demo_router
    application.include_router(create_demo_router(settings, outbound))
    application.include_router(create_conversation_router(settings, browser))
    if gateway is not None:
        from dwellcall.telephony.retell.routes import create_retell_router

        application.include_router(
            create_retell_router(settings, session_factory, gateway, consultant, outbound, browser)
        )
    listing = listing_settings or ListingSettings()
    if listing.listing_intelligence_enabled:
        application.include_router(create_listing_router(settings, session_factory, listing, crm))
        application.include_router(create_workspace_router(settings, session_factory, listing, crm))

    @application.exception_handler(ApiError)
    async def handle_api_error(request: Request, error: Exception) -> JSONResponse:
        if not isinstance(error, ApiError):
            raise error
        return await api_error_handler(request, error)

    @application.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        field_errors = [
            {
                "path": ".".join(str(part) for part in item["loc"]),
                "message": item["msg"],
                "type": item["type"],
            }
            for item in error.errors()
        ]
        validation_error = ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="VALIDATION_FAILED",
            message="The request did not satisfy the API contract",
            details={"fields": field_errors},
        )
        return await api_error_handler(request, validation_error)

    @application.exception_handler(SQLAlchemyError)
    async def database_error_handler(
        request: Request, error: SQLAlchemyError,
    ) -> JSONResponse:
        return await api_error_handler(request, ApiError(
            status_code=503, code="DATABASE_UNAVAILABLE",
            message="The operation is unavailable; existing work is retained",
        ))

    @application.middleware("http")
    async def add_correlation_id(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        raw_correlation_id = request.headers.get("X-Correlation-ID")
        try:
            correlation_id = UUID(raw_correlation_id) if raw_correlation_id else uuid4()
        except ValueError:
            correlation_id = uuid4()
        request.state.correlation_id = str(correlation_id)
        if request.url.path.startswith("/api/v1/account/") and request.method == "POST":
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > 4096:
                    denied = await api_error_handler(request, ApiError(status_code=413, code="AUTH_REQUEST_TOO_LARGE", message="The sign-in form is too large"))
                    denied.headers["Cache-Control"] = "no-store"
                    return denied
                body.extend(chunk)
            request._body = bytes(body)
        if request.method in {"POST", "PUT", "DELETE"} and request.url.path.startswith(("/api/v1/intelligence", "/api/v1/crm")) and request.headers.get("X-Operator-Action") == "reserve":
            try:
                from starlette.concurrency import run_in_threadpool
                require_admin = request.headers.get("X-Admin-Token")
                from dwellcall.admin_security import require_admin_token
                require_admin_token(settings, require_admin)
                key = request.headers.get("Idempotency-Key", "")
                body = bytearray()
                async for chunk in request.stream():
                    if len(body) + len(chunk) > listing.listing_max_import_bytes + 65536:
                        raise ApiError(status_code=413, code="ACTION_TOO_LARGE", message="Choose a smaller source file")
                    body.extend(chunk)
                request._body = bytes(body)
                await run_in_threadpool(reserve_operator_action, session_factory, key, request.method + " " + request.url.path + "?" + str(request.url.query), bytes(body))
            except ApiError as error:
                denied = await api_error_handler(request, error)
                denied.headers["Cache-Control"] = "no-store"
                denied.headers["X-Correlation-ID"] = str(correlation_id)
                return denied
            except SQLAlchemyError:
                denied = await api_error_handler(request, ApiError(status_code=503, code="ACTION_STORE_UNAVAILABLE", message="The action could not be reserved; inspect history before retrying"))
                denied.headers["Cache-Control"] = "no-store"
                denied.headers["X-Correlation-ID"] = str(correlation_id)
                return denied
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = str(correlation_id)
        if request.url.path.startswith(("/api/v1/billing", "/api/v1/account", "/api/v1/intelligence", "/api/v1/crm", "/api/v1/outbound", "/api/v1/retell")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="api",
            environment=settings.app_environment,
        )

    @application.get("/ready", response_model=ReadinessResponse)
    def ready() -> ReadinessResponse:
        try:
            check_database_readiness(database_engine)
        except DatabaseReadinessError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="database unavailable",
            ) from error

        return ReadinessResponse(
            status="ok",
            service="api",
            environment=settings.app_environment,
            database="ready",
        )

    return application
