from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

ShortText = Annotated[str, Field(min_length=1, max_length=200)]
EvidenceReference = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,120}$")]


class ConfirmedContact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    first_name: ShortText | None = None
    last_name: ShortText | None = None
    email: EmailStr | None = None
    phone: str | None = Field(default=None, pattern=r"^\+[1-9][0-9]{7,14}$")

    @model_validator(mode="after")
    def contact_required(self) -> Self:
        if self.email is None and self.phone is None:
            raise ValueError("A confirmed email or phone is required")
        return self


class ConfirmedBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    amount: Decimal = Field(gt=0, le=1_000_000_000, max_digits=12, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    period: Literal["monthly", "purchase"]


class ConsultationSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    contact: ConfirmedContact
    scenario: Literal["renting", "buying", "luxury"]
    budget: ConfirmedBudget | None = None
    location: ShortText | None = None
    requirements: tuple[ShortText, ...] = Field(default=(), max_length=20)
    summary: str = Field(min_length=1, max_length=1000)
    fictional_properties: Literal[True] = True

    @field_validator("fictional_properties", mode="before")
    @classmethod
    def fictional_only(cls, value: object) -> object:
        if value is not True:
            raise ValueError("Only fictional demonstration consultations are supported")
        return value


class ExportAuthorization(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,200}$")
    snapshot_version: int = Field(ge=1, le=2_147_483_647)
    destination: str = Field(pattern=r"^[0-9a-f]{64}$")
    business_name: ShortText
    snapshot: ConsultationSnapshot
    details_confirmed: Literal[True]
    storage_permission: Literal[True]
    crm_permission: Literal[True]
    consent_version: Literal["dwellcall-crm-v1"]
    permission_reference: EvidenceReference

    @field_validator(
        "details_confirmed", "storage_permission", "crm_permission", mode="before"
    )
    @classmethod
    def explicit_permission(cls, value: object) -> object:
        if value is not True:
            raise ValueError("Separate explicit confirmation and permission are required")
        return value


class ExportStatus(BaseModel):
    id: UUID
    status: str
    code: str | None
    attempts: int
    created_at: datetime
    next_attempt_at: datetime
    permission_revoked_at: datetime | None
    permission_expires_at: datetime
    replayed: bool = False


class ReconciliationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: Literal["delivered", "do_not_retry"]
    evidence_reference: EvidenceReference
    person_id: int | None = Field(default=None, strict=True, gt=0, le=2_147_483_647)

    @model_validator(mode="after")
    def receipt_required(self) -> Self:
        if self.resolution == "delivered" and self.person_id is None:
            raise ValueError("A verified person receipt is required")
        return self


class DispatchResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_reference: EvidenceReference
