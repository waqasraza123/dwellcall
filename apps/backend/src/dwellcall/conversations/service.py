from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
from contextlib import aclosing
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from dwellcall.consultant.catalog import PropertyRequirements, load_catalog
from dwellcall.consultant.state import AI_ONLY_HANDOFF_REPLY, ConsultationSession, closing_requested, human_handoff_requested
from dwellcall.conversations.provider import BrowserProvider
from dwellcall.conversations.schemas import ConversationStarted, ConversationStatus, StartConversation, TextReply, TextState, TextTurn
from dwellcall.database.models import AudioAdmissionGuard, AudioSession, BrowserConversation
from dwellcall.errors import ApiError
from dwellcall.settings import ApiSettings
from dwellcall.telephony.retell.schemas import RetellCall
from dwellcall.telephony.retell.service import AudioSessionService

if TYPE_CHECKING:
    from dwellcall.consultant.graph import PropertyConsultant


def blocked(message: str, code: str = "BROWSER_CONVERSATION_BLOCKED") -> ApiError:
    return ApiError(status_code=409, code=code, message=message)


class BrowserConversationService:
    def __init__(self, sessions: sessionmaker[Session], settings: ApiSettings, consultant: PropertyConsultant | None, provider: BrowserProvider | None) -> None:
        self.sessions, self.settings, self.consultant, self.provider = sessions, settings, consultant, provider

    def _hash(self, purpose: str, value: str) -> str:
        key = self.settings.admin_token
        if key is None:
            raise blocked("Operator access is not configured")
        return hmac.new(key.get_secret_value().encode(), ("dwellcall-browser/v1/" + purpose + ":" + value).encode(), hashlib.sha256).hexdigest()

    def _row(self, session: Session, local_id: UUID, owner: str | None = None) -> BrowserConversation:
        row = session.get(BrowserConversation, local_id, with_for_update=True)
        if row is None or (owner is not None and not hmac.compare_digest(row.owner_hash, self._hash("owner", owner))):
            raise ApiError(status_code=404, code="BROWSER_CONVERSATION_NOT_FOUND", message="This browser conversation could not be found")
        return row

    def _audio(self, session: Session, row: BrowserConversation) -> AudioSession:
        audio = session.get(AudioSession, row.audio_session_id, with_for_update=True)
        if audio is None:
            raise blocked("The conversation reservation is missing")
        return audio

    def _status(self, session: Session, row: BrowserConversation) -> ConversationStatus:
        audio = self._audio(session, row)
        expires = audio.created_at + timedelta(seconds=self.settings.conversation_max_duration_seconds)
        if audio.status != "ended" and datetime.now(UTC) >= expires and (row.mock or (row.mode == "text" and datetime.now(UTC) >= expires + timedelta(seconds=30))):
            audio.status, audio.finalized_at = "ended", datetime.now(UTC)
        return ConversationStatus.model_validate(dict(id=row.id, mode=row.mode, scenario=row.scenario, status=audio.status, mock=row.mock, expires_at=expires, provider_call_id=row.provider_call_id, turn_count=row.turn_count, turn_in_flight=row.turn_in_flight))

    def get(self, local_id: UUID, owner: str) -> ConversationStatus:
        with self.sessions() as session, session.begin():
            AudioSessionService._lock(session)
            return self._status(session, self._row(session, local_id, owner))

    def _token(self, state: TextState) -> str:
        body = base64.urlsafe_b64encode(state.model_dump_json().encode()).decode().rstrip("=")
        return body + "." + self._hash("text-state", body)

    def _state(self, token: str, local_id: UUID) -> TextState:
        try:
            body, signature = token.split(".")
            if not hmac.compare_digest(signature, self._hash("text-state", body)):
                raise ValueError
            state = TextState.model_validate_json(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
            if state.conversation_id != local_id:
                raise ValueError
            return state
        except (ValueError, TypeError):
            raise blocked("The conversation state is invalid; end this session before starting again") from None

    def _reserve(self, owner: str, data: StartConversation) -> bool:
        enabled = self.settings.browser_mock_enabled or (self.settings.browser_text_enabled if data.mode == "text" else self.settings.browser_voice_enabled)
        if not enabled:
            raise ApiError(status_code=503, code="BROWSER_CONVERSATION_DISABLED", message="This conversation mode has not been enabled by the owner")
        with self.sessions() as session, session.begin():
            AudioSessionService._lock(session)
            guard = session.get(AudioAdmissionGuard, 1)
            if guard is None or guard.outbound_paused:
                raise blocked("Conversations are paused", "BROWSER_CONVERSATIONS_PAUSED")
            existing = session.get(BrowserConversation, data.request_id)
            if existing is not None:
                row = self._row(session, data.request_id, owner)
                if row.mode != data.mode or row.scenario != data.scenario:
                    raise blocked("This request belongs to another conversation")
                return False
            audio_id = "browser_" + str(data.request_id)
            AudioSessionService.reserve_in_session(session, audio_id, self.settings.retell_agent_id or "browser_text", datetime.now(UTC), cost=self.settings.conversation_reserved_cost_cents, daily_limit=self.settings.conversation_daily_session_limit, budget=self.settings.conversation_daily_budget_cents)
            session.add(BrowserConversation(id=data.request_id, owner_hash=self._hash("owner", owner), audio_session_id=audio_id, mode=data.mode, scenario=data.scenario, agent_id=self.settings.retell_agent_id or "browser_text", agent_version=self.settings.retell_agent_version or 0, mock=self.settings.browser_mock_enabled, turn_count=0, turn_in_flight=False, socket_admitted=False))
            return True

    async def start(self, owner: str, data: StartConversation) -> ConversationStarted:
        fresh = await run_in_threadpool(self._reserve, owner, data)
        status = await run_in_threadpool(self.get, data.request_id, owner)
        greeting = self.consultant.greeting(data.scenario) if self.consultant else "Hi, I'm DwellCall's AI property consultant. Let's explore fictional US homes. What budget and number of bedrooms do you have in mind?"
        if not fresh:
            raise blocked("This request was already reserved. Recover its status and end it before starting a fresh conversation")
        if data.mode == "text" or status.mock:
            state = TextState(conversation_id=data.request_id, turn=0, requirements=PropertyRequirements(scenario=data.scenario))
            return ConversationStarted(conversation=status, greeting=greeting, state_token=self._token(state) if data.mode == "text" else None)
        try:
            if self.provider is None:
                raise ValueError("Browser voice is unavailable")
            await self.provider.preflight()
        except Exception:
            await run_in_threadpool(self._creation_failed, data.request_id, uncertain=False)
            raise ApiError(status_code=503, code="BROWSER_AGENT_INVALID", message="The pinned web agent could not pass configuration preflight") from None
        try:
            await run_in_threadpool(self._begin_send, data.request_id, owner)
            grant = await self.provider.create({"dwellcall_browser_id": str(data.request_id), "authorization": self._hash("voice", str(data.request_id))})
            call = await self.provider.gateway.retrieve(grant.call_id)
            await run_in_threadpool(self.apply, call)
            if not await run_in_threadpool(self._can_connect, data.request_id, owner):
                await self.provider.stop(grant.call_id)
                raise blocked("The conversation was cancelled; reconcile its final status")
            return ConversationStarted(conversation=await run_in_threadpool(self.get, data.request_id, owner), greeting=greeting, grant=grant.model_dump(exclude_none=True))
        except Exception as error:
            if isinstance(error, ApiError) and error.code == "BROWSER_PROVIDER_REJECTED":
                await run_in_threadpool(self._creation_failed, data.request_id, uncertain=False)
                raise
            await run_in_threadpool(self._creation_failed, data.request_id, uncertain=True)
            raise ApiError(status_code=503, code="BROWSER_START_UNCONFIRMED", message="The voice connection is unconfirmed. Recover this request without starting another") from None

    def _begin_send(self, local_id: UUID, owner: str) -> None:
        with self.sessions() as session, session.begin():
            AudioSessionService._lock(session)
            row = self._row(session, local_id, owner)
            guard = session.get(AudioAdmissionGuard, 1)
            if row.stopped_at or not guard or guard.outbound_paused or self._status(session, row).status != "active":
                raise blocked("This conversation was cancelled")
            row.send_started_at = datetime.now(UTC)

    def _can_connect(self, local_id: UUID, owner: str) -> bool:
        with self.sessions() as session, session.begin():
            AudioSessionService._lock(session)
            row = self._row(session, local_id, owner)
            guard = session.get(AudioAdmissionGuard, 1)
            return bool(guard and not guard.outbound_paused and row.stopped_at is None and self._status(session, row).status == "active")

    def _creation_failed(self, local_id: UUID, *, uncertain: bool) -> None:
        with self.sessions() as session, session.begin():
            AudioSessionService._lock(session)
            row = self._row(session, local_id)
            audio = self._audio(session, row)
            if audio.status != "ended":
                audio.status = "unknown" if uncertain else "ended"
                audio.finalized_at = None if uncertain else datetime.now(UTC)

    def _claim_turn(self, owner: str, local_id: UUID, state: TextState) -> tuple[bool, float]:
        with self.sessions() as session, session.begin():
            AudioSessionService._lock(session)
            row = self._row(session, local_id, owner)
            status = self._status(session, row)
            guard = session.get(AudioAdmissionGuard, 1)
            if row.mode != "text" or row.stopped_at or status.status != "active" or not guard or guard.outbound_paused or row.turn_in_flight or row.turn_count != state.turn or row.turn_count >= self.settings.conversation_max_responses:
                raise blocked("This turn cannot be sent again. Check status and end an interrupted conversation")
            remaining = (status.expires_at - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                raise blocked("The conversation time has elapsed")
            row.turn_count += 1
            row.turn_in_flight = True
            return row.mock, remaining

    def _complete_turn(self, owner: str, local_id: UUID, end_call: bool) -> ConversationStatus:
        with self.sessions() as session, session.begin():
            AudioSessionService._lock(session)
            row = self._row(session, local_id, owner)
            row.turn_in_flight = False
            guard = session.get(AudioAdmissionGuard, 1)
            if guard is None or guard.outbound_paused or row.stopped_at:
                raise blocked("The conversation was stopped or paused")
            if end_call or row.turn_count >= self.settings.conversation_max_responses:
                audio = self._audio(session, row)
                audio.status, audio.finalized_at = "ended", datetime.now(UTC)
            return self._status(session, row)

    def _failed_turn(self, owner: str, local_id: UUID) -> None:
        with self.sessions() as session, session.begin():
            AudioSessionService._lock(session)
            row = self._row(session, local_id, owner)
            row.turn_in_flight = False
            audio = self._audio(session, row)
            audio.status = "ended" if row.stopped_at else "unknown"
            audio.finalized_at = datetime.now(UTC) if row.stopped_at else None

    async def reply(self, owner: str, local_id: UUID, data: TextTurn) -> TextReply:
        state = self._state(data.state_token, local_id)
        mock, remaining = await run_in_threadpool(self._claim_turn, owner, local_id, state)
        conversation = ConsultationSession(requirements=state.requirements, version=state.version, confirmed_version=state.confirmed_version, pending_readback=state.pending_readback, confirmed_summary=state.confirmed_summary)
        try:
            if mock:
                catalog = load_catalog(self.settings)
                names = ", ".join(item.name for item in catalog.properties if state.requirements.scenario in item.scenarios)
                reply = "Simulation: these fictional examples include " + names + ". Tell me your budget and bedroom preference to explore the conversation flow."
                conversation.end_call = closing_requested(data.transcript)
                if conversation.end_call:
                    reply = "Thanks for exploring the fictional homes. Goodbye."
                elif human_handoff_requested(data.transcript):
                    reply = AI_ONLY_HANDOFF_REPLY
            else:
                if self.consultant is None or not self.settings.browser_text_enabled:
                    raise ValueError("The property consultant is unavailable")
                async with asyncio.timeout(min(25, remaining)), aclosing(self.consultant.stream(data.transcript, conversation)) as stream:
                    parts = [part async for part in stream]
                reply = "".join(parts)
            if not reply.strip() or len(reply) > 2000:
                raise ValueError("Invalid consultant response")
            status = await run_in_threadpool(self._complete_turn, owner, local_id, conversation.end_call)
            next_state = TextState(conversation_id=local_id, turn=state.turn + 1, requirements=conversation.requirements, version=conversation.version, confirmed_version=conversation.confirmed_version, pending_readback=conversation.pending_readback, confirmed_summary=conversation.confirmed_summary)
            return TextReply(reply=reply, state_token=self._token(next_state), conversation=status)
        except Exception:
            await run_in_threadpool(self._failed_turn, owner, local_id)
            raise ApiError(status_code=503, code="BROWSER_TURN_UNCONFIRMED", message="The reply could not be completed. Your draft is kept; end this conversation before starting another") from None

    def _identity(self, row: BrowserConversation, call: RetellCall) -> None:
        metadata = call.metadata or {}
        if row.mock or row.mode != "voice" or row.send_started_at is None or call.call_type != "web_call" or call.agent_id != row.agent_id or call.agent_version != row.agent_version or metadata.get("dwellcall_browser_id") != str(row.id) or metadata.get("authorization") != self._hash("voice", str(row.id)) or (row.provider_call_id is not None and row.provider_call_id != call.call_id):
            raise blocked("The web call does not match this browser reservation", "BROWSER_CALL_IDENTITY_INVALID")

    def apply(self, call: RetellCall, *, admit: bool = False) -> tuple[str, str]:
        try:
            local_id = UUID(str((call.metadata or {}).get("dwellcall_browser_id", "")))
        except ValueError:
            raise blocked("The browser reservation is invalid") from None
        with self.sessions() as session, session.begin():
            AudioSessionService._lock(session)
            row = self._row(session, local_id)
            self._identity(row, call)
            audio = self._audio(session, row)
            row.provider_call_id = call.call_id
            if call.call_status in {"ended", "error", "not_connected"}:
                audio.status, audio.finalized_at = "ended", datetime.now(UTC)
            if admit:
                guard = session.get(AudioAdmissionGuard, 1)
                if not self.settings.browser_voice_enabled or not guard or guard.outbound_paused or row.stopped_at or row.socket_admitted or audio.status != "active" or datetime.now(UTC) >= audio.created_at + timedelta(seconds=self.settings.conversation_max_duration_seconds):
                    raise blocked("The browser audio session cannot be admitted")
                row.socket_admitted = True
            return row.audio_session_id, row.scenario

    def active(self, audio_id: str) -> bool:
        with self.sessions() as session:
            row = session.scalar(select(BrowserConversation).where(BrowserConversation.audio_session_id == audio_id))
            audio = session.get(AudioSession, audio_id)
            guard = session.get(AudioAdmissionGuard, 1)
            return bool(self.settings.browser_voice_enabled and row and not row.stopped_at and audio and audio.status == "active" and guard and not guard.outbound_paused)

    def validate_details(self, audio_id: str, call: RetellCall) -> None:
        with self.sessions() as session:
            row = session.scalar(select(BrowserConversation).where(BrowserConversation.audio_session_id == audio_id))
            if row is None:
                raise blocked("The browser reservation is unavailable")
            self._identity(row, call)

    async def refresh(self, owner: str, local_id: UUID) -> ConversationStatus:
        status = await run_in_threadpool(self.get, local_id, owner)
        if status.mode == "voice" and not status.mock and status.status != "ended":
            if self.provider is None:
                raise blocked("Provider recovery is unavailable; retain this request")
            try:
                call = await self.provider.gateway.retrieve(status.provider_call_id) if status.provider_call_id else await self.provider.find(str(local_id))
                if call is not None:
                    await run_in_threadpool(self.apply, call)
            except Exception:
                raise ApiError(status_code=503, code="BROWSER_RECOVERY_UNAVAILABLE", message="The provider outcome is unavailable; retain the saved request") from None
        return await run_in_threadpool(self.get, local_id, owner)

    def _request_end(self, owner: str, local_id: UUID) -> ConversationStatus:
        with self.sessions() as session, session.begin():
            AudioSessionService._lock(session)
            row = self._row(session, local_id, owner)
            audio = self._audio(session, row)
            row.stopped_at = row.stopped_at or datetime.now(UTC)
            if audio.status == "ended":
                return self._status(session, row)
            if row.mock or (row.mode == "text" and not row.turn_in_flight) or (row.mode == "voice" and row.send_started_at is None):
                audio.status, audio.finalized_at = "ended", datetime.now(UTC)
                return self._status(session, row)
            audio.status = "unknown"
            return self._status(session, row)

    async def end(self, owner: str, local_id: UUID) -> ConversationStatus:
        status = await run_in_threadpool(self._request_end, owner, local_id)
        if status.status == "ended":
            return status
        status = await self.refresh(owner, local_id)
        if status.mode == "voice" and status.provider_call_id and status.status != "ended" and self.provider:
            try:
                await self.provider.stop(status.provider_call_id)
                status = await self.refresh(owner, local_id)
            except Exception:
                raise ApiError(status_code=503, code="BROWSER_STOP_UNCONFIRMED", message="Audio has stopped locally; provider completion remains unconfirmed. Reconcile this request") from None
        return status
