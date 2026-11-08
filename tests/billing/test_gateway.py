import hashlib
import hmac
import json
import time
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from dwellcall.billing.catalog import PLANS
from dwellcall.billing.gateway import StripeGateway
from dwellcall.billing.service import stripe_url
from dwellcall.billing.state import active_plan, apply_subscription
from dwellcall.database.models.billing import BillingAccount
from dwellcall.errors import ApiError
from dwellcall.settings import ApiSettings


def test_catalog_and_activation_configuration(settings: ApiSettings) -> None:
    assert {key: plan.amount for key, plan in PLANS.items()} == {"free": 0, "pro": 2900, "team": 7900}
    assert not StripeGateway(settings).ready
    with pytest.raises(ValidationError):
        ApiSettings.model_validate({**settings.model_dump(), "billing_enabled": True})
    with pytest.raises(ValidationError):
        ApiSettings.model_validate({**settings.model_dump(), "stripe_secret_key": "sk_live_synthetic", "stripe_live_mode": False})
    with pytest.raises(ValidationError):
        ApiSettings.model_validate({**settings.model_dump(), "stripe_pro_price_id": "price_same", "stripe_team_price_id": "price_same"})


def test_product_id_default_and_environment_override(settings, monkeypatch, tmp_path) -> None:
    values = settings.model_dump(exclude={"stripe_product_id"})
    assert ApiSettings(**values).stripe_product_id == "dwellcall_subscription_v1"
    environment = tmp_path / ".env"
    environment.write_text("STRIPE_PRODUCT_ID=prod_synthetic\n")
    assert ApiSettings(_env_file=environment, **values).stripe_product_id == "prod_synthetic"
    monkeypatch.setenv("STRIPE_PRODUCT_ID", "prod_environment")
    assert ApiSettings(**values).stripe_product_id == "prod_environment"


@pytest.mark.parametrize("product_id", ["", " ", "prod_invalid/value"])
def test_invalid_product_id_is_rejected(settings, product_id) -> None:
    with pytest.raises(ValidationError):
        ApiSettings.model_validate({**settings.model_dump(), "stripe_product_id": product_id})


@pytest.mark.parametrize("product_id", ["dwellcall_subscription_v1", "prod_synthetic"])
@pytest.mark.parametrize("mismatch", [None, "product", "livemode"])
def test_checkout_validates_configured_product_and_mode(settings, monkeypatch, product_id, mismatch) -> None:
    gateway = StripeGateway(settings.model_copy(update={"stripe_product_id": product_id, "stripe_pro_price_id": "price_pro"}))
    client = Mock()
    client.v1.prices.retrieve.return_value = SimpleNamespace(
        product="prod_other" if mismatch == "product" else product_id,
        livemode=mismatch == "livemode", active=True, currency="usd", unit_amount=2900,
        recurring=SimpleNamespace(interval="month", interval_count=1),
    )
    client.v1.checkout.sessions.create.return_value.to_dict.return_value = {"id": "cs_synthetic"}
    monkeypatch.setattr(gateway, "client", lambda: nullcontext(client))
    if mismatch:
        with pytest.raises(ApiError) as denied:
            gateway.checkout("cus_synthetic", "pro", uuid4(), uuid4())
        assert denied.value.code == "BILLING_PRICE_MISMATCH"
        client.v1.checkout.sessions.create.assert_not_called()
    else:
        assert gateway.checkout("cus_synthetic", "pro", uuid4(), uuid4()) == {"id": "cs_synthetic"}


@pytest.mark.parametrize("mismatch", [None, "product", "livemode"])
def test_reconciliation_uses_configured_product_and_preserves_mode_boundary(settings, mismatch) -> None:
    configuration = settings.model_copy(update={"stripe_product_id": "prod_synthetic", "stripe_pro_price_id": "price_pro"})
    account = BillingAccount(account_id=uuid4(), customer_id="cus_synthetic", livemode=False)
    now = datetime.now(UTC)
    data = {
        "id": "sub_synthetic", "customer": "cus_synthetic", "livemode": mismatch == "livemode",
        "status": "active", "metadata": {"dwellcall_account_id": str(account.account_id)},
        "items": {"data": [{
            "quantity": 1, "current_period_start": int((now - timedelta(days=1)).timestamp()),
            "current_period_end": int((now + timedelta(days=29)).timestamp()),
            "price": {"id": "price_pro", "product": "prod_other" if mismatch == "product" else "prod_synthetic",
                      "currency": "usd", "unit_amount": 2900, "recurring": {"interval": "month", "interval_count": 1}},
        }]},
        "latest_invoice": {"status": "paid", "customer": "cus_synthetic"},
    }
    apply_subscription(account, data, configuration)
    assert active_plan(account) == ("free" if mismatch else "pro")
    if mismatch:
        assert account.status == "needs_review"


def test_webhook_signature_and_test_live_boundary(settings: ApiSettings) -> None:
    secret = "whsec_synthetic_signature_specification"
    gateway = StripeGateway(settings.model_copy(update={"stripe_webhook_secret": SecretStr(secret)}))
    timestamp = int(time.time())
    body = json.dumps({"id": "evt_synthetic", "object": "event", "type": "invoice.paid", "livemode": False, "data": {"object": {"id": "in_synthetic", "customer": "cus_synthetic"}}}).encode()
    digest = hmac.new(secret.encode(), str(timestamp).encode() + b"." + body, hashlib.sha256).hexdigest()
    signature = f"t={timestamp},v1={digest}"
    assert gateway.verify_event(body, signature)["id"] == "evt_synthetic"
    with pytest.raises(ApiError):
        gateway.verify_event(body + b" ", signature)
    gateway.settings = gateway.settings.model_copy(update={"stripe_live_mode": True})
    with pytest.raises(ApiError) as denied:
        gateway.verify_event(body, signature)
    assert denied.value.code == "BILLING_MODE_MISMATCH"


@pytest.mark.parametrize("value", ["http://checkout.stripe.com/test", "https://checkout.stripe.com.evil.test/test", "https://checkout.stripe.com@evil.test/test", "https://checkout.stripe.com:abc/test", "javascript:alert(1)"])
def test_redirects_cannot_leave_stripe(value: str) -> None:
    with pytest.raises(ApiError):
        stripe_url(value, "checkout")


def test_unrecognized_subscription_clears_previous_plan(settings: ApiSettings) -> None:
    account = BillingAccount(account_id=uuid4(), customer_id="cus_synthetic", livemode=False, plan="team", status="active", price_id="price_old")
    apply_subscription(account, {"id": "sub_synthetic", "customer": "cus_synthetic", "livemode": False, "status": "active", "metadata": {"dwellcall_account_id": str(account.account_id)}, "items": {"data": [{"quantity": 1, "price": {"id": "price_unknown"}}]}}, settings)
    assert active_plan(account) == "free"
    assert account.plan == "free"
    assert account.price_id is None
