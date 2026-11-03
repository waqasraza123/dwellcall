from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from dwellcall.crm.agent_schemas import AgentContactSnapshot
from dwellcall.crm.schemas import ConsultationSnapshot

DeliveryStatus = Literal["sent", "retry_wait", "failed", "ignored", "unknown", "disabled"]


@dataclass(frozen=True)
class CrmExportRequest:
    export_id: UUID
    destination: str
    snapshot: ConsultationSnapshot


@dataclass(frozen=True)
class DeliveryResult:
    status: DeliveryStatus
    code: str
    person_id: int | None = None
    retry_after_seconds: int = 0


class CrmProvider(Protocol):
    def send(self, request: CrmExportRequest) -> DeliveryResult: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class AgentExportRequest:
    export_id: UUID
    destination: str
    snapshot: "AgentContactSnapshot"
    fingerprint: str
    fields: dict[str, str]
    contact_id: str | None = None
    opportunity_id: str | None = None
    company_id: str | None = None
    uncertain_code: str | None = None


@dataclass(frozen=True)
class AgentDeliveryResult:
    status: DeliveryStatus
    code: str
    contact_id: str | None = None
    opportunity_id: str | None = None
    retry_after_seconds: int = 0
    company_id: str | None = None


class AgentCrmProvider(Protocol):
    def send_agent(self, request: AgentExportRequest) -> AgentDeliveryResult: ...

    def reconcile_agent(self, request: AgentExportRequest) -> AgentDeliveryResult: ...

    def close(self) -> None: ...
