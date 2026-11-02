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
from dwellcall.consultant.state import ConsultationSession
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
    consultant: PropertyConsultant,
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
        except (ValueError, UnicodeError, TypeError):
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
        gateway.validate_identity(event.call, event.call.call_id)
        if event.event in {"call_ended", "call_analyzed"}:
            if event.call.call_status not in {"ended", "error", "not_connected"}:
                raise ApiError(
                    status_code=422,
                    code="EVENT_STATE_INVALID",
                    message="A final call state is required",
                )
            await run_in_threadpool(
                service.finalize, event.call.call_id, event.call.agent_id
            )
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
        response_task: asyncio.Task[None] | None = None
        send_lock = asyncio.Lock()
        last_response_id = -1
        user_transcript: tuple[str, ...] = ()
        response_count = 0
        conversation = ConsultationSession()

        async def send(response: Response) -> None:
            async with send_lock:
                await websocket.send_json(response.model_dump())

        async def respond(event: ResponseRequired) -> None:
            try:
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
            call = await gateway.authorize(call_id)
            remaining = float(settings.conversation_max_duration_seconds)
            if call.start_timestamp is not None:
                elapsed = datetime.now(UTC).timestamp() - call.start_timestamp / 1000
                remaining -= max(0, elapsed)
            if remaining <= 0:
                raise ApiError(
                    status_code=409,
                    code="CALL_EXPIRED",
                    message="The conversation duration has elapsed",
                )
            await run_in_threadpool(service.reserve, call_id, call.agent_id)
            reserved = True
            await websocket.accept()
            await websocket.send_json(ConfigResponse().model_dump())
            await send(Response(
                response_id=0,
                content=consultant.greeting(),
                content_complete=True,
            ))
            try:
                async with asyncio.timeout(remaining):
                    while True:
                        raw = await websocket.receive_text()
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
                                    service.is_active, call_id
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
                await run_in_threadpool(service.disconnect, call_id)

    return router
