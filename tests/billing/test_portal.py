from types import SimpleNamespace
from unittest.mock import Mock

from dwellcall.billing.catalog import STRIPE_PRODUCT_ID
from dwellcall.billing.gateway import StripeGateway
from dwellcall.billing.portal import setup_portal_configurations


def test_portal_upgrade_and_downgrade_catalogs_are_independent_and_reused(settings) -> None:
    client = Mock()
    configurations = client.v1.billing_portal.configurations
    stored = []
    configurations.list.return_value.auto_paging_iter.side_effect = lambda: iter(stored)
    def create(parameters, **options):
        result = SimpleNamespace(id=f"bpc_{parameters['metadata']['dwellcall_audience']}", metadata=parameters["metadata"])
        stored.append(result)
        return result
    configurations.create.side_effect = create
    configurations.update.side_effect = lambda identifier, parameters: SimpleNamespace(id=identifier)
    prices = {"pro": "price_pro", "team": "price_team"}
    first = setup_portal_configurations(client, settings, prices)
    assert first == {"STRIPE_PORTAL_CONFIGURATION_ID": "bpc_management", "STRIPE_PORTAL_PRO_CONFIGURATION_ID": "bpc_pro", "STRIPE_PORTAL_TEAM_CONFIGURATION_ID": "bpc_team"}
    for call in configurations.create.call_args_list:
        data = call.args[0]
        audience = data["metadata"]["dwellcall_audience"]
        assert data["features"]["subscription_cancel"] == {"enabled": True, "mode": "at_period_end"}
        changes = data["features"]["subscription_update"]
        if audience == "management":
            assert changes == {"enabled": False}
        else:
            target = "price_team" if audience == "pro" else "price_pro"
            assert changes["products"] == [{"product": STRIPE_PRODUCT_ID, "prices": [target]}]
            assert changes["proration_behavior"] == "always_invoice"
            assert changes["schedule_at_period_end"] == {"conditions": [{"type": "decreasing_item_amount"}]}
    assert setup_portal_configurations(client, settings, prices) == first
    assert configurations.create.call_count == 3
    assert configurations.update.call_count == 3


def test_portal_target_uses_current_stripe_subscription_price(settings, monkeypatch) -> None:
    configuration = settings.model_copy(update={"stripe_pro_price_id": "price_pro", "stripe_team_price_id": "price_team", "stripe_portal_configuration_id": "bpc_management", "stripe_portal_pro_configuration_id": "bpc_pro", "stripe_portal_team_configuration_id": "bpc_team"})
    gateway = StripeGateway(configuration)
    client = Mock()
    client.v1.billing_portal.sessions.create.return_value.url = "https://billing.stripe.com/synthetic"
    context = Mock()
    context.__enter__ = Mock(return_value=client)
    context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(gateway, "client", lambda: context)
    for price, expected in [("price_pro", "bpc_pro"), ("price_team", "bpc_team"), ("price_unknown", "bpc_management")]:
        monkeypatch.setattr(gateway, "subscriptions", lambda customer: [{"status": "active", "items": {"data": [{"quantity": 1, "price": {"id": price}}]}}])
        assert gateway.portal("cus_synthetic") == "https://billing.stripe.com/synthetic"
        assert client.v1.billing_portal.sessions.create.call_args.args[0]["configuration"] == expected
