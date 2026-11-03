from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from dwellcall.admin_security import require_admin_token
from dwellcall.crm.agent_jobs import process_agent_jobs, reconcile_job
from dwellcall.crm.agent_schemas import (
    AgentAuditPage, AgentJobPage, AgentJobStatus, AgentPreviewPage, AgentSyncRequest, ContactBinding,
    GhlSetupInput, LocationProvisionInput, OperatorEvidence,
)
from dwellcall.crm.agent_service import AgentCrmService, job_audit_history
from dwellcall.crm.ghl_setup import GhlConfigurationService
from dwellcall.crm.job_execution import JobDeadlineExceeded
from dwellcall.crm.routes import bounded_body
from dwellcall.crm.settings import CrmSettings
from dwellcall.crm.hubspot_setup import HubSpotConfigurationService, HubSpotPropertyCreation, HubSpotSetupInput
from dwellcall.errors import ApiError
from dwellcall.settings import ApiSettings


async def parse_body[T: BaseModel](request: Request, model: type[T]) -> T:
    try:
        return model.model_validate_json(await bounded_body(request))
    except ValidationError:
        raise ApiError(status_code=422, code="GHL_REQUEST_INVALID", message="Provide a valid bounded operator request; input values are not echoed") from None


def create_agent_crm_router(api: ApiSettings, sessions: sessionmaker[Session], settings: CrmSettings, provider_name: Literal["gohighlevel", "hubspot"] = "gohighlevel") -> APIRouter:
    def admin(response: Response, token: Annotated[str | None, Header(alias="X-Admin-Token")] = None) -> None:
        require_admin_token(api, token)
        response.headers["Cache-Control"] = "no-store"

    def selected() -> None:
        if settings.crm_provider != provider_name and (provider_name == "hubspot" or settings.crm_provider == "hubspot"):
            raise ApiError(status_code=409, code="CRM_PROVIDER_NOT_SELECTED", message="Select this CRM in backend configuration before using its workflows")

    router = APIRouter(prefix="/api/v1/crm/" + ("hubspot" if provider_name == "hubspot" else "ghl"), dependencies=[Depends(admin)])
    service, configuration = AgentCrmService(sessions, settings), GhlConfigurationService(sessions, settings)

    @router.get("/status")
    def status() -> dict[str, object]:
        return HubSpotConfigurationService(sessions, settings).status() if provider_name == "hubspot" else configuration.status()

    @router.post("/setup")
    async def setup(request: Request) -> dict[str, object]:
        selected()
        if provider_name == "hubspot":
            hubspot_data = await parse_body(request, HubSpotSetupInput)
            return await run_in_threadpool(HubSpotConfigurationService(sessions, settings).setup, hubspot_data)
        data = await parse_body(request, GhlSetupInput)
        return await run_in_threadpool(configuration.setup, data)

    @router.get("/agents", response_model=AgentPreviewPage, dependencies=[Depends(selected)])
    def preview(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)) -> AgentPreviewPage:
        return service.preview(page, page_size)

    @router.post("/agents/queue", response_model=list[AgentJobStatus], dependencies=[Depends(selected)])
    async def queue(request: Request) -> list[AgentJobStatus]:
        data = await parse_body(request, AgentSyncRequest)
        return await run_in_threadpool(service.queue, data.agent_ids)

    @router.post("/agents/{agent_id}/bind", dependencies=[Depends(selected)])
    async def bind(agent_id: UUID, request: Request) -> dict[str, object]:
        data = await parse_body(request, ContactBinding)
        if provider_name == "hubspot":
            return await run_in_threadpool(HubSpotConfigurationService(sessions, settings).bind, agent_id, data)
        return await run_in_threadpool(configuration.bind, agent_id, data)

    @router.get("/jobs", response_model=AgentJobPage, dependencies=[Depends(selected)])
    def history(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                status: Literal["pending", "sending", "retry_wait", "sent", "unknown", "failed", "cancelled"] | None = None,
                agent_id: UUID | None = None) -> AgentJobPage:
        return service.history(page, page_size, status, agent_id)

    @router.get("/jobs/{job_id}/audit", response_model=AgentAuditPage, dependencies=[Depends(selected)])
    def audit_history(job_id: UUID, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)) -> AgentAuditPage:
        if not settings.agent_destination_configured:
            raise ApiError(status_code=409, code=settings.agent_code("NOT_CONFIGURED"), message="Configure the selected CRM destination first")
        return job_audit_history(sessions, settings, job_id, page, page_size)

    @router.post("/jobs/process", dependencies=[Depends(selected)])
    def process(batch_size: int = Query(12, ge=1, le=50)) -> dict[str, object]:
        from dataclasses import asdict

        return asdict(process_agent_jobs(sessions, settings, batch_size=batch_size))

    @router.post("/jobs/{job_id}/retry", response_model=AgentJobStatus, dependencies=[Depends(selected)])
    async def retry(job_id: UUID, request: Request) -> AgentJobStatus:
        data = await parse_body(request, OperatorEvidence)
        return await run_in_threadpool(service.retry, job_id, data.evidence_reference)

    @router.post("/jobs/{job_id}/reconcile", response_model=AgentJobStatus, dependencies=[Depends(selected)])
    async def reconcile(job_id: UUID, request: Request) -> AgentJobStatus:
        data = await parse_body(request, OperatorEvidence)
        try:
            return await run_in_threadpool(reconcile_job, sessions, settings, job_id, data.evidence_reference)
        except JobDeadlineExceeded:
            raise ApiError(status_code=503, code=settings.agent_code("RECONCILIATION_DEFERRED"), message="Reconciliation budget exceeded; the uncertain reservation is retained") from None

    if provider_name == "hubspot":
        @router.post("/properties/create", dependencies=[Depends(selected)])
        async def create_properties(request: Request) -> dict[str, object]:
            data = await parse_body(request, HubSpotPropertyCreation)
            return await run_in_threadpool(HubSpotConfigurationService(sessions, settings).create_properties, data)
    else:
        @router.post("/locations/provision")
        async def provision(request: Request) -> dict[str, object]:
            data = await parse_body(request, LocationProvisionInput)
            return await run_in_threadpool(configuration.provision, data)

    return router


def create_crm_provider_router(api: ApiSettings, settings: CrmSettings) -> APIRouter:
    def admin(response: Response, token: Annotated[str | None, Header(alias="X-Admin-Token")] = None) -> None:
        require_admin_token(api, token)
        response.headers["Cache-Control"] = "no-store"

    router = APIRouter(prefix="/api/v1/crm", dependencies=[Depends(admin)])

    @router.get("/providers")
    def providers() -> dict[str, object]:
        return {"selected": settings.crm_provider, "providers": [
            {"key": "gohighlevel", "label": "GoHighLevel", "primary": True, "workflow": "verified_listing_agents"},
            {"key": "followupboss", "label": "Follow Up Boss", "primary": False, "workflow": "consented_consultations"},
            {"key": "hubspot", "label": "HubSpot", "primary": False, "workflow": "verified_listing_agents"},
        ]}

    return router
