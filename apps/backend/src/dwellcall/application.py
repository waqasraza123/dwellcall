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

from dwellcall.consultant.catalog import load_catalog
from dwellcall.consultant.graph import RentalConsultant
from dwellcall.crm.routes import create_crm_router
from dwellcall.crm.settings import CrmSettings
from dwellcall.database.connection import DatabaseReadinessError, check_database_readiness
from dwellcall.errors import ApiError, api_error_handler
from dwellcall.settings import ApiSettings
from dwellcall.telephony.retell.provider import RetellGateway
from dwellcall.telephony.retell.routes import create_retell_router


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
) -> FastAPI:
    session_factory = sessionmaker(
        bind=database_engine, class_=Session, expire_on_commit=False,
    )
    gateway = RetellGateway(settings) if settings.retell_test_audio_enabled else None
    consultant = (
        RentalConsultant(settings, load_catalog(settings))
        if settings.retell_test_audio_enabled else None
    )

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
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Correlation-ID", "X-Admin-Token"],
        expose_headers=["X-Correlation-ID"],
    )
    crm = crm_settings or CrmSettings(
        app_environment=settings.app_environment, business_name=settings.business_name,
    )
    if crm.crm_provider != "none":
        if settings.admin_token is None or len(settings.admin_token.get_secret_value()) < 32:
            raise ValueError("CRM administration requires a strong ADMIN_TOKEN")
        application.include_router(create_crm_router(settings, session_factory, crm))
    if gateway is not None and consultant is not None:
        application.include_router(
            create_retell_router(settings, session_factory, gateway, consultant)
        )

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
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = str(correlation_id)
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
