from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import stripe

from dwellcall.billing.catalog import PLANS
from dwellcall.billing.cli import setup_catalog
from dwellcall.billing.gateway import StripeGateway


@pytest.fixture
def catalog_client(settings, monkeypatch):
    client = Mock()
    client.v1.products.retrieve.return_value = SimpleNamespace(id=settings.stripe_product_id, active=True, livemode=False)
    configurations = client.v1.billing_portal.configurations
    configurations.list.return_value.auto_paging_iter.return_value = iter(())
    configurations.create.side_effect = lambda data, **options: SimpleNamespace(id=f"bpc_{data['metadata']['dwellcall_audience']}")
    monkeypatch.setattr(StripeGateway, "client", lambda self, **options: nullcontext(client))
    return client


def synthetic_price(plan, product):
    return SimpleNamespace(
        id=f"price_{plan}", product=product, livemode=False, active=True,
        currency="usd", unit_amount=PLANS[plan].amount,
        recurring=SimpleNamespace(interval="month", interval_count=1),
    )


def test_setup_reuses_manual_product_and_configured_prices_without_lookup_keys(settings, catalog_client) -> None:
    configuration = settings.model_copy(update={
        "stripe_product_id": "prod_synthetic", "stripe_pro_price_id": "price_pro", "stripe_team_price_id": "price_team",
    })
    catalog_client.v1.products.retrieve.return_value.id = configuration.stripe_product_id
    catalog_client.v1.prices.retrieve.side_effect = lambda identifier: synthetic_price(identifier.removeprefix("price_"), configuration.stripe_product_id)
    result = setup_catalog(configuration)
    catalog_client.v1.products.retrieve.assert_called_once_with("prod_synthetic")
    assert result["STRIPE_PRO_PRICE_ID"] == "price_pro"
    assert result["STRIPE_TEAM_PRICE_ID"] == "price_team"
    catalog_client.v1.products.create.assert_not_called()
    catalog_client.v1.prices.list.assert_not_called()
    catalog_client.v1.prices.create.assert_not_called()
    assert catalog_client.v1.billing_portal.configurations.create.call_count == 3


def test_setup_retains_default_product_creation_and_managed_price_lookup(settings, catalog_client) -> None:
    catalog_client.v1.products.retrieve.side_effect = stripe.InvalidRequestError("Missing product", "id", http_status=404)
    catalog_client.v1.products.create.return_value = SimpleNamespace(id=settings.stripe_product_id, active=True, livemode=False)
    catalog_client.v1.prices.list.side_effect = lambda data: SimpleNamespace(data=[synthetic_price("pro" if "pro" in data["lookup_keys"][0] else "team", settings.stripe_product_id)])
    assert setup_catalog(settings)["STRIPE_PRO_PRICE_ID"] == "price_pro"
    assert catalog_client.v1.products.create.call_args.args[0]["id"] == "dwellcall_subscription_v1"
    catalog_client.v1.prices.create.assert_not_called()


def test_missing_generated_product_does_not_create_replacement(settings, catalog_client) -> None:
    configuration = settings.model_copy(update={"stripe_product_id": "prod_missing"})
    catalog_client.v1.products.retrieve.side_effect = stripe.InvalidRequestError("Missing product", "id", http_status=404)
    with pytest.raises(RuntimeError, match="STRIPE_PRODUCT_ID"):
        setup_catalog(configuration)
    catalog_client.v1.products.create.assert_not_called()
    catalog_client.v1.prices.create.assert_not_called()
    catalog_client.v1.billing_portal.configurations.create.assert_not_called()


@pytest.mark.parametrize("mismatch", ["product", "livemode", "unit_amount"])
def test_incompatible_configured_price_fails_without_creation(settings, catalog_client, mismatch) -> None:
    configuration = settings.model_copy(update={"stripe_pro_price_id": "price_pro"})
    price = synthetic_price("pro", settings.stripe_product_id)
    setattr(price, mismatch, {"product": "prod_other", "livemode": True, "unit_amount": 1}[mismatch])
    catalog_client.v1.prices.retrieve.return_value = price
    with pytest.raises(RuntimeError, match="agreed catalog"):
        setup_catalog(configuration)
    catalog_client.v1.products.create.assert_not_called()
    catalog_client.v1.prices.create.assert_not_called()
    catalog_client.v1.prices.update.assert_not_called()
    catalog_client.v1.billing_portal.configurations.create.assert_not_called()
