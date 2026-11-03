from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class AgentProperty(BaseModel):
    listing_id: UUID
    source_key: str
    source_listing_id: str
    listing_url: str | None = None
    street_address: str | None = None
    status: str | None = None
    price: str | None = None
    currency: str | None = None
    permission_version: int
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None


class AgentContactSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: UUID
    full_name: str = Field(min_length=1, max_length=200)
    brokerage: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, pattern=r"^\+[1-9][0-9]{7,14}$")
    properties: list[AgentProperty] = Field(min_length=1, max_length=100)
    contact_references: list[dict[str, str | int]] = Field(max_length=100)
    last_discovered_at: AwareDatetime | None = None

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str | None) -> str | None:
        from pydantic import EmailStr, TypeAdapter

        return str(TypeAdapter(EmailStr).validate_python(value)).casefold() if value is not None else None


class AgentSyncRequest(BaseModel):
    agent_ids: list[UUID] = Field(min_length=1, max_length=50)


class OperatorEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_reference: str = Field(pattern=r"^[A-Za-z0-9_-]{1,160}$")


class ContactBinding(OperatorEvidence):
    contact_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")


class GhlSetupInput(OperatorEvidence):
    custom_fields: dict[str, str] | None = Field(default=None, max_length=5)

    @field_validator("custom_fields")
    @classmethod
    def mapping_ids(cls, values: dict[str, str] | None) -> dict[str, str] | None:
        if values is None:
            return None
        from dwellcall.crm.settings import CrmSettings
        return CrmSettings.validate_ghl_fields(values)



class LocationProvisionInput(OperatorEvidence):
    approve_external_creation: Literal[True]
    agency_scope_confirmed: Literal[True]
    plan_permits_provisioning: Literal[True]
    plan_evidence_reference: str = Field(pattern=r"^[A-Za-z0-9_-]{1,160}$")
    name: str = Field(min_length=1, max_length=100)
    address: str = Field(min_length=1, max_length=200)
    city: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=1, max_length=100)
    country: str = Field(pattern=r"^[A-Z]{2}$")
    postal_code: str = Field(min_length=1, max_length=20)
    timezone: str = Field(min_length=1, max_length=100)

    @field_validator("approve_external_creation", "agency_scope_confirmed", "plan_permits_provisioning", mode="before")
    @classmethod
    def explicit_approval(cls, value: object) -> object:
        if value is not True:
            raise ValueError("Explicit true approval is required")
        return value


class AgentJobStatus(BaseModel):
    id: UUID
    agent_id: UUID
    status: str
    code: str | None
    attempts: int
    next_attempt_at: datetime
    contact_id: str | None
    opportunity_id: str | None
    company_id: str | None = None
    last_synced_at: datetime | None = None
    created_at: datetime


class AgentPreview(BaseModel):
    agent_id: UUID
    eligible: bool
    reason: str | None = None
    snapshot: AgentContactSnapshot | None = None
    contact_id: str | None = None
    sync_status: str | None = None
    company_id: str | None = None
    last_synced_at: datetime | None = None


class AgentPreviewPage(BaseModel):
    items: list[AgentPreview]
    page: int
    page_size: int
    total: int


class AgentJobPage(BaseModel):
    items: list[AgentJobStatus]
    page: int
    page_size: int
    total: int


class AgentAuditEntry(BaseModel):
    event_type: str
    evidence_reference: str | None
    occurred_at: datetime


class AgentAuditPage(BaseModel):
    items: list[AgentAuditEntry]
    page: int
    page_size: int
    total: int
