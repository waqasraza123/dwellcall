from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header

from dwellcall.admin_security import require_admin_token
from dwellcall.errors import ApiError
from dwellcall.settings import ApiSettings
from dwellcall.telephony.outbound.provider import OutboundProviderError
from dwellcall.telephony.outbound.schemas import BindInput, CallInput, CallResponse, CarrierEndedInput, ControlsInput, SuppressInput
from dwellcall.telephony.outbound.service import OutboundCallService


def create_outbound_router(settings: ApiSettings, service: OutboundCallService) -> APIRouter:
    def admin(supplied: Annotated[str | None, Header(alias="X-Admin-Token")] = None) -> None:
        require_admin_token(settings, supplied)

    router = APIRouter(prefix="/api/v1/outbound", dependencies=[Depends(admin)])

    @router.get("/leads")
    def leads() -> list[dict[str, object]]:
        if not settings.platform_extensions_enabled:
            raise ApiError(status_code=404, code="FEATURE_UNAVAILABLE", message="This extension is disabled")
        from datetime import UTC, datetime
        from sqlalchemy import select
        from dwellcall.database.models import OutboundCall
        from dwellcall.database.models.call_intelligence import CallIntelligence
        with service.sessions() as session:
            rows = list(session.scalars(select(OutboundCall).join(CallIntelligence, CallIntelligence.call_id == OutboundCall.id).where(CallIntelligence.status == "complete", CallIntelligence.expires_at > datetime.now(UTC)).order_by(OutboundCall.created_at.desc()).limit(100)))
            calls = [service._response(row) for row in rows]
        result = []
        for call in calls:
            detail = service.intelligence.detail(call.id)
            if detail.get("assessment") is not None:
                result.append({"call": call.model_dump(mode="json"), "assessment": detail["assessment"]})
        return result

    @router.get("/calls/{call_id}/intelligence")
    def intelligence(call_id: UUID) -> dict[str, object]:
        service.get(call_id)
        return service.intelligence.detail(call_id)

    @router.post("/calls/{call_id}/analyze")
    def analyze(call_id: UUID) -> dict[str, object]:
        service.get(call_id)
        service.intelligence.process(call_id, retry=True)
        return service.intelligence.detail(call_id)

    @router.post("/transcripts/purge")
    def purge() -> dict[str, int]:
        return {"purged": service.intelligence.purge()}

    @router.get("/availability")
    def availability() -> dict[str, object]:
        controls = service.controls()
        return {
            "available": (settings.outbound_enabled or settings.outbound_mock_enabled) and not controls["calls_paused"],
            "mock": settings.outbound_mock_enabled,
            "provider": settings.outbound_provider,
            "intelligence_enabled": settings.outbound_intelligence_enabled,
            "transfer_available": False,
            "max_duration_seconds": settings.outbound_max_duration_seconds,
            "daily_limit": settings.outbound_daily_limit,
            "countries": sorted(settings.outbound_allowed_countries),
            **controls,
        }

    @router.post("/preflight")
    def preflight() -> dict[str, bool]:
        if settings.outbound_mock_enabled:
            return {"ready": True, "mock": True}
        if not settings.outbound_enabled:
            raise ApiError(status_code=503, code="OUTBOUND_DISABLED", message="Configure and deliberately enable outbound calling before provider preflight")
        try:
            service.provider.preflight()
        except OutboundProviderError as error:
            raise ApiError(status_code=503, code=error.code, message=str(error)) from None
        return {"ready": True, "mock": False}

    @router.post("/calls", response_model=CallResponse)
    def create(data: CallInput, key: Annotated[str | None, Header(alias="Idempotency-Key")] = None) -> CallResponse:
        if key is not None and key != str(data.request_id):
            raise ApiError(status_code=409, code="OUTBOUND_KEY_MISMATCH", message="Use the request ID as the Idempotency-Key header")
        return service.create(data)

    @router.get("/calls", response_model=list[CallResponse])
    def history() -> list[CallResponse]:
        return service.history()

    @router.get("/calls/{call_id}", response_model=CallResponse)
    def status(call_id: UUID) -> CallResponse:
        return service.get(call_id)

    @router.get("/requests/{request_id}", response_model=CallResponse)
    def request_status(request_id: UUID) -> CallResponse:
        return service.get_request(request_id)

    @router.post("/calls/{call_id}/refresh", response_model=CallResponse)
    def refresh(call_id: UUID) -> CallResponse:
        return service.refresh(call_id)

    @router.post("/calls/{call_id}/bind", response_model=CallResponse)
    def bind(call_id: UUID, data: BindInput) -> CallResponse:
        return service.refresh(call_id, data.provider_call_id)

    @router.post("/calls/{call_id}/stop", response_model=CallResponse)
    def stop(call_id: UUID) -> CallResponse:
        return service.stop(call_id)

    @router.post("/calls/{call_id}/carrier-ended", response_model=CallResponse)
    def carrier_ended(call_id: UUID, data: CarrierEndedInput) -> CallResponse:
        return service.carrier_ended(call_id)

    @router.post("/suppress")
    def suppress(data: SuppressInput) -> dict[str, bool]:
        service.suppress(data.phone_number)
        return {"suppressed": True}

    @router.post("/controls")
    def controls(data: ControlsInput) -> dict[str, bool]:
        return service.controls(data)

    return router
