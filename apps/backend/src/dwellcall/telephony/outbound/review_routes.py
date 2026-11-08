from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query

from dwellcall.account_access.schemas import AccountView
from dwellcall.account_access.security import bearer_token, require_account_portal
from dwellcall.account_access.service import AccountAccessService
from dwellcall.errors import ApiError
from dwellcall.settings import ApiSettings
from dwellcall.telephony.outbound.review_schemas import LeadReviewInput, LeadReviewRead
from dwellcall.telephony.outbound.reviews import CallLeadReviewService
from dwellcall.telephony.outbound.service import OutboundCallService


def create_lead_review_router(settings: ApiSettings, calls: OutboundCallService) -> APIRouter:
    access = AccountAccessService(calls.sessions, settings)
    service = CallLeadReviewService(calls)

    def operator(key: Annotated[str | None, Header(alias="X-Account-Portal-Key")] = None,
                 authorization: Annotated[str | None, Header()] = None) -> AccountView:
        require_account_portal(settings, key)
        user = access.identity(bearer_token(authorization))
        if not user.operator_access:
            raise ApiError(status_code=403, code="LEAD_REVIEW_OPERATOR_REQUIRED", message="An approved operator account is required")
        return user

    Operator = Annotated[AccountView, Depends(operator)]
    router = APIRouter(prefix="/api/v1/account/call-leads")

    @router.get("/tasks")
    def tasks(user: Operator, status: Annotated[Literal["open", "completed", "cancelled", "deferred"], Query()] = "open") -> list[dict[str, object]]:
        return service.tasks(status)

    @router.get("/{call_id}", response_model=LeadReviewRead)
    def review(call_id: UUID, user: Operator) -> LeadReviewRead:
        return service.get(call_id)

    @router.post("/{call_id}/actions", response_model=LeadReviewRead)
    def action(call_id: UUID, data: LeadReviewInput, user: Operator) -> LeadReviewRead:
        return service.apply(call_id, user.id, data)

    return router
