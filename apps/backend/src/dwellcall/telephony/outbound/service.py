import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from dwellcall.database.models import (
    AudioAdmissionGuard, AudioSession, ListingAgent, ListingAgentIdentity,
    ListingContactEvidence, OutboundCall, OutboundCallEvent, OutboundSuppression,
)
from dwellcall.errors import ApiError
from dwellcall.listings.normalization import fingerprint
from dwellcall.settings import ApiSettings
from dwellcall.telephony.outbound.destinations import validate_destination
from dwellcall.telephony.outbound.provider import OutboundProviderError, RetellOutboundProvider
from dwellcall.telephony.outbound.schemas import CallInput, CallResponse, CallStatus, ControlsInput, TransferStatus
from dwellcall.telephony.retell.schemas import RetellCall
from dwellcall.telephony.retell.service import AudioSessionService

MESSAGES = {
    "reserved": "The request is reserved. Do not submit another call.",
    "dialing": "Retell accepted the request. Answering has not been confirmed.",
    "ringing": "The provider reports ringing. Answering has not been confirmed.",
    "in_progress": "The AI conversation is in progress.",
    "completed": "The call ended. No follow-up or appointment was arranged.",
    "rejected": "The recipient was busy or declined. No automatic redial will occur.",
    "unanswered": "The call was not answered. No automatic redial will occur.",
    "failed": "The call could not be completed. No automatic redial will occur.",
    "unknown": "The outcome is unconfirmed. Reconcile this request; do not redial.",
    "transferred": "Transfer signaling was accepted. Human answer and carrier leg completion are not confirmed.",
    "transfer_unconfirmed": "Transfer outcome is unconfirmed. Verify all carrier legs before releasing this call.",
}


def unavailable(message: str = "Outbound calling is disabled") -> ApiError:
    return ApiError(status_code=503, code="OUTBOUND_UNAVAILABLE", message=message)


class OutboundCallService:
    """Adapted from HVACLine's durable outbound service; uses the existing audio lock."""

    def __init__(self, sessions: sessionmaker[Session], settings: ApiSettings, provider: RetellOutboundProvider) -> None:
        self.sessions = sessions
        self.settings = settings
        self.provider = provider

    def _hash(self, purpose: str, value: str) -> str:
        secret = self.settings.outbound_hash_secret
        if secret is None:
            raise unavailable("Configure the stable outbound hashing secret")
        return hmac.new(secret.get_secret_value().encode(), f"dwellcall-outbound/v1/{purpose}:{value}".encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _lock(session: Session) -> AudioAdmissionGuard:
        AudioSessionService._lock(session)
        guard = session.get(AudioAdmissionGuard, 1, populate_existing=True)
        if guard is None:
            raise unavailable("The shared audio admission guard is missing")
        return guard

    @staticmethod
    def _row(session: Session, call_id: UUID) -> OutboundCall:
        row = session.get(OutboundCall, call_id, with_for_update=True)
        if row is None:
            raise ApiError(status_code=404, code="OUTBOUND_CALL_NOT_FOUND", message="This call request could not be found; do not redial an uncertain request")
        return row

    def _event(self, session: Session, row: OutboundCall, kind: str, digest: str | None = None) -> None:
        session.add(OutboundCallEvent(
            id=uuid4(), call_id=row.id, kind=kind, status=row.status,
            fingerprint=digest or uuid4().hex, created_at=datetime.now(UTC),
        ))

    def _suppressed(self, session: Session, number: str) -> bool:
        if number in self.settings.suppressed_numbers or session.get(OutboundSuppression, self._hash("destination", number)) is not None:
            return True
        suppressed_contact = session.scalar(select(ListingContactEvidence.id).join(
            ListingAgent, ListingAgent.id == ListingContactEvidence.agent_id,
        ).where(ListingContactEvidence.value == number, ListingAgent.suppressed_at.is_not(None)).limit(1))
        suppressed_alias = session.scalar(select(ListingAgentIdentity.id).join(
            ListingAgent, ListingAgent.id == ListingAgentIdentity.agent_id,
        ).where(
            ListingAgentIdentity.namespace.in_(("suppressed-contact:direct_business_phone", "suppressed-contact:professional_mobile")),
            ListingAgentIdentity.identifier == fingerprint(number), ListingAgent.suppressed_at.is_not(None),
        ).limit(1))
        return suppressed_contact is not None or suppressed_alias is not None

    def _policy(self, session: Session, guard: AudioAdmissionGuard, number: str) -> None:
        if not (self.settings.outbound_enabled or self.settings.outbound_mock_enabled) or guard.outbound_paused:
            raise unavailable()
        validate_destination(number, self.settings.outbound_allowed_countries)
        if number not in self.settings.allowed_numbers:
            raise ApiError(status_code=403, code="OUTBOUND_RECIPIENT_NOT_APPROVED", message="Only separately approved, consenting recipients may receive demonstration calls")
        if self._suppressed(session, number):
            raise ApiError(status_code=403, code="OUTBOUND_RECIPIENT_SUPPRESSED", message="This recipient is suppressed or restricted from calling")
        if number in {self.settings.outbound_from_number.get_secret_value(), self.settings.outbound_human_number.get_secret_value()}:
            raise ApiError(status_code=403, code="OUTBOUND_CALL_LOOP", message="Caller, recipient and human transfer numbers must differ")

    def _reserve(self, data: CallInput) -> tuple[UUID, CallResponse | None]:
        now = datetime.now(UTC)
        request_hash = self._hash("request", data.model_dump_json())
        destination = self._hash("destination", data.phone_number)
        today = datetime.combine(now.date(), datetime.min.time(), tzinfo=UTC)
        with self.sessions() as session, session.begin():
            guard = self._lock(session)
            existing = session.scalar(select(OutboundCall).where(OutboundCall.request_id == data.request_id))
            if existing is not None:
                if not hmac.compare_digest(existing.request_hash, request_hash):
                    raise ApiError(status_code=409, code="OUTBOUND_REQUEST_CONFLICT", message="This request ID belongs to a different call; inspect its existing status")
                return existing.id, self._response(existing)
            self._policy(session, guard, data.phone_number)
            base = select(OutboundCall).where(OutboundCall.created_at >= today)
            daily = session.scalar(select(func.count()).select_from(base.subquery())) or 0
            number_daily = session.scalar(select(func.count()).select_from(base.where(OutboundCall.destination_hash == destination).subquery())) or 0
            recent = session.scalar(select(OutboundCall.id).where(OutboundCall.created_at >= now - timedelta(seconds=self.settings.outbound_cooldown_seconds)).limit(1))
            if daily >= self.settings.outbound_daily_limit or number_daily >= self.settings.outbound_number_daily_limit or recent is not None:
                raise ApiError(status_code=429, code="OUTBOUND_CALL_LIMIT", message="The daily, recipient or cooldown limit was reached")
            call_id = uuid4()
            audio_id = "outbound_" + str(call_id)
            cost = self.settings.outbound_reserved_cost_cents
            if self.settings.outbound_transfer_enabled:
                cost += self.settings.outbound_transfer_reserved_cost_cents
            AudioSessionService.reserve_in_session(
                session, audio_id, self.settings.outbound_agent_id or "", now,
                cost=cost, daily_limit=self.settings.outbound_daily_limit,
                budget=self.settings.outbound_daily_budget_cents,
            )
            agent_version = self.settings.outbound_agent_version
            if agent_version is None:
                raise unavailable("Pin the dedicated outbound agent version")
            row = OutboundCall(
                id=call_id, request_id=data.request_id, request_hash=request_hash,
                destination_hash=destination, audio_session_id=audio_id,
                agent_id=self.settings.outbound_agent_id or "", agent_version=agent_version,
                caller_hash=self._hash("caller", self.settings.outbound_from_number.get_secret_value()),
                scenario=data.scenario, consent_version=data.consent_version, consent_at=now,
                created_at=now, status="reserved", transfer_status="not_requested",
                socket_admitted=False, carrier_end_confirmed=False, reserved_cost_cents=cost, mock=self.settings.outbound_mock_enabled,
            )
            session.add(row)
            session.flush()
            self._event(session, row, "operator_consent_dnc_review_and_reservation")
            return row.id, None

    def create(self, data: CallInput) -> CallResponse:
        call_id, existing = self._reserve(data)
        if existing is not None:
            return existing
        sent = False
        try:
            if not self.settings.outbound_mock_enabled:
                self.provider.preflight(data.phone_number)
            with self.sessions() as session, session.begin():
                guard = self._lock(session)
                row = self._row(session, call_id)
                self._policy(session, guard, data.phone_number)
                if row.finalized_at is not None or row.send_started_at is not None or row.status != "reserved":
                    return self._response(row)
                row.send_started_at = datetime.now(UTC)
                request_hash = row.request_hash
                self._event(session, row, "provider_send_reserved")
            if self.settings.outbound_mock_enabled:
                return self.get(call_id)
            with self.sessions() as session, session.begin():
                guard = self._lock(session)
                row = self._row(session, call_id)
                if row.finalized_at is not None or row.status != "reserved" or row.provider_call_id is not None:
                    return self._response(row)
                self._policy(session, guard, data.phone_number)
                sent = True
                receipt = self.provider.dial(data, str(call_id), request_hash)
            self.apply(receipt, "receipt")
        except OutboundProviderError as error:
            return self._failure(call_id, error.code, error.outcome_unknown)
        except ApiError as error:
            return self._failure(call_id, error.code, sent)
        return self.get(call_id)

    def _failure(self, call_id: UUID, code: str, unknown: bool) -> CallResponse:
        with self.sessions() as session, session.begin():
            self._lock(session)
            row = self._row(session, call_id)
            if row.finalized_at is None and row.status == "reserved" and row.provider_call_id is None:
                row.status = "unknown" if unknown else "failed"
                row.error_code = code
                self._finish(session, row, uncertain=unknown)
            self._event(session, row, "provider_error")
            return self._response(row)

    def _identity(self, row: OutboundCall, call: RetellCall) -> None:
        metadata = call.metadata or {}
        if (
            call.call_type != "phone_call" or call.direction != "outbound"
            or call.agent_id != row.agent_id or call.agent_version != row.agent_version
            or metadata.get("dwellcall_outbound_id") != str(row.id)
            or metadata.get("authorization") != row.request_hash
            or not call.from_number or not call.to_number
            or self._hash("caller", call.from_number) != row.caller_hash
            or self._hash("destination", call.to_number) != row.destination_hash
            or (row.provider_call_id is not None and row.provider_call_id != call.call_id)
            or row.send_started_at is None
        ):
            raise ApiError(status_code=403, code="OUTBOUND_CALL_IDENTITY_INVALID", message="The provider call does not match this authorized request")

    def _finish(self, session: Session, row: OutboundCall, *, uncertain: bool = False) -> None:
        audio = session.get(AudioSession, row.audio_session_id, with_for_update=True)
        if audio is None:
            raise unavailable("The shared audio reservation is missing; investigate before calling")
        audio.status = "unknown" if uncertain else "ended"
        if not uncertain:
            row.finalized_at = audio.finalized_at = datetime.now(UTC)
        else:
            row.finalized_at = audio.finalized_at = None

    def apply(self, call: RetellCall, kind: str, digest: str | None = None) -> UUID:
        try:
            call_id = UUID(str((call.metadata or {}).get("dwellcall_outbound_id", "")))
        except ValueError:
            raise ApiError(status_code=403, code="OUTBOUND_CALL_IDENTITY_INVALID", message="The provider call has no authorized outbound reservation") from None
        with self.sessions() as session, session.begin():
            self._lock(session)
            row = self._row(session, call_id)
            self._identity(row, call)
            if digest and session.scalar(select(OutboundCallEvent.id).where(OutboundCallEvent.fingerprint == digest)) is not None:
                return row.id
            if row.mock and kind != "mock":
                raise ApiError(status_code=403, code="OUTBOUND_CALL_IDENTITY_INVALID", message="Live evidence cannot update a mock call")
            row.provider_call_id = call.call_id
            reason = call.disconnection_reason
            if reason == "user_requested_dnc":
                if session.get(OutboundSuppression, row.destination_hash) is None:
                    session.add(OutboundSuppression(destination_hash=row.destination_hash, created_at=datetime.now(UTC)))
            connected_reasons = {"user_hangup", "agent_hangup", "user_requested_dnc", "max_duration_reached", "inactivity", "manual_stopped", "call_transfer", "transfer_bridged"}
            if call.start_timestamp is not None and (call.call_status == "ongoing" or (call.call_status == "ended" and reason in connected_reasons)):
                row.started_at = datetime.fromtimestamp(call.start_timestamp / 1000, UTC)
            if call.duration_ms is not None:
                row.duration_seconds = max(row.duration_seconds or 0, call.duration_ms // 1000)
            transfer_evidence = reason in {"call_transfer", "transfer_bridged"}
            if transfer_evidence:
                expected = self.settings.outbound_human_number.get_secret_value()
                row.transfer_status = "refer_accepted" if reason == "call_transfer" and expected and call.transfer_destination == expected else "unconfirmed"
                if not row.carrier_end_confirmed:
                    row.status = "transferred" if row.transfer_status == "refer_accepted" else "transfer_unconfirmed"
                    self._finish(session, row, uncertain=True)
            elif row.finalized_at is None:
                if reason == "transfer_cancelled" and row.transfer_status in {"requested", "unconfirmed"}:
                    row.transfer_status = "failed"
                if call.call_status in {"ended", "error", "not_connected"}:
                    if row.transfer_status in {"requested", "unconfirmed", "refer_accepted"}:
                        row.status = "transfer_unconfirmed"
                        self._finish(session, row, uncertain=True)
                    else:
                        row.status = (
                            "rejected" if reason in {"dial_busy", "user_declined"}
                            else "unanswered" if reason in {"dial_no_answer", "voicemail_reached", "ivr_reached", "registered_call_timeout"}
                            else "completed" if call.call_status == "ended" and reason in connected_reasons
                            else "failed"
                        )
                        if row.status == "failed":
                            row.error_code = {
                                "telephony_provider_permission_denied": "TELNYX_DESTINATION_OR_CALLER_ID_DENIED",
                                "telephony_provider_unavailable": "TELNYX_UNAVAILABLE",
                                "sip_routing_error": "TELNYX_SIP_ROUTING_ERROR",
                                "invalid_destination": "RETELL_INVALID_DESTINATION",
                                "concurrency_limit_reached": "RETELL_CONCURRENCY_LIMIT",
                                "budget_reached": "RETELL_BUDGET_REACHED",
                                "no_valid_payment": "RETELL_PAYMENT_REQUIRED",
                                "credit_exhausted": "RETELL_CREDIT_EXHAUSTED",
                                "error_llm_websocket_open": "RETELL_LLM_CONNECTION_FAILED",
                                "error_llm_websocket_lost_connection": "RETELL_LLM_CONNECTION_LOST",
                            }.get(reason or "", "RETELL_CALL_FAILED")
                        self._finish(session, row)
                elif row.status not in {"transferred", "transfer_unconfirmed"}:
                    if call.call_status == "ongoing":
                        row.status = "in_progress"
                    elif row.status == "reserved":
                        row.status = "dialing"
            self._event(session, row, kind, digest)
            return row.id

    def _mock_snapshot(self, row: OutboundCall) -> RetellCall:
        number = next((n for n in self.settings.allowed_numbers if self._hash("destination", n) == row.destination_hash), None)
        if number is None:
            raise unavailable("Restore the mock allowlist to reconcile this simulated call")
        elapsed = (datetime.now(UTC) - row.created_at).total_seconds()
        return RetellCall(
            call_id="call_mock_" + row.id.hex, agent_id=row.agent_id,
            agent_version=row.agent_version, call_type="phone_call", direction="outbound",
            call_status="ended" if elapsed >= 15 else "ongoing" if elapsed >= 2 else "registered",
            from_number=self.settings.outbound_from_number.get_secret_value(), to_number=number,
            metadata={"dwellcall_outbound_id": str(row.id), "authorization": row.request_hash},
            start_timestamp=int((row.created_at.timestamp() + 2) * 1000) if elapsed >= 2 else None,
            duration_ms=13000 if elapsed >= 15 else None,
            disconnection_reason="agent_hangup" if elapsed >= 15 else None,
        )

    def get(self, call_id: UUID) -> CallResponse:
        with self.sessions() as session:
            row = self._row(session, call_id)
            snapshot = self._mock_snapshot(row) if row.mock and row.send_started_at is not None and row.finalized_at is None else None
        if snapshot is not None:
            self.apply(snapshot, "mock")
        with self.sessions() as session, session.begin():
            self._lock(session)
            row = self._row(session, call_id)
            timeout = 60 if row.status == "reserved" else self.settings.outbound_max_duration_seconds + self.settings.outbound_ringing_seconds + 60
            if row.finalized_at is None and row.status in {"reserved", "dialing", "ringing", "in_progress"} and datetime.now(UTC) > row.created_at + timedelta(seconds=timeout):
                row.status = "unknown"
                self._finish(session, row, uncertain=True)
                self._event(session, row, "receipt_or_final_evidence_overdue")
            return self._response(row)

    def get_request(self, request_id: UUID) -> CallResponse:
        with self.sessions() as session:
            call_id = session.scalar(select(OutboundCall.id).where(OutboundCall.request_id == request_id))
        if call_id is None:
            raise ApiError(status_code=404, code="OUTBOUND_REQUEST_NOT_FOUND", message="The request is not visible yet; inspect history before starting another call")
        return self.get(call_id)

    def history(self) -> list[CallResponse]:
        with self.sessions() as session:
            return [self._response(row) for row in session.scalars(select(OutboundCall).order_by(OutboundCall.created_at.desc()).limit(25))]

    def refresh(self, call_id: UUID, provider_call_id: str | None = None) -> CallResponse:
        with self.sessions() as session:
            row = self._row(session, call_id)
            mock = row.mock
            bound = row.provider_call_id
            request_hash = row.request_hash
        if mock:
            return self.get(call_id)
        try:
            lookup_id = provider_call_id or bound
            call = self.provider.retrieve(lookup_id) if lookup_id else self.provider.find(str(call_id), request_hash)
        except OutboundProviderError as error:
            raise ApiError(status_code=503, code=error.code, message=str(error)) from None
        if call is not None:
            if (call.metadata or {}).get("dwellcall_outbound_id") != str(call_id):
                raise ApiError(status_code=403, code="OUTBOUND_CALL_IDENTITY_INVALID", message="This provider call belongs to another request")
            self.apply(call, "operator_reconciliation")
        return self.get(call_id)

    def admit_phone(self, call: RetellCall) -> tuple[str, str]:
        call_id = self.apply(call, "phone_identity_verified")
        with self.sessions() as session, session.begin():
            guard = self._lock(session)
            row = self._row(session, call_id)
            if not self.settings.outbound_enabled or guard.outbound_paused or row.mock or row.socket_admitted or row.finalized_at is not None or call.call_status not in {"registered", "ongoing"} or row.transfer_status != "not_requested":
                raise ApiError(status_code=409, code="OUTBOUND_SOCKET_NOT_ADMITTED", message="This phone conversation is disabled, inactive or already admitted")
            if not call.to_number:
                raise unavailable()
            self._policy(session, guard, call.to_number)
            row.socket_admitted = True
            audio = session.get(AudioSession, row.audio_session_id)
            if audio is None or audio.status == "ended":
                raise ApiError(status_code=409, code="OUTBOUND_SOCKET_NOT_ADMITTED", message="The shared audio reservation is unresolved")
            audio.status = "active"
            row.status = "in_progress" if call.call_status == "ongoing" else "dialing"
            self._event(session, row, "phone_socket_admitted")
            return row.audio_session_id, row.scenario

    def validate_phone_details(self, audio_id: str, call: RetellCall) -> None:
        with self.sessions() as session:
            row = session.scalar(select(OutboundCall).where(OutboundCall.audio_session_id == audio_id))
            if row is None:
                raise unavailable()
            self._identity(row, call)

    def remaining_seconds(self, audio_id: str) -> float:
        with self.sessions() as session:
            row = session.scalar(select(OutboundCall).where(OutboundCall.audio_session_id == audio_id))
            if row is None:
                return 0
            origin = row.started_at or row.send_started_at or row.created_at
            return max(0, self.settings.outbound_max_duration_seconds - (datetime.now(UTC) - origin).total_seconds())

    def event_digest(self, body: bytes) -> str:
        return self._hash("event", hashlib.sha256(body).hexdigest())

    def disconnect(self, audio_id: str) -> None:
        with self.sessions() as session, session.begin():
            self._lock(session)
            row = session.scalar(select(OutboundCall).where(OutboundCall.audio_session_id == audio_id).with_for_update())
            if row is not None and row.finalized_at is None:
                if row.transfer_status in {"requested", "refer_accepted", "unconfirmed"}:
                    row.status = "transfer_unconfirmed"
                    if row.transfer_status == "requested":
                        row.transfer_status = "unconfirmed"
                else:
                    row.status = "unknown"
                self._finish(session, row, uncertain=True)
                self._event(session, row, "phone_socket_disconnected")

    def reserve_transfer(self, audio_id: str, confirmation_hash: str) -> str:
        with self.sessions() as session, session.begin():
            guard = self._lock(session)
            row = session.scalar(select(OutboundCall).where(OutboundCall.audio_session_id == audio_id).with_for_update())
            if row is None or row.mock or row.finalized_at is not None or row.status != "in_progress" or row.transfer_status != "not_requested" or not self.settings.outbound_transfer_enabled or guard.transfer_paused or guard.outbound_paused:
                raise ApiError(status_code=409, code="OUTBOUND_TRANSFER_DISABLED", message="Human transfer is unavailable for this call")
            row.transfer_status = "requested"
            row.transfer_confirmation_hash = confirmation_hash
            self._event(session, row, "caller_confirmed_fixed_destination_transfer")
            return self.settings.outbound_human_number.get_secret_value()

    def suppress_call(self, audio_id: str) -> None:
        with self.sessions() as session, session.begin():
            self._lock(session)
            row = session.scalar(select(OutboundCall).where(OutboundCall.audio_session_id == audio_id))
            if row is not None and session.get(OutboundSuppression, row.destination_hash) is None:
                session.add(OutboundSuppression(destination_hash=row.destination_hash, created_at=datetime.now(UTC)))
                self._event(session, row, "caller_requested_do_not_call")

    def suppress(self, number: str) -> None:
        with self.sessions() as session, session.begin():
            self._lock(session)
            key = self._hash("destination", number)
            if session.get(OutboundSuppression, key) is None:
                session.add(OutboundSuppression(destination_hash=key, created_at=datetime.now(UTC)))

    def controls(self, values: ControlsInput | None = None) -> dict[str, bool]:
        with self.sessions() as session, session.begin():
            guard = self._lock(session)
            if values is not None:
                guard.outbound_paused = values.calls_paused
                guard.transfer_paused = values.transfers_paused
            return {"calls_paused": guard.outbound_paused, "transfers_paused": guard.transfer_paused}

    def transfer_available(self) -> bool:
        controls = self.controls()
        return self.settings.outbound_transfer_enabled and not controls["calls_paused"] and not controls["transfers_paused"]

    def active(self, audio_id: str) -> bool:
        with self.sessions() as session:
            guard = session.get(AudioAdmissionGuard, 1)
            audio = session.get(AudioSession, audio_id)
            return bool(guard and not guard.outbound_paused and audio and audio.status == "active")

    def stop(self, call_id: UUID) -> CallResponse:
        with self.sessions() as session, session.begin():
            self._lock(session)
            row = self._row(session, call_id)
            if row.finalized_at is not None:
                return self._response(row)
            provider_id, mock = row.provider_call_id, row.mock
            row.status = "unknown"
            self._finish(session, row, uncertain=True)
            self._event(session, row, "operator_stop_requested")
        if mock:
            return self.carrier_ended(call_id)
        if not provider_id:
            raise unavailable("Reconcile the unknown provider call before requesting stop; the reservation remains held")
        try:
            self.provider.stop(provider_id)
        except OutboundProviderError as error:
            raise ApiError(status_code=503, code=error.code, message=str(error)) from None
        return self.refresh(call_id)

    def carrier_ended(self, call_id: UUID) -> CallResponse:
        with self.sessions() as session, session.begin():
            self._lock(session)
            row = self._row(session, call_id)
            if row.finalized_at is None:
                if not row.mock and (datetime.now(UTC) - (row.send_started_at or row.created_at)).total_seconds() < 60:
                    raise ApiError(status_code=409, code="OUTBOUND_SEND_IN_FLIGHT", message="Wait for the in-flight provider request, then verify every carrier leg has ended")
                row.status = "completed" if row.started_at is not None else "failed"
                row.carrier_end_confirmed = True
                self._finish(session, row)
                self._event(session, row, "operator_confirmed_all_carrier_legs_ended")
            return self._response(row)

    @staticmethod
    def _response(row: OutboundCall) -> CallResponse:
        message = MESSAGES[row.status]
        if row.error_code:
            message += " Configuration or provider error: " + row.error_code + "."
        if row.mock:
            message = "SIMULATED — no telephone call. " + message
        return CallResponse(
            id=row.id, request_id=row.request_id, status=CallStatus(row.status),
            provider_call_id=row.provider_call_id,
            transfer_status=cast(TransferStatus, row.transfer_status), scenario=row.scenario,
            created_at=row.created_at, started_at=row.started_at, finalized_at=row.finalized_at,
            duration_seconds=row.duration_seconds, terminal=row.finalized_at is not None,
            mock=row.mock, message=message, error_code=row.error_code,
        )
