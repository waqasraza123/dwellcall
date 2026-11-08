from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from starlette.concurrency import run_in_threadpool

from dwellcall.admin_security import require_admin_token
from dwellcall.database.models import OutboundCall
from dwellcall.errors import ApiError
from dwellcall.settings import ApiSettings
from dwellcall.telephony.outbound.elevenlabs import ElevenLabsOutboundProvider, MAX_WEBHOOK_BYTES
from dwellcall.telephony.outbound.provider import OutboundProviderError
from dwellcall.telephony.outbound.schemas import CallInput, CallResponse
from dwellcall.telephony.outbound.service import OutboundCallService, unavailable
from dwellcall.telephony.outbound.verification import PhoneVerificationService
from dwellcall.telephony.outbound.verification_schemas import SmsStartInput, SmsVerifyInput, SmsChallengeResponse


def create_demo_router(settings: ApiSettings, service: OutboundCallService) -> APIRouter:
    router = APIRouter(prefix="/api/v1/outbound-demo")
    verification = PhoneVerificationService(service.sessions, settings, service._lock, service._hash)

    def visitor(token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
                identity: Annotated[str | None, Header(alias="X-Browser-Session")] = None) -> str:
        require_admin_token(settings, token)
        try:
            return str(UUID(identity or ""))
        except ValueError:
            raise ApiError(status_code=401, code="CALLBACK_SIGN_IN_REQUIRED", message="Sign in to request a call") from None

    Visitor = Annotated[str, Depends(visitor)]

    @router.get("/availability")
    def availability(owner: Visitor) -> dict[str, object]:
        return {"available": settings.website_available and not service.controls()["calls_paused"], "provider": settings.outbound_provider}

    @router.post("/phone-verifications", response_model=SmsChallengeResponse)
    def start(data: SmsStartInput, owner: Visitor) -> SmsChallengeResponse:
        return verification.start(data, owner)

    @router.post("/phone-verifications/verify", response_model=SmsChallengeResponse)
    def verify(data: SmsVerifyInput, owner: Visitor) -> SmsChallengeResponse:
        return verification.verify(data, owner)

    @router.post("/calls", response_model=CallResponse)
    def create(data: CallInput, owner: Visitor) -> CallResponse:
        if not settings.website_available or data.call_purpose != "demonstration":
            raise unavailable("Website demonstrations are disabled")
        return service.create(data, owner)

    @router.get("/requests/{request_id}", response_model=CallResponse)
    def status(request_id: UUID, owner: Visitor) -> CallResponse:
        with service.sessions() as session:
            from sqlalchemy import select
            row = session.scalar(select(OutboundCall).where(OutboundCall.request_id == request_id, OutboundCall.owner_hash == service._hash("owner", owner)))
            if row is None:
                raise ApiError(status_code=404, code="DEMO_CALL_NOT_FOUND", message="The saved request is not visible; do not redial")
            call_id = row.id
        return service.get(call_id)

    @router.post("/webhook")
    async def webhook(request: Request) -> dict[str, bool]:
        provider = ElevenLabsOutboundProvider(settings)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_WEBHOOK_BYTES:
                raise ApiError(status_code=413, code="OUTBOUND_EVENT_TOO_LARGE", message="Event exceeds the size limit")
        try:
            payload = provider.verify_webhook(request.headers, bytes(body))
            kind = payload.get("type")
            if kind not in {"post_call_transcription", "call_initiation_failure"}:
                raise ApiError(status_code=422, code="OUTBOUND_EVENT_INVALID", message="Unsupported event")
            data = payload["data"]
            snapshot = provider.snapshot(data, str(kind))
        except OutboundProviderError as error:
            raise ApiError(status_code=401, code=error.code, message=str(error)) from None
        call_id = await run_in_threadpool(service.apply, snapshot, str(kind), service.event_digest(bytes(body)), source_provider="elevenlabs")
        if kind == "post_call_transcription":
            await run_in_threadpool(service.intelligence.capture, call_id, data.get("transcript"))
            await run_in_threadpool(service.intelligence.process, call_id)
        return {"accepted": True}

    return router
