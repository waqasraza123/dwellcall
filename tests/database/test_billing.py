import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from dwellcall.billing.catalog import STRIPE_PRODUCT_ID
from dwellcall.billing.gateway import StripeGateway
from dwellcall.billing.service import BillingService
from dwellcall.database.models.account import Account
from dwellcall.database.models.billing import BillingAccount, BillingCheckout, BillingEvent
from dwellcall.errors import ApiError


def prepare(sessions, settings):
    account_id = uuid4()
    with sessions() as session, session.begin():
        session.add(Account(id=account_id, full_name="Synthetic owner", email="demo@example.com", password_hash="unusable", operator_access=True, created_at=datetime.now(UTC)))
    configuration = settings.model_copy(update={"stripe_pro_price_id": "price_pro", "stripe_team_price_id": "price_team"})
    gateway = Mock(spec=StripeGateway)
    gateway.ready = True
    gateway.create_customer.return_value = {"id": "cus_synthetic", "livemode": False, "metadata": {"dwellcall_account_id": str(account_id)}}
    gateway.subscriptions.return_value = []
    remote = {"id": "cs_synthetic", "customer": "cus_synthetic", "livemode": False, "mode": "subscription", "client_reference_id": str(account_id), "metadata": {"dwellcall_account_id": str(account_id), "plan": "pro"}, "status": "open", "url": "https://checkout.stripe.com/synthetic", "expires_at": int((datetime.now(UTC) + timedelta(hours=24)).timestamp())}
    gateway.checkout.return_value = remote
    gateway.retrieve_checkout.return_value = remote
    return account_id, gateway, BillingService(sessions, configuration, gateway)


def paid_subscription(account_id, *, status="active", price="price_pro"):
    now = datetime.now(UTC)
    return {"id": "sub_synthetic", "customer": "cus_synthetic", "livemode": False, "metadata": {"dwellcall_account_id": str(account_id)}, "status": status, "items": {"data": [{"quantity": 1, "current_period_start": int((now - timedelta(days=1)).timestamp()), "current_period_end": int((now + timedelta(days=29)).timestamp()), "price": {"id": price, "product": STRIPE_PRODUCT_ID, "currency": "usd", "unit_amount": 2900, "recurring": {"interval": "month", "interval_count": 1}}}]}, "latest_invoice": {"status": "paid", "customer": "cus_synthetic"}}


def test_concurrent_checkout_requests_share_one_durable_attempt(sessions, settings) -> None:
    account_id, gateway, service = prepare(sessions, settings)
    barrier = threading.Barrier(2)
    def checkout(_):
        barrier.wait(timeout=5)
        return service.create_checkout(account_id, "demo@example.com", "pro", uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        urls = list(pool.map(checkout, range(2)))
    assert urls == ["https://checkout.stripe.com/synthetic"] * 2
    gateway.checkout.assert_called_once()
    gateway.create_customer.assert_called_once()
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(BillingCheckout)) == 1


def test_unknown_checkout_reserves_identity_and_cannot_be_recreated_after_replay_window(sessions, settings) -> None:
    account_id, gateway, service = prepare(sessions, settings)
    request_id = uuid4()
    gateway.checkout.side_effect = ApiError(status_code=502, code="STRIPE_UNAVAILABLE", message="Synthetic timeout")
    with pytest.raises(ApiError):
        service.create_checkout(account_id, "demo@example.com", "pro", request_id)
    with sessions() as session, session.begin():
        attempt = session.get(BillingCheckout, request_id)
        assert attempt.status == "creating"
        attempt.created_at = datetime.now(UTC) - timedelta(hours=24)
    gateway.checkout.reset_mock()
    with pytest.raises(ApiError) as denied:
        service.create_checkout(account_id, "demo@example.com", "pro", uuid4())
    assert denied.value.code == "CHECKOUT_UNCONFIRMED"
    gateway.checkout.assert_not_called()


def test_webhook_replays_and_reordered_events_reconcile_current_subscription(sessions, settings) -> None:
    account_id, gateway, service = prepare(sessions, settings)
    service.create_checkout(account_id, "demo@example.com", "pro", uuid4())
    gateway.subscriptions.return_value = [paid_subscription(account_id)]
    event = {"id": "evt_old", "type": "customer.subscription.deleted", "data": {"object": {"id": "sub_synthetic", "customer": "cus_synthetic"}}}
    service.receive_event(event)
    service.receive_event(event)
    assert service.summary(account_id).sync_pending
    assert service.refresh(account_id).plan == "pro"
    assert not service.summary(account_id).sync_pending
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(BillingEvent)) == 1
    gateway.subscriptions.return_value = [paid_subscription(account_id, status="past_due")]
    assert service.refresh(account_id).plan == "free"
    gateway.subscriptions.return_value = [paid_subscription(account_id, price="price_unknown")]
    assert service.refresh(account_id).subscription_status == "needs_review"


def test_multiple_subscriptions_and_mode_mismatch_block_new_checkout(sessions, settings) -> None:
    account_id, gateway, service = prepare(sessions, settings)
    service.create_checkout(account_id, "demo@example.com", "pro", uuid4())
    gateway.subscriptions.return_value = [paid_subscription(account_id), {**paid_subscription(account_id), "id": "sub_second"}]
    assert service.refresh(account_id).plan == "free"
    with pytest.raises(ApiError) as denied:
        service.create_checkout(account_id, "demo@example.com", "team", uuid4())
    assert denied.value.code == "SUBSCRIPTION_EXISTS"
    with sessions() as session, session.begin():
        session.get(BillingAccount, account_id).livemode = True
    with pytest.raises(ApiError) as denied:
        service.summary(account_id)
    assert denied.value.code == "BILLING_MODE_MISMATCH"


def test_complete_checkout_waits_for_subscription_and_foreign_request_cannot_rebind(sessions, settings) -> None:
    account_id, gateway, service = prepare(sessions, settings)
    request_id = uuid4()
    service.create_checkout(account_id, "demo@example.com", "pro", request_id)
    gateway.retrieve_checkout.return_value = {**gateway.retrieve_checkout.return_value, "status": "complete", "subscription": "sub_synthetic"}
    with pytest.raises(ApiError) as denied:
        service.create_checkout(account_id, "demo@example.com", "pro", uuid4())
    assert denied.value.code == "CHECKOUT_PENDING"
    gateway.checkout.assert_called_once()
    gateway.retrieve_checkout.return_value = {**gateway.retrieve_checkout.return_value, "customer": "cus_foreign"}
    with pytest.raises(ApiError):
        service.bind_checkout(request_id, "cs_foreign")
    with sessions() as session:
        assert session.get(BillingCheckout, request_id).session_id == "cs_synthetic"
