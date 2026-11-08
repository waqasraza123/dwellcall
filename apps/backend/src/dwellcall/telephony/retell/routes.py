import asyncio
import logging
import secrets
from contextlib import aclosing, suppress
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from retell import RetellError
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from dwellcall.admin_security import require_admin_token
from dwellcall.consultant.graph import PropertyConsultant
from dwellcall.consultant.catalog import PropertyRequirements
from dwellcall.consultant.state import ConsultationSession
from dwellcall.consultant.spoken import normalized_speech
from dwellcall.conversations.service import BrowserConversationService
from dwellcall.errors import ApiError
from dwellcall.settings import ApiSettings
from dwellcall.telephony.retell.provider import RetellGateway
from dwellcall.telephony.retell.schemas import (
    REQUEST,
    CallDetails,
    CallId,
    ConfigResponse,
    PingPong,
    PingPongResponse,
    Response,
    ResponseRequired,
    RetellWebhook,
    UpdateOnly,
)
from dwellcall.telephony.retell.service import AudioSessionService
from dwellcall.telephony.outbound.service import OutboundCallService
from dwellcall.telephony.webhook_validation import log_webhook_validation_failure

logger = logging.getLogger(__name__)
MAX_MESSAGE_BYTES = 65_536
MAX_WEBHOOK_BYTES = 1_048_576


async def cancel_response(task: asyncio.Task[None] | None) -> None:
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def create_retell_router(
    settings: ApiSettings,
    sessions: sessionmaker[Session],
    gateway: RetellGateway,
    consultant: PropertyConsultant | None,
    outbound: OutboundCallService | None = None,
    browser: BrowserConversationService | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/retell")
    service = AudioSessionService(sessions, settings)

    def admin(
        supplied: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
    ) -> None:
        require_admin_token(settings, supplied)

    @router.post("/admin/calls/{call_id}/refresh")
    async def refresh(
        call_id: CallId,
        authenticated: Annotated[None, Depends(admin)],
    ) -> dict[str, str]:
        try:
            call = await gateway.retrieve(call_id)
        except RetellError as error:
            raise ApiError(
                status_code=503,
                code="RETELL_UNAVAILABLE",
                message="Retell status is unavailable; the reservation is retained",
            ) from error
        if call.call_status in {"ended", "error", "not_connected"}:
            if call.call_type == "phone_call" and outbound is not None:
                await run_in_threadpool(outbound.apply, call, "operator_refresh")
            elif browser is not None and (call.metadata or {}).get("dwellcall_browser_id"):
                await run_in_threadpool(browser.apply, call)
            else:
                await run_in_threadpool(service.finalize, call.call_id, call.agent_id)
        return {"call_status": call.call_status}

    @router.post("/webhook")
    async def webhook(request: Request) -> dict[str, bool]:
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_WEBHOOK_BYTES:
                raise ApiError(
                    status_code=413,
                    code="EVENT_TOO_LARGE",
                    message="Event exceeds the size limit",
                )
        signature = request.headers.get("X-Retell-Signature", "")
        try:
            valid = bool(signature) and gateway.verify(bytes(body), signature)
        except (ValueError, UnicodeError, TypeError, OverflowError):
            valid = False
        if not valid:
            raise ApiError(
                status_code=401,
                code="WEBHOOK_AUTH_REQUIRED",
                message="A valid Retell signature is required",
            )
        try:
            event = RetellWebhook.model_validate_json(bytes(body))
        except ValidationError as error:
            log_webhook_validation_failure(error=error)
            raise ApiError(
                status_code=422, code="EVENT_INVALID", message="The event is invalid"
            ) from error
        if event.event in {"call_ended", "call_analyzed"}:
            if event.call.call_status not in {"ended", "error", "not_connected"}:
                raise ApiError(
                    status_code=422,
                    code="EVENT_STATE_INVALID",
                    message="A final call state is required",
                )
        if event.call.call_type == "phone_call":
            if outbound is None:
                raise ApiError(status_code=403, code="OUTBOUND_CALL_IDENTITY_INVALID", message="No outbound reservation service is available")
            call_id = await run_in_threadpool(outbound.apply, event.call, event.event, outbound.event_digest(bytes(body)))
            if event.event in {"call_ended", "call_analyzed"}:
                await run_in_threadpool(outbound.intelligence.capture, call_id, event.call.transcript_object)
                await run_in_threadpool(outbound.intelligence.process, call_id)
        else:
            gateway.validate_identity(event.call, event.call.call_id)
            if browser is not None and (event.call.metadata or {}).get("dwellcall_browser_id"):
                await run_in_threadpool(browser.apply, event.call)
            elif event.event in {"call_ended", "call_analyzed"}:
                await run_in_threadpool(service.finalize, event.call.call_id, event.call.agent_id)
        return {"received": True}

    @router.websocket("/llm/{secret}/{call_id}")
    async def llm(websocket: WebSocket, secret: str, call_id: CallId) -> None:
        expected = settings.retell_websocket_secret
        if expected is None or not secrets.compare_digest(
            secret.encode(), expected.get_secret_value().encode()
        ):
            await websocket.close(code=1008)
            return
        reserved = False
        phone = False
        browser_call = False
        call_purpose, intelligence_consent = "demonstration", False
        audio_id = call_id
        response_task: asyncio.Task[None] | None = None
        send_lock = asyncio.Lock()
        last_response_id = -1
        user_transcript: tuple[str, ...] = ()
        response_count = 0
        conversation = ConsultationSession()

        async def send(response: Response) -> None:
            async with send_lock:
                await websocket.send_json(response.model_dump(exclude_none=True))

        async def respond(event: ResponseRequired) -> None:
            try:
                if consultant is None:
                    raise ValueError("The consultant is unavailable")
                speech = normalized_speech(event.transcript[-1].content) if event.transcript and event.transcript[-1].role == "user" else ""
                if phone and outbound is not None and any(phrase in speech for phrase in ("do not call", "don t call", "dont call", "stop calling", "remove my number")):
                    await run_in_threadpool(outbound.suppress_call, audio_id)
                    await send(Response(response_id=event.response_id, content="I have marked this number do not call. Goodbye.", content_complete=True, end_call=True))
                    return
                if phone and call_purpose == "qualification":
                    async with asyncio.timeout(25):
                        reply = await consultant.qualify(event.transcript, intelligence_consent)
                    if event.response_id == last_response_id:
                        await send(Response(response_id=event.response_id, content=reply.content, content_complete=True, end_call=reply.end_call))
                    return
                async with asyncio.timeout(25), aclosing(
                    consultant.stream(event.transcript, conversation)
                ) as stream:
                    async for content in stream:
                        if event.response_id != last_response_id:
                            return
                        await send(Response(
                            response_id=event.response_id, content=content,
                            content_complete=False,
                        ))
                    if event.response_id != last_response_id:
                        return
                    await send(Response(
                        response_id=event.response_id, content="", content_complete=True,
                        end_call=conversation.end_call,
                    ))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Private audio response failed")
                with suppress(WebSocketDisconnect, RuntimeError, OSError):
                    await send(Response(
                        response_id=event.response_id,
                        content="I can't continue this demonstration. Thank you.",
                        content_complete=True, end_call=True,
                    ))
                    await websocket.close(code=1011)

        try:
            if consultant is None:
                raise ApiError(status_code=503, code="CONSULTANT_DISABLED", message="The consultant is disabled")
            call = await gateway.authorize(call_id)
            phone = call.call_type == "phone_call"
            browser_call = not phone and bool((call.metadata or {}).get("dwellcall_browser_id"))
            if phone:
                if outbound is None:
                    raise ApiError(status_code=403, code="PHONE_CALL_DISABLED", message="Phone calls are disabled")
                audio_id, scenario = await run_in_threadpool(outbound.admit_phone, call)
                call_purpose, intelligence_consent = await run_in_threadpool(outbound.call_context, audio_id)
                reserved = True
                conversation.requirements = PropertyRequirements.model_validate({"scenario": scenario})
                remaining = await run_in_threadpool(outbound.remaining_seconds, audio_id)
            else:
                if not settings.retell_test_audio_enabled:
                    raise ApiError(status_code=403, code="WEB_CALL_DISABLED", message="Web calls are disabled")
                if browser_call:
                    if browser is None:
                        raise ApiError(status_code=403, code="BROWSER_CALL_DISABLED", message="Browser calls are disabled")
                    audio_id, scenario = await run_in_threadpool(browser.apply, call, admit=True)
                    reserved = True
                    conversation.requirements = PropertyRequirements.model_validate({"scenario": scenario})
                else:
                    scenario = None
                remaining = float(settings.conversation_max_duration_seconds)
            if call.start_timestamp is not None:
                elapsed = datetime.now(UTC).timestamp() - call.start_timestamp / 1000
                remaining = min(remaining, (settings.outbound_max_duration_seconds if phone else settings.conversation_max_duration_seconds) - max(0, elapsed))
            if remaining <= 0:
                raise ApiError(
                    status_code=409,
                    code="CALL_EXPIRED",
                    message="The conversation duration has elapsed",
                )
            if not phone and not browser_call:
                await run_in_threadpool(service.reserve, call_id, call.agent_id)
                reserved = True
            await websocket.accept()
            await websocket.send_json(ConfigResponse().model_dump())
            await send(Response(
                response_id=0,
                content=("Hi, I am DwellCall’s AI assistant, calling for the platform conversation you requested. " + ("The transcript is saved and analyzed with OpenAI to assess follow-up interest. " if intelligence_consent else "") + "Is now a good time?") if phone and call_purpose == "qualification" else consultant.greeting(scenario) if phone or browser_call else consultant.greeting(),
                content_complete=True,
            ))
            try:
                async with asyncio.timeout(remaining):
                    while True:
                        active_service = outbound.active if phone and outbound else browser.active if browser_call and browser else None
                        if active_service is not None and not await run_in_threadpool(active_service, audio_id):
                            await cancel_response(response_task)
                            response_task = None
                            await send(Response(response_id=max(last_response_id, 0), content="This demonstration has ended. Goodbye.", content_complete=True, end_call=True))
                            break
                        try:
                            if phone or browser_call:
                                raw = await asyncio.wait_for(websocket.receive_text(), timeout=1)
                            else:
                                raw = await websocket.receive_text()
                        except TimeoutError:
                            continue
                        if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
                            await websocket.close(code=1009)
                            break
                        event = REQUEST.validate_json(raw)
                        if isinstance(event, PingPong):
                            async with send_lock:
                                await websocket.send_json(
                                    PingPongResponse(
                                        timestamp=event.timestamp
                                    ).model_dump()
                                )
                        elif isinstance(event, CallDetails):
                            gateway.validate_identity(event.call, call_id)
                            if phone and outbound is not None:
                                await run_in_threadpool(outbound.validate_phone_details, audio_id, event.call)
                            elif browser_call and browser is not None:
                                await run_in_threadpool(browser.validate_details, audio_id, event.call)
                        elif isinstance(event, UpdateOnly):
                            users = tuple(
                                turn.content
                                for turn in event.transcript
                                if turn.role == "user"
                            )
                            if users != user_transcript:
                                await cancel_response(response_task)
                                response_task = None
                        elif isinstance(event, ResponseRequired):
                            if event.response_id <= last_response_id:
                                continue
                            last_response_id = event.response_id
                            await cancel_response(response_task)
                            response_task = None
                            response_count += 1
                            if (
                                response_count > settings.conversation_max_responses
                                or not await run_in_threadpool(
                                    outbound.active if phone and outbound is not None else browser.active if browser_call and browser is not None else service.is_active, audio_id
                                )
                            ):
                                await send(Response(
                                    response_id=last_response_id,
                                    content="Thank you. This demonstration has ended.",
                                    content_complete=True, end_call=True,
                                ))
                                break
                            user_transcript = tuple(
                                turn.content
                                for turn in event.transcript
                                if turn.role == "user"
                            )
                            response_task = asyncio.create_task(respond(event))
            except TimeoutError:
                await cancel_response(response_task)
                response_task = None
                await send(Response(
                    response_id=max(last_response_id, 0),
                    content="Our demonstration time is up. Thank you for exploring.",
                    content_complete=True, end_call=True,
                ))
            await websocket.close(code=1000)
        except WebSocketDisconnect:
            pass
        except (ApiError, ValidationError):
            with suppress(RuntimeError, OSError):
                await websocket.close(code=1008)
        except Exception:
            logger.warning("Private audio connection failed")
            with suppress(RuntimeError, OSError):
                await websocket.close(code=1011)
        finally:
            await cancel_response(response_task)
            if reserved:
                if phone and outbound is not None:
                    await run_in_threadpool(outbound.disconnect, audio_id)
                else:
                    await run_in_threadpool(service.disconnect, audio_id)

    return router
