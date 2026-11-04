from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dwellcall.telephony.outbound.destinations import normalize_phone_number


class CallStatus(StrEnum):
    RESERVED = "reserved"
    DIALING = "dialing"
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REJECTED = "rejected"
    UNANSWERED = "unanswered"
    FAILED = "failed"
    UNKNOWN = "unknown"
    TRANSFERRED = "transferred"
    TRANSFER_UNCONFIRMED = "transfer_unconfirmed"


FINAL_STATUSES = frozenset({"completed", "rejected", "unanswered", "failed"})
TransferStatus = Literal["not_requested", "requested", "refer_accepted", "failed", "unconfirmed"]


class CallInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    phone_number: str = Field(min_length=1, max_length=64)
    scenario: Literal["renting", "buying", "luxury"]
    consent: Literal[True]
    consent_version: Literal["dwellcall-ai-call-v1"]
    recipient_consent_confirmed: Literal[True]
    do_not_call_checked: Literal[True]

    @field_validator("phone_number")
    @classmethod
    def normalize(cls, value: str) -> str:
        return normalize_phone_number(value)

    @field_validator("consent", "recipient_consent_confirmed", "do_not_call_checked", mode="before")
    @classmethod
    def explicit_confirmation(cls, value: object) -> object:
        if value is not True:
            raise ValueError("Explicit recipient permission and do-not-call review are required")
        return value


class CallResponse(BaseModel):
    id: UUID
    request_id: UUID
    provider_call_id: str | None = None
    status: CallStatus
    transfer_status: TransferStatus
    scenario: str
    created_at: datetime
    started_at: datetime | None
    finalized_at: datetime | None
    duration_seconds: int | None
    terminal: bool
    mock: bool
    message: str
    error_code: str | None


class ControlsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    calls_paused: bool
    transfers_paused: Literal[True]

    @field_validator("transfers_paused", mode="before")
    @classmethod
    def transfers_stay_disabled(cls, value: object) -> object:
        if value is not True:
            raise ValueError("Human transfers are permanently unavailable")
        return value


class SuppressInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone_number: str = Field(min_length=1, max_length=64)

    @field_validator("phone_number")
    @classmethod
    def normalize(cls, value: str) -> str:
        return normalize_phone_number(value)


class CarrierEndedInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    all_carrier_legs_ended: Literal[True]

    @field_validator("all_carrier_legs_ended", mode="before")
    @classmethod
    def explicit_confirmation(cls, value: object) -> object:
        if value is not True:
            raise ValueError("Explicit confirmation that every carrier leg ended is required")
        return value


class BindInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_call_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,200}$")
