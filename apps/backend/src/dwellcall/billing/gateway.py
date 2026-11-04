from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import stripe

from dwellcall.settings import ApiSettings
from dwellcall.billing.errors import billing_error as AppError
from dwellcall.billing.catalog import PLANS, STRIPE_PRODUCT_ID, PlanKey

type StripeData = dict[str, Any]


class StripeGateway:
    def __init__(self, settings: ApiSettings) -> None:
        self.settings = settings

    @property
    def ready(self) -> bool:
        return bool(
            self.settings.billing_enabled and self.settings.stripe_secret_key
            and self.settings.stripe_webhook_secret
            and self.settings.stripe_pro_price_id and self.settings.stripe_team_price_id
            and self.settings.stripe_portal_configuration_id
            and self.settings.stripe_portal_pro_configuration_id
            and self.settings.stripe_portal_team_configuration_id
        )

    def price(self, plan: PlanKey) -> str:
        value = {
            "pro": self.settings.stripe_pro_price_id,
            "team": self.settings.stripe_team_price_id,
        }.get(plan)
        if value is None or not value.startswith("price_"):
            raise AppError(503, "billing_unavailable", "Subscription checkout is not available yet.")
        return value

    @contextmanager
    def client(self, *, translate_errors: bool = True) -> Iterator[stripe.StripeClient]:
        key = self.settings.stripe_secret_key
        if key is None:
            raise AppError(503, "billing_unavailable", "Billing is not configured.")
        if key.get_secret_value().startswith("sk_live_") != self.settings.stripe_live_mode:
            raise AppError(503, "billing_mode_mismatch", "Billing configuration is inconsistent.")
        transport = stripe.RequestsClient(timeout=10.0)
        try:
            yield stripe.StripeClient(
                key.get_secret_value(), http_client=transport, max_network_retries=1, stripe_version="2026-10-28.endive",
            )
        except stripe.StripeError as error:
            if not translate_errors:
                raise
            raise AppError(502, "stripe_unavailable", "Stripe is unavailable. Please try again.") from error
        finally:
            transport.close()

    def create_customer(self, account_id: UUID, email: str) -> StripeData:
        with self.client() as client:
            result = client.v1.customers.create(
                {"email": email, "metadata": {"dwellcall_account_id": str(account_id)}},
                options={"idempotency_key": f"dwellcall:customer:{account_id}"},
            )
            return result.to_dict()

    def subscriptions(self, customer_id: str) -> list[StripeData]:
        with self.client() as client:
            result = client.v1.subscriptions.list({
                "customer": customer_id, "status": "all", "limit": 100,
                "expand": ["data.latest_invoice"],
            })
            subscriptions: list[StripeData] = []
            for value in result.auto_paging_iter():
                if len(subscriptions) >= 100:
                    raise AppError(409, "billing_history_review", "Billing history needs support review.")
                subscriptions.append(value.to_dict())
            return subscriptions

    def checkout(self, customer_id: str, plan: PlanKey, request_id: UUID,
                       account_id: UUID) -> StripeData:
        origin = self.settings.web_origin.rstrip("/")
        with self.client() as client:
            price = client.v1.prices.retrieve(self.price(plan))
            if price.livemode is not self.settings.stripe_live_mode or not price.active or price.product != STRIPE_PRODUCT_ID or price.currency != "usd" or (
                price.unit_amount != PLANS[plan].amount or price.recurring is None
                or price.recurring.interval != "month" or price.recurring.interval_count != 1
            ):
                raise AppError(503, "billing_price_mismatch", "The configured subscription price needs review.")
            result = client.v1.checkout.sessions.create({
                "mode": "subscription", "customer": customer_id,
                "client_reference_id": str(account_id),
                "line_items": [{"price": self.price(plan), "quantity": 1}],
                "adaptive_pricing": {"enabled": False},
                "subscription_data": {"metadata": {"dwellcall_account_id": str(account_id)}},
                "metadata": {"dwellcall_account_id": str(account_id), "plan": plan},
                "success_url": f"{origin}/billing?checkout=success",
                "cancel_url": f"{origin}/billing?checkout=canceled",
            }, options={"idempotency_key": f"dwellcall:checkout:{account_id}:{request_id}"})
            return result.to_dict()

    def retrieve_checkout(self, session_id: str) -> StripeData:
        with self.client() as client:
            result = client.v1.checkout.sessions.retrieve(session_id)
            return result.to_dict()

    def expire_checkout(self, session_id: str) -> None:
        with self.client() as client:
            client.v1.checkout.sessions.expire(session_id)

    def portal(self, customer_id: str) -> str:
        configuration = self.settings.stripe_portal_configuration_id
        subscriptions = [item for item in self.subscriptions(customer_id)
                         if item.get("status") not in {"canceled", "incomplete_expired"}]
        if len(subscriptions) == 1:
            items = subscriptions[0].get("items", {}).get("data", [])
            if len(items) == 1 and items[0].get("quantity", 1) == 1:
                price_id = items[0].get("price", {}).get("id")
                if price_id and price_id == self.settings.stripe_pro_price_id:
                    configuration = self.settings.stripe_portal_pro_configuration_id
                elif price_id and price_id == self.settings.stripe_team_price_id:
                    configuration = self.settings.stripe_portal_team_configuration_id
        if configuration is None:
            raise AppError(503, "billing_unavailable", "Billing management is unavailable.")
        with self.client() as client:
            result = client.v1.billing_portal.sessions.create({
                "customer": customer_id, "configuration": configuration,
                "return_url": f"{self.settings.web_origin.rstrip('/')}/billing",
            })
            if not result.url:
                raise AppError(502, "stripe_unavailable", "Stripe did not provide a billing portal URL.")
            return result.url

    def verify_event(self, body: bytes, signature: str) -> StripeData:
        secret = self.settings.stripe_webhook_secret
        if secret is None:
            raise AppError(503, "billing_unavailable", "Billing is not configured.")
        try:
            event = stripe.Webhook.construct_event(body, signature, secret.get_secret_value())
        except (ValueError, stripe.SignatureVerificationError) as error:
            raise AppError(400, "invalid_stripe_signature", "Invalid webhook signature.") from error
        if bool(event.livemode) != self.settings.stripe_live_mode:
            raise AppError(400, "billing_mode_mismatch", "Webhook mode does not match.")
        return event.to_dict()
