from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from dwellcall.account_access.schemas import AccountView
from dwellcall.account_access.security import bearer_token, require_account_portal
from dwellcall.account_access.service import AccountAccessService
from dwellcall.billing.errors import billing_error
from dwellcall.billing.gateway import StripeGateway
from dwellcall.billing.schemas import BillingRead, CatalogRead, CheckoutCreate, RedirectRead
from dwellcall.billing.service import BillingService, catalog_response
from dwellcall.settings import ApiSettings


def create_billing_router(settings: ApiSettings, sessions: sessionmaker[Session]) -> APIRouter:
    router = APIRouter()
    service = BillingService(sessions, settings)
    access = AccountAccessService(sessions, settings)

    def identity(
        key: Annotated[str | None, Header(alias="X-Account-Portal-Key")] = None,
        authorization: Annotated[str | None, Header()] = None,
    ) -> AccountView:
        require_account_portal(settings, key)
        user = access.identity(bearer_token(authorization))
        if not user.operator_access:
            raise billing_error(403, "billing_approval_required", "Owner approval is required before purchasing or managing a subscription.")
        return user

    Identity = Annotated[AccountView, Depends(identity)]

    @router.get("/api/v1/billing/plans", response_model=CatalogRead)
    def plans() -> CatalogRead:
        return catalog_response(settings)

    @router.get("/api/v1/account/billing/status", response_model=BillingRead)
    def summary(user: Identity) -> BillingRead:
        return service.summary(user.id)

    @router.post("/api/v1/account/billing/checkout", response_model=RedirectRead)
    def checkout(data: CheckoutCreate, user: Identity) -> RedirectRead:
        return RedirectRead(url=service.create_checkout(user.id, user.email, data.plan, data.request_id))

    @router.post("/api/v1/account/billing/portal", response_model=RedirectRead)
    def portal(user: Identity) -> RedirectRead:
        return RedirectRead(url=service.portal(user.id))

    @router.post("/api/v1/account/billing/refresh", response_model=BillingRead)
    def refresh(user: Identity) -> BillingRead:
        return service.refresh(user.id)

    @router.post("/api/v1/billing/webhook")
    async def webhook(request: Request) -> dict[str, bool]:
        if not settings.billing_enabled:
            raise billing_error(503, "billing_unavailable", "Billing is not enabled.")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 1_048_576:
                raise billing_error(413, "stripe_event_too_large", "Webhook body is too large.")
            body.extend(chunk)
        event = StripeGateway(settings).verify_event(bytes(body), request.headers.get("stripe-signature", ""))
        await run_in_threadpool(service.receive_event, event)
        return {"received": True}

    return router
