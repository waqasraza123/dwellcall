import hashlib
import hmac
import json
import time
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
