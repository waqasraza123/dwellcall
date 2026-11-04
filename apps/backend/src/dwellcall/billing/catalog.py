from dataclasses import dataclass
from typing import Literal

type PlanKey = Literal["free", "pro", "team"]
STRIPE_PRODUCT_ID = "dwellcall_subscription_v1"


@dataclass(frozen=True)
class Plan:
    key: PlanKey
    name: str
    amount: int
    description: str


PLANS: dict[PlanKey, Plan] = {
    "free": Plan("free", "Free", 0, "Start with your DwellCall account."),
    "pro": Plan("pro", "Pro", 2900, "A monthly subscription for your real estate workflow."),
    "team": Plan("team", "Team", 7900, "A monthly subscription for your growing real estate operation."),
}

CORE_FEATURES = (
    "Owner-approved workspace access", "Listing and agent intelligence",
    "Permission-based CRM workflows", "AI conversations when enabled",
)
