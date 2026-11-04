from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from dwellcall.billing.catalog import CORE_FEATURES, PLANS, PlanKey
from dwellcall.billing.errors import billing_error
from dwellcall.billing.gateway import StripeGateway
from dwellcall.billing.schemas import BillingRead, CatalogRead, PlanRead
from dwellcall.billing.state import active_plan, apply_subscription, stripe_datetime
from dwellcall.database.models.billing import BillingAccount, BillingCheckout, BillingEvent
from dwellcall.settings import ApiSettings

TERMINAL_SUBSCRIPTIONS = {"canceled", "incomplete_expired"}
SUBSCRIPTION_EVENTS = frozenset({
    "checkout.session.completed", "checkout.session.expired",
    "customer.subscription.created", "customer.subscription.updated",
    "customer.subscription.deleted", "customer.subscription.paused",
    "customer.subscription.resumed", "invoice.paid", "invoice.payment_failed",
    "invoice.payment_action_required",
})
REPLAY_WINDOW = timedelta(hours=23)


def stripe_url(value: object, kind: str) -> str:
    host = "checkout.stripe.com" if kind == "checkout" else "billing.stripe.com"
    if not isinstance(value, str) or len(value) > 4096:
        raise billing_error(502, "stripe_response_invalid", "Stripe returned an invalid redirect.")
    try:
        parsed = urlsplit(value)
        valid_port = parsed.port in {None, 443}
    except ValueError as error:
        raise billing_error(502, "stripe_response_invalid", "Stripe returned an invalid redirect.") from error
    if parsed.scheme != "https" or parsed.hostname != host or parsed.username or parsed.password or not valid_port:
        raise billing_error(502, "stripe_response_invalid", "Stripe returned an invalid redirect.")
    return value


def catalog_response(settings: ApiSettings) -> CatalogRead:
    return CatalogRead(plans=[PlanRead(**asdict(plan), features=list(CORE_FEATURES)) for plan in PLANS.values()], checkout_enabled=StripeGateway(settings).ready)


class BillingService:
    def __init__(self, sessions: sessionmaker[Session], settings: ApiSettings, gateway: StripeGateway | None = None) -> None:
        self.sessions, self.settings = sessions, settings
        self.gateway = gateway or StripeGateway(settings)

    def _ready(self) -> None:
        if not self.gateway.ready:
            raise billing_error(503, "billing_unavailable", "Paid billing is not available yet.")

    def _account(self, session: Session, account_id: UUID) -> BillingAccount:
        session.execute(insert(BillingAccount).values(account_id=account_id, livemode=self.settings.stripe_live_mode, plan="free", status="none", cancel_at_period_end=False).on_conflict_do_nothing(index_elements=["account_id"]))
        account = session.scalar(select(BillingAccount).where(BillingAccount.account_id == account_id).with_for_update().execution_options(populate_existing=True))
        if account is None:
            raise billing_error(503, "billing_unavailable", "Billing account is unavailable.")
        if account.livemode != self.settings.stripe_live_mode:
            raise billing_error(409, "billing_mode_mismatch", "This billing account belongs to another Stripe environment.")
        return account

    def _ensure_customer(self, account_id: UUID, email: str) -> None:
        with self.sessions() as session:
            account = self._account(session, account_id)
            if account.customer_id:
                session.commit()
                return
            if account.customer_started_at is None:
                account.customer_started_at = datetime.now(UTC)
            session.commit()
            account = self._account(session, account_id)
            if not account.customer_id:
                if account.customer_started_at is None or datetime.now(UTC) - account.customer_started_at >= REPLAY_WINDOW:
                    raise billing_error(409, "billing_customer_unconfirmed", "A previous customer creation is unconfirmed. The owner must reconcile it before retrying.")
                result = self.gateway.create_customer(account_id, email)
                if not isinstance(result.get("id"), str) or not result["id"].startswith("cus_") or result.get("livemode") is not self.settings.stripe_live_mode or result.get("metadata", {}).get("dwellcall_account_id") != str(account_id):
                    raise billing_error(502, "stripe_response_invalid", "Stripe customer identity could not be confirmed.")
                account.customer_id = result["id"]
            session.commit()

    def _reconcile(self, session: Session, account: BillingAccount) -> list[dict[str, Any]]:
        if not account.customer_id:
            return []
        event_ids = list(session.scalars(select(BillingEvent.event_id).where(BillingEvent.account_id == account.account_id, BillingEvent.processed_at.is_(None)).limit(500)))
        subscriptions = self.gateway.subscriptions(account.customer_id)
        current = [item for item in subscriptions if item.get("status") not in TERMINAL_SUBSCRIPTIONS]
        if len(current) > 1:
            account.plan, account.status = "free", "needs_review"
        else:
            selected = current[0] if current else next((item for item in subscriptions if item.get("id") == account.subscription_id), None)
            if selected is not None:
                apply_subscription(account, selected, self.settings)
            else:
                account.plan, account.status = "free", "none" if not account.subscription_id else "canceled"
                account.period_start, account.period_end, account.paid_through = None, None, None
        account.last_synced_at = datetime.now(UTC)
        if event_ids:
            session.execute(update(BillingEvent).where(BillingEvent.event_id.in_(event_ids)).values(processed_at=account.last_synced_at))
        return subscriptions

    def refresh(self, account_id: UUID) -> BillingRead:
        self._ready()
        with self.sessions() as session:
            account = self._account(session, account_id)
            subscriptions = self._reconcile(session, account)
            attempts = session.scalars(select(BillingCheckout).where(BillingCheckout.account_id == account_id, BillingCheckout.session_id.is_not(None), BillingCheckout.status.in_(["creating", "open"])).limit(50))
            for attempt in attempts:
                remote = self._checkout_remote(attempt, account)
                if remote.get("status") == "expired":
                    attempt.status = "expired"
                elif remote.get("status") == "complete" and any(item.get("id") == remote.get("subscription") for item in subscriptions):
                    attempt.status = "complete"
            session.commit()
        return self.summary(account_id)

    def summary(self, account_id: UUID) -> BillingRead:
        with self.sessions() as session:
            account = session.get(BillingAccount, account_id)
            if account and account.livemode != self.settings.stripe_live_mode:
                raise billing_error(409, "billing_mode_mismatch", "This billing account belongs to another Stripe environment.")
            pending = session.scalar(select(BillingEvent.event_id).where(BillingEvent.account_id == account_id, BillingEvent.processed_at.is_(None)).limit(1)) is not None
            checkout_pending = session.scalar(select(BillingCheckout.id).where(BillingCheckout.account_id == account_id, BillingCheckout.status.in_(["creating", "open"])).limit(1)) is not None
            return BillingRead(account_id=account_id, plan=active_plan(account), subscription_status=account.status if account else "none", period_start=account.period_start if account else None, period_end=account.period_end if account else None, cancel_at_period_end=bool(account and account.cancel_at_period_end), last_synced_at=account.last_synced_at if account else None, checkout_enabled=self.gateway.ready, portal_enabled=bool(self.gateway.ready and account and account.customer_id), sync_pending=pending, checkout_pending=checkout_pending)

    def _checkout_remote(self, attempt: BillingCheckout, account: BillingAccount) -> dict[str, Any]:
        remote = self.gateway.retrieve_checkout(cast(str, attempt.session_id))
        if remote.get("customer") != account.customer_id or remote.get("client_reference_id") != str(account.account_id) or remote.get("livemode") is not self.settings.stripe_live_mode or remote.get("mode") != "subscription" or remote.get("metadata", {}).get("dwellcall_account_id") != str(account.account_id) or remote.get("metadata", {}).get("plan") != attempt.plan:
            raise billing_error(409, "checkout_identity_invalid", "The checkout identity needs owner review.")
        return remote

    def create_checkout(self, account_id: UUID, email: str, plan: PlanKey, request_id: UUID) -> str:
        self._ready()
        if plan not in {"pro", "team"}:
            raise billing_error(422, "invalid_checkout_plan", "Choose Pro or Team for checkout.")
        self._ensure_customer(account_id, email)
        with self.sessions() as session:
            account = self._account(session, account_id)
            subscriptions = self._reconcile(session, account)
            if any(item.get("status") not in TERMINAL_SUBSCRIPTIONS for item in subscriptions):
                session.commit()
                raise billing_error(409, "subscription_exists", "Manage your existing subscription in the billing portal.")
            existing = session.get(BillingCheckout, request_id)
            if existing and (existing.account_id != account_id or existing.plan != plan):
                raise billing_error(409, "checkout_request_conflict", "This checkout request does not match.")
            attempts = list(session.scalars(select(BillingCheckout).where(BillingCheckout.account_id == account_id, BillingCheckout.status.in_(["creating", "open"])).order_by(BillingCheckout.created_at).limit(51)))
            if len(attempts) > 50:
                raise billing_error(409, "billing_history_review", "Checkout history needs owner review.")
            chosen = None
            for attempt in attempts:
                if attempt.session_id:
                    remote = self._checkout_remote(attempt, account)
                    status = remote.get("status")
                    if status == "complete":
                        terminal = any(item.get("id") == remote.get("subscription") and item.get("status") in TERMINAL_SUBSCRIPTIONS for item in subscriptions)
                        if not terminal:
                            session.commit()
                            raise billing_error(409, "checkout_pending", "Your payment is being confirmed. Refresh billing before trying again.")
                        attempt.status = "complete"
                    elif status == "expired":
                        attempt.status = "expired"
                    elif status == "open":
                        if attempt.plan == plan:
                            url = stripe_url(remote.get("url"), "checkout")
                            session.commit()
                            return url
                        self.gateway.expire_checkout(attempt.session_id)
                        attempt.status = "expired"
                    else:
                        raise billing_error(409, "checkout_pending", "Checkout status is unconfirmed. Keep this request and refresh billing.")
                elif attempt.plan == plan:
                    chosen = attempt
                else:
                    raise billing_error(409, "checkout_pending", "Another checkout is unconfirmed. Keep that request before choosing a different plan.")
            if chosen is None:
                if existing is not None:
                    session.commit()
                    raise billing_error(409, "checkout_finished", "This request has finished. Start a new checkout deliberately.")
                chosen = BillingCheckout(id=request_id, account_id=account_id, plan=plan, status="creating", created_at=datetime.now(UTC))
                session.add(chosen)
            chosen_id = chosen.id
            session.commit()
            account = self._account(session, account_id)
            chosen = session.get(BillingCheckout, chosen_id, populate_existing=True)
            if chosen is None or chosen.status not in {"creating", "open"}:
                raise billing_error(409, "checkout_finished", "Refresh your billing status before continuing.")
            if chosen.session_id:
                remote = self._checkout_remote(chosen, account)
                if remote.get("status") != "open":
                    raise billing_error(409, "checkout_pending", "Refresh billing before starting another checkout.")
                return stripe_url(remote.get("url"), "checkout")
            if datetime.now(UTC) - chosen.created_at >= REPLAY_WINDOW:
                raise billing_error(409, "checkout_unconfirmed", "This checkout is unconfirmed and cannot be recreated. The owner must reconcile it.")
            if any(item.get("status") not in TERMINAL_SUBSCRIPTIONS for item in self._reconcile(session, account)):
                session.commit()
                raise billing_error(409, "subscription_exists", "Manage your existing subscription in the billing portal.")
            result = self.gateway.checkout(cast(str, account.customer_id), plan, chosen.id, account_id)
            if not isinstance(result.get("id"), str) or not result["id"].startswith("cs_"):
                raise billing_error(502, "stripe_response_invalid", "Stripe did not provide a checkout reference.")
            chosen.session_id = result["id"]
            remote = self._checkout_remote(chosen, account)
            if remote.get("status") != "open":
                raise billing_error(409, "checkout_pending", "Checkout status is unconfirmed. Refresh billing shortly.")
            chosen.url = stripe_url(remote.get("url"), "checkout")
            chosen.expires_at = stripe_datetime(remote.get("expires_at"))
            chosen.status = "open"
            session.commit()
            return chosen.url

    def portal(self, account_id: UUID) -> str:
        self._ready()
        with self.sessions() as session:
            account = self._account(session, account_id)
            if not account.customer_id:
                raise billing_error(409, "billing_customer_missing", "Choose a paid plan first.")
            url = stripe_url(self.gateway.portal(account.customer_id), "portal")
            session.commit()
            return url

    def receive_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type not in SUBSCRIPTION_EVENTS:
            return
        data = event.get("data", {}).get("object", {})
        references = (event.get("id"), data.get("customer"), data.get("id"))
        if not all(isinstance(item, str) and 1 <= len(item) <= 128 and all(c.isascii() and (c.isalnum() or c == "_") for c in item) for item in references):
            raise billing_error(400, "stripe_event_invalid", "The event references are invalid.")
        with self.sessions() as session, session.begin():
            account = session.scalar(select(BillingAccount).where(BillingAccount.customer_id == data["customer"], BillingAccount.livemode == self.settings.stripe_live_mode))
            if account is None:
                return
            session.execute(insert(BillingEvent).values(event_id=event["id"], account_id=account.account_id, event_type=event_type, customer_id=data["customer"], object_id=data["id"]).on_conflict_do_nothing(index_elements=["event_id"]))

    def bind_customer(self, account_id: UUID, customer_id: str) -> None:
        with self.sessions() as session:
            account = self._account(session, account_id)
            if account.customer_id and account.customer_id != customer_id:
                raise billing_error(409, "billing_binding_conflict", "This account already has another customer binding.")
            with self.gateway.client() as client:
                customer = client.v1.customers.retrieve(customer_id).to_dict()
            if customer.get("deleted") or customer.get("livemode") is not self.settings.stripe_live_mode or customer.get("metadata", {}).get("dwellcall_account_id") != str(account_id):
                raise billing_error(409, "billing_binding_conflict", "The customer does not belong to this DwellCall account and Stripe mode.")
            account.customer_id = customer_id
            session.commit()

    def bind_checkout(self, request_id: UUID, session_id: str) -> None:
        with self.sessions() as session:
            initial = session.get(BillingCheckout, request_id)
            if initial is None:
                raise billing_error(404, "checkout_missing", "The reserved checkout request was not found.")
            account = self._account(session, initial.account_id)
            attempt = session.get(BillingCheckout, request_id, populate_existing=True)
            if attempt is None or attempt.session_id and attempt.session_id != session_id:
                raise billing_error(409, "billing_binding_conflict", "This request already has another checkout binding.")
            attempt.session_id = session_id
            remote = self._checkout_remote(attempt, account)
            if remote.get("status") not in {"open", "complete", "expired"}:
                raise billing_error(409, "checkout_pending", "The provider checkout status is unconfirmed.")
            attempt.url = stripe_url(remote.get("url"), "checkout") if remote.get("status") == "open" else None
            attempt.expires_at = stripe_datetime(remote.get("expires_at"))
            attempt.status = "expired" if remote.get("status") == "expired" else "open"
            session.commit()
