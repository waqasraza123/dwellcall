from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from dwellcall.admin_security import require_admin_token
from dwellcall.crm.schemas import (
    DispatchResumeInput, ExportAuthorization, ExportStatus, ReconciliationInput,
)
from dwellcall.crm.service import CrmService
from dwellcall.crm.settings import CrmSettings
from dwellcall.errors import ApiError
from dwellcall.settings import ApiSettings


async def bounded_body(request: Request) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16384:
            raise ApiError(status_code=413, code="CRM_REQUEST_TOO_LARGE", message="CRM authorization exceeds the size limit")
    return bytes(body)


def create_crm_router(
    api: ApiSettings, sessions: sessionmaker[Session], settings: CrmSettings,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/crm/admin")
    service = CrmService(sessions, api, settings)

    def admin(
        response: Response,
        supplied: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
    ) -> None:
        require_admin_token(api, supplied)
        response.headers["Cache-Control"] = "no-store"

    @router.get("/destination", dependencies=[Depends(admin)])
    def destination() -> dict[str, str | bool]:
        return {
            "provider": settings.crm_provider, "destination": settings.destination,
            "sync_enabled": settings.dispatch_enabled,
            "business_name": api.business_name,
            "source": settings.followupboss_lead_source,
        }

    @router.post("/exports", response_model=ExportStatus, dependencies=[Depends(admin)])
    async def authorize(request: Request) -> ExportStatus:
        try:
            data = ExportAuthorization.model_validate_json(await bounded_body(request))
        except ValidationError as error:
            raise ApiError(status_code=422, code="CRM_AUTHORIZATION_INVALID", message="Confirm the snapshot and separate storage/CRM permissions") from error
        return await run_in_threadpool(service.authorize, data)

    @router.post("/dispatch/resume", dependencies=[Depends(admin)])
    async def resume(request: Request) -> dict[str, bool]:
        try:
            data = DispatchResumeInput.model_validate_json(await bounded_body(request))
        except ValidationError as error:
            raise ApiError(status_code=422, code="CRM_RESUME_INVALID", message="Provide an opaque operator evidence reference") from error
        return await run_in_threadpool(service.resume_dispatch, data.evidence_reference)

    @router.get("/exports/{export_id}", response_model=ExportStatus, dependencies=[Depends(admin)])
    def status(export_id: UUID) -> ExportStatus:
        return service.get(export_id)

    @router.post("/exports/{export_id}/revoke", response_model=ExportStatus, dependencies=[Depends(admin)])
    def revoke(export_id: UUID) -> ExportStatus:
        return service.revoke(export_id)

    @router.post("/exports/{export_id}/reconcile", response_model=ExportStatus, dependencies=[Depends(admin)])
    async def reconcile(export_id: UUID, request: Request) -> ExportStatus:
        try:
            data = ReconciliationInput.model_validate_json(await bounded_body(request))
        except ValidationError as error:
            raise ApiError(status_code=422, code="CRM_RECONCILIATION_INVALID", message="Provide a resolution and opaque evidence reference") from error
        return await run_in_threadpool(service.reconcile, export_id, data)

    return router
