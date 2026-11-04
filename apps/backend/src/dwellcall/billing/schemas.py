from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from dwellcall.billing.catalog import PlanKey


class PlanRead(BaseModel):
    key: PlanKey
    name: str
    amount: int
    currency: Literal["usd"] = "usd"
    interval: Literal["month"] = "month"
    description: str
    features: list[str]


class CatalogRead(BaseModel):
    plans: list[PlanRead]
    checkout_enabled: bool


class CheckoutCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    plan: Literal["pro", "team"]
    request_id: UUID


class RedirectRead(BaseModel):
    url: str


class BillingRead(BaseModel):
    account_id: UUID
    plan: PlanKey
    subscription_status: str
    period_start: datetime | None
    period_end: datetime | None
    cancel_at_period_end: bool
    last_synced_at: datetime | None
    checkout_enabled: bool
    portal_enabled: bool
    sync_pending: bool
    checkout_pending: bool
