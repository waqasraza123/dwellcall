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

    @router.get("/availability")
    def availability() -> dict[str, object]:
        controls = service.controls()
        return {
            "available": (settings.outbound_enabled or settings.outbound_mock_enabled) and not controls["calls_paused"],
            "mock": settings.outbound_mock_enabled,
            "transfer_available": settings.outbound_transfer_enabled and not controls["calls_paused"] and not controls["transfers_paused"],
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
