from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from dwellcall.admin_security import require_admin_token
from dwellcall.crm.job_execution import JobDeadlineExceeded
from dwellcall.crm.settings import CrmSettings
from dwellcall.database.models import ListingReview, ListingSource
from dwellcall.database.models.workspace import DiscoveryAttempt, DiscoveryJob
from dwellcall.errors import ApiError
from dwellcall.listings.permissions import permission
from dwellcall.listings.queries import ListingQueries
from dwellcall.listings.reviews import review_data
from dwellcall.listings.registry import SYNTHETIC_PERMISSION, SYNTHETIC_SOURCE_KEY
from dwellcall.listings.routes import bounded_body
from dwellcall.listings.schemas import DiscoveryFilters, SourceKey
from dwellcall.listings.service import ListingIngestionService, audit, ingestion_lock
from dwellcall.listings.settings import ListingSettings
from dwellcall.settings import ApiSettings
from dwellcall.workspace_queries import WorkspaceQueries


class JobInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    source_key: SourceKey
    enabled: bool = True
    filters: DiscoveryFilters = Field(default_factory=DiscoveryFilters)
    poll_interval_minutes: int = Field(default=60, ge=15, le=1440)
    expected_version: int = Field(default=0, ge=0)


class RunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str | None = Field(default=None, max_length=1_048_576)
    format: Literal["json", "csv"] = "json"


def job_data(job: DiscoveryJob) -> dict[str, object]:
    return {"id": str(job.id), "name": job.name, "source_key": job.source_key,
            "enabled": job.enabled, "filters": job.filters, "poll_interval_minutes": job.poll_interval_minutes,
            "version": job.version, "created_at": job.created_at, "updated_at": job.updated_at,
            "scheduling_active": False, "scheduling_supported": job.source_key == SYNTHETIC_SOURCE_KEY, "trigger_mode": "manual_file_import"}


def attempt_data(row: DiscoveryAttempt) -> dict[str, object]:
    return {"id": str(row.id), "job_id": str(row.job_id), "request_id": str(row.request_id),
            "status": row.status, "started_at": row.started_at, "finished_at": row.finished_at,
            "code": row.code, "result": row.result,
            "stale": row.status == "running" and row.started_at < datetime.now(UTC) - timedelta(seconds=90)}


class DiscoveryService:
    def __init__(self, sessions: sessionmaker[Session], listing: ListingSettings, crm: CrmSettings) -> None:
        self.sessions, self.listing, self.crm = sessions, listing, crm

    def save(self, request: JobInput, job_id: UUID | None = None) -> dict[str, object]:
        now = datetime.now(UTC)
        with self.sessions() as session, session.begin():
            ingestion_lock(session)
            source = session.get(ListingSource, request.source_key)
            if source is None:
                raise ApiError(status_code=409, code="SOURCE_REQUIRED", message="Register source permissions first")
            if permission(source).provider != "file":
                raise ApiError(status_code=409, code="CONNECTOR_UNAVAILABLE", message="This provider has no authorized connector")
            job = session.get(DiscoveryJob, job_id, with_for_update=True) if job_id else None
            if job_id and job is None:
                raise ApiError(status_code=404, code="JOB_NOT_FOUND", message="Discovery job was not found")
            if request.expected_version != (job.version if job else 0):
                raise ApiError(status_code=409, code="JOB_CHANGED", message="Refresh this job before saving changes")
            if job is None:
                job = DiscoveryJob(id=uuid4(), created_at=now, version=0)
                session.add(job)
            job.name, job.source_key, job.enabled = request.name, request.source_key, request.enabled
            job.filters = request.filters.model_dump(mode="json")
            job.poll_interval_minutes, job.updated_at = request.poll_interval_minutes, now
            job.version += 1
            session.flush()
            return job_data(job)

    def run(self, job_id: UUID, request_id: UUID, request: RunInput, *, only_if_due: bool = False) -> dict[str, object]:
        now = datetime.now(UTC)
        with self.sessions() as session, session.begin():
            ingestion_lock(session)
            previous = session.scalar(select(DiscoveryAttempt).where(DiscoveryAttempt.request_id == request_id))
            if previous:
                if previous.job_id != job_id:
                    raise ApiError(status_code=409, code="REQUEST_ID_REUSED", message="Use a distinct action for a different job")
                return attempt_data(previous)
            job = session.get(DiscoveryJob, job_id, with_for_update=True)
            if job is None or not job.enabled:
                raise ApiError(status_code=409, code="JOB_DISABLED", message="Enable an existing job before running it")
            if only_if_due:
                if job.source_key != SYNTHETIC_SOURCE_KEY:
                    raise ApiError(status_code=409, code="SCHEDULING_UNSUPPORTED", message="Scheduled polling supports only the bundled synthetic source")
                latest = session.scalar(select(func.max(DiscoveryAttempt.started_at)).where(DiscoveryAttempt.job_id == job_id))
                if latest and latest + timedelta(minutes=job.poll_interval_minutes) > now:
                    raise ApiError(status_code=409, code="JOB_NOT_DUE", message="This job is not due yet")
            active = session.scalar(select(DiscoveryAttempt).where(DiscoveryAttempt.job_id == job_id, DiscoveryAttempt.status == "running"))
            if active and active.started_at > now - timedelta(seconds=90):
                raise ApiError(status_code=409, code="JOB_RUNNING", message="This job is already running; refresh its history")
            if active:
                active.status, active.code, active.finished_at = "failed", "INTERRUPTED_CHECK_IMPORT_HISTORY", now
            source = session.get(ListingSource, job.source_key)
            if source is None or permission(source).provider != "file":
                raise ApiError(status_code=409, code="CONNECTOR_UNAVAILABLE", message="Only permission-scoped file imports are available")
            if request.content is None and not (job.source_key == SYNTHETIC_SOURCE_KEY and permission(source).data_mode == "synthetic"):
                raise ApiError(status_code=422, code="FILE_REQUIRED", message="Select an authorized source file for this run")
            source_key, filters = job.source_key, DiscoveryFilters.model_validate(job.filters)
            attempt = DiscoveryAttempt(id=uuid4(), job_id=job_id, request_id=request_id, status="running", started_at=now, result={})
            session.add(attempt)
            attempt_id = attempt.id
        try:
            content = request.content.encode() if request.content is not None else (
                Path(__file__).resolve().parents[4] / "data/listings/synthetic-listings.json"
            ).read_bytes()
            result = ListingIngestionService(self.sessions, self.listing, self.crm).ingest(source_key, content, request.format, request_id, filters)
            status, code = str(result["status"]), None
        except (ApiError, JobDeadlineExceeded, OSError) as error:
            status, code, result = "failed", error.code if isinstance(error, ApiError) else "DISCOVERY_INTERRUPTED", {}
        with self.sessions() as session, session.begin():
            saved = session.get(DiscoveryAttempt, attempt_id, with_for_update=True)
            if saved is None:
                raise ApiError(status_code=409, code="ATTEMPT_UNAVAILABLE", message="Refresh discovery history")
            saved.status, saved.code, saved.result, saved.finished_at = status, code, result, datetime.now(UTC)
            return attempt_data(saved)


def create_workspace_router(api: ApiSettings, sessions: sessionmaker[Session], listing: ListingSettings, crm: CrmSettings) -> APIRouter:
    def admin(response: Response, token: Annotated[str | None, Header(alias="X-Admin-Token")] = None) -> None:
        require_admin_token(api, token)
        response.headers["Cache-Control"] = "no-store"
    router = APIRouter(prefix="/api/v1/intelligence/workspace", dependencies=[Depends(admin)])
    queries, existing, discovery = WorkspaceQueries(sessions, crm), ListingQueries(sessions, crm), DiscoveryService(sessions, listing, crm)

    async def parse(request: Request, model: type[BaseModel]) -> BaseModel:
        try:
            return model.model_validate_json(await bounded_body(request, listing.listing_max_import_bytes + 65536))
        except ValidationError:
            raise ApiError(status_code=422, code="WORKSPACE_INPUT_INVALID", message="Check the required fields, filter values and size limits") from None

    @router.get("/dashboard")
    def dashboard(mode: Literal["synthetic", "live"] = "synthetic") -> dict[str, object]:
        return queries.dashboard(mode)

    @router.get("/listings/{listing_id}")
    def listing_detail(listing_id: UUID, mode: Literal["synthetic", "live"] = "synthetic") -> dict[str, object]:
        return queries.listing(listing_id, mode)

    @router.get("/listings/{listing_id}/history")
    def history(listing_id: UUID, mode: Literal["synthetic", "live"] = "synthetic", page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)) -> dict[str, object]:
        return queries.revisions(listing_id, mode, page, page_size)

    @router.get("/agents/{agent_id}")
    def agent_detail(agent_id: UUID, mode: Literal["synthetic", "live"] = "synthetic") -> dict[str, object]:
        result = existing.agents(1, 1, mode, reveal_contacts=True, agent_id=agent_id)
        if not result["items"]:
            raise ApiError(status_code=404, code="AGENT_NOT_FOUND", message="Agent is unavailable under current source rights")
        return result["items"][0]

    @router.get("/activity")
    def activity(mode: Literal["synthetic", "live"] = "synthetic", page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), kind: Literal["discovery", "listing", "review", "crm", "system"] | None = None, q: str = Query("", max_length=120), status: str | None = Query(None, max_length=24)) -> dict[str, object]:
        return queries.activity(mode, page, page_size, kind, q, status)

    @router.get("/reviews")
    def reviews(mode: Literal["synthetic", "live"] = "synthetic", page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), status: Literal["pending", "approved", "rejected"] | None = None) -> dict[str, object]:
        from sqlalchemy import text
        query = select(ListingReview).join(ListingSource).where(
            ListingSource.permission["data_mode"].astext == mode,
            ListingSource.permission["display_allowed"].as_boolean().is_(True),
            ListingSource.permission["store_allowed"].as_boolean().is_(True),
            ListingReview.created_at > func.now() - ListingSource.permission["retention_days"].as_integer() * text("INTERVAL '1 day'"),
        )
        if status:
            query = query.where(ListingReview.status == status)
        with sessions() as session:
            total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
            rows = session.scalars(query.order_by(ListingReview.created_at.desc(), ListingReview.id).offset((page-1)*page_size).limit(page_size))
            return {"items": [review_data(row) for row in rows], "total": total, "page": page, "page_size": page_size}

    @router.get("/jobs")
    def jobs(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)) -> dict[str, object]:
        with sessions() as session:
            total = session.scalar(select(func.count()).select_from(DiscoveryJob)) or 0
            rows = session.scalars(select(DiscoveryJob).order_by(DiscoveryJob.created_at.desc(), DiscoveryJob.id).offset((page-1)*page_size).limit(page_size))
            return {"items": [job_data(row) for row in rows], "total": total, "page": page, "page_size": page_size}

    @router.post("/demo/setup")
    def demo_setup() -> dict[str, object]:
        with sessions() as session, session.begin():
            ingestion_lock(session)
            if session.get(ListingSource, SYNTHETIC_SOURCE_KEY):
                return {"source_key": SYNTHETIC_SOURCE_KEY, "existing_permissions_preserved": True}
            source = ListingSource(key=SYNTHETIC_SOURCE_KEY, permission=dict(SYNTHETIC_PERMISSION), permission_version=1, created_at=datetime.now(UTC))
            session.add(source)
            session.flush()
            audit(session, source, "SOURCE_PERMISSION_UPDATED", {"permission_version": 1, "enabled": True})
            return {"source_key": SYNTHETIC_SOURCE_KEY, "permission_version": 1, "provider_implemented": True}

    @router.post("/jobs")
    async def create_job(request: Request) -> dict[str, object]:
        data = await parse(request, JobInput)
        assert isinstance(data, JobInput)
        return await run_in_threadpool(discovery.save, data)

    @router.put("/jobs/{job_id}")
    async def edit_job(job_id: UUID, request: Request) -> dict[str, object]:
        data = await parse(request, JobInput)
        assert isinstance(data, JobInput)
        return await run_in_threadpool(discovery.save, data, job_id)

    @router.post("/jobs/{job_id}/run")
    async def trigger(job_id: UUID, request: Request, request_id: Annotated[UUID, Header(alias="Idempotency-Key")]) -> dict[str, object]:
        data = await parse(request, RunInput)
        assert isinstance(data, RunInput)
        return await run_in_threadpool(discovery.run, job_id, request_id, data)

    @router.get("/attempts")
    def attempts(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), job_id: UUID | None = None) -> dict[str, object]:
        query = select(DiscoveryAttempt)
        if job_id:
            query = query.where(DiscoveryAttempt.job_id == job_id)
        with sessions() as session:
            total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
            rows = session.scalars(query.order_by(DiscoveryAttempt.started_at.desc(), DiscoveryAttempt.id).offset((page-1)*page_size).limit(page_size))
            return {"items": [attempt_data(row) for row in rows], "total": total, "page": page, "page_size": page_size}

    return router
