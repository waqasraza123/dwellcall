from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from dwellcall.database.models.outbound_verification import (
    OutboundPhoneVerification,
)
from dwellcall.errors import ApiError
from dwellcall.telephony.outbound.destinations import validate_destination
from dwellcall.telephony.outbound.settings import OutboundSettings
from dwellcall.telephony.outbound.sms_provider import (
    TelnyxVerificationProvider,
    sms_unavailable,
)
from dwellcall.telephony.outbound.verification_schemas import (
    SmsChallengeResponse,
    SmsStartInput,
    SmsVerifyInput,
)


def verification_required() -> ApiError:
    return ApiError(
        status_code=403, code="DEMO_PHONE_VERIFICATION_REQUIRED",
        message="Verify your phone number with a new text-message code first.",
    )


class PhoneVerificationService:
    def __init__(
        self, sessions: sessionmaker[Session], settings: OutboundSettings,
        lock: Callable[[Session], object], digest: Callable[[str, str], str],
        provider: TelnyxVerificationProvider | None = None,
    ) -> None:
        self.sessions, self.settings = sessions, settings
        self.lock, self.digest = lock, digest
        self.provider = provider or TelnyxVerificationProvider(settings)

    def start(self, data: SmsStartInput, owner: str) -> SmsChallengeResponse:
        if not self.settings.website_available:
            raise sms_unavailable()
        validate_destination(data.phone_number, frozenset({"US"}))
        if (
            data.phone_number not in self.settings.allowed_numbers
        ):
            raise ApiError(
                status_code=403, code="DEMO_NUMBER_NOT_AUTHORIZED",
                message="This number is not approved for the private demo.",
            )
        owner_hash = self.digest("owner", owner)
        destination = self.digest("destination", data.phone_number)
        now = datetime.now(UTC)
        with self.sessions() as session, session.begin():
            self.lock(session)
            base = select(OutboundPhoneVerification).where(
                OutboundPhoneVerification.created_at >= now - timedelta(days=1),
            )

            def count(*conditions: ColumnElement[bool]) -> int:
                return (
                    session.scalar(
                        select(func.count()).select_from(
                            base.where(*conditions).subquery()
                        )
                    ) or 0
                )

            recent = session.scalar(
                base.where(
                    or_(
                        OutboundPhoneVerification.owner_hash == owner_hash,
                        OutboundPhoneVerification.destination_hash == destination,
                    ),
                    OutboundPhoneVerification.created_at >= now - timedelta(
                        seconds=self.settings.outbound_sms_cooldown_seconds
                    ),
                ).limit(1)
            )
            if (
                recent is not None
                or count() >= self.settings.outbound_sms_daily_limit
                or count(OutboundPhoneVerification.owner_hash == owner_hash)
                >= self.settings.outbound_sms_account_daily_limit
                or count(OutboundPhoneVerification.destination_hash == destination)
                >= self.settings.outbound_sms_number_daily_limit
            ):
                raise ApiError(
                    status_code=429, code="DEMO_SMS_LIMIT",
                    message="The text verification limit has been reached. Try later.",
                )
            row = OutboundPhoneVerification(
                owner_hash=owner_hash,
                destination_hash=destination, created_at=now,
                expires_at=now + timedelta(
                    seconds=self.settings.outbound_sms_ttl_seconds
                ), attempts=0, consent_version=data.sms_consent_version,
            )
            session.add(row)
            session.flush()
            challenge_id = row.id
        provider_id = self.provider.send(data.phone_number)
        with self.sessions() as session, session.begin():
            row = session.get(
                OutboundPhoneVerification, challenge_id, with_for_update=True
            )
            if row is None or row.expires_at <= datetime.now(UTC):
                raise sms_unavailable()
            row.provider_verification_id = provider_id
            return self._response(row)

    def verify(self, data: SmsVerifyInput, owner: str) -> SmsChallengeResponse:
        if not self.settings.website_available:
            raise sms_unavailable()
        with self.sessions() as session, session.begin():
            row = session.scalar(
                select(OutboundPhoneVerification).where(
                    OutboundPhoneVerification.id == data.challenge_id,
                    OutboundPhoneVerification.owner_hash == self.digest("owner", owner),
                ).with_for_update()
            )
            if (
                row is None or row.expires_at <= datetime.now(UTC)
                or row.provider_verification_id is None
                or row.consumed_by_request_id is not None
            ):
                raise verification_required()
            if row.verified_at is not None:
                return self._response(row)
            if row.attempts >= 5:
                raise verification_required()
            row.attempts += 1
            provider_id = row.provider_verification_id
            destination = row.destination_hash
        # Commit the attempt before the network request, including timeout failures.
        number = self.provider.verify(provider_id, data.code)
        with self.sessions() as session, session.begin():
            row = session.get(
                OutboundPhoneVerification, data.challenge_id, with_for_update=True
            )
            if (
                row is None or row.expires_at <= datetime.now(UTC)
                or row.consumed_by_request_id is not None
            ):
                raise verification_required()
            if number is not None and self.digest("destination", number) == destination:
                row.verified_at = datetime.now(UTC)
                return self._response(row)
        raise ApiError(
            status_code=422, code="DEMO_SMS_CODE_INVALID",
            message="That code is invalid or expired. Check the text and try again.",
        )

    @staticmethod
    def consume(
        session: Session, owner_hash: str, destination: str,
        challenge_id: UUID | None, request_id: UUID,
    ) -> None:
        if challenge_id is None:
            raise verification_required()
        row = session.scalar(
            select(OutboundPhoneVerification).where(
                OutboundPhoneVerification.id == challenge_id,
                OutboundPhoneVerification.owner_hash == owner_hash,
                OutboundPhoneVerification.destination_hash == destination,
            ).with_for_update()
        )
        if (
            row is None or row.verified_at is None
            or row.expires_at <= datetime.now(UTC)
            or row.consumed_by_request_id is not None
        ):
            raise verification_required()
        row.consumed_by_request_id = request_id

    @staticmethod
    def _response(row: OutboundPhoneVerification) -> SmsChallengeResponse:
        return SmsChallengeResponse(
            challenge_id=row.id, expires_at=row.expires_at,
            verified=row.verified_at is not None,
        )
