from typing import Literal, cast

import stripe
from stripe.params.billing_portal import ConfigurationCreateParams, ConfigurationUpdateParams

from dwellcall.settings import ApiSettings
from dwellcall.billing.catalog import STRIPE_PRODUCT_ID

type PortalAudience = Literal["management", "pro", "team"]

PORTAL_SETTINGS: dict[PortalAudience, str] = {
    "management": "STRIPE_PORTAL_CONFIGURATION_ID",
    "pro": "STRIPE_PORTAL_PRO_CONFIGURATION_ID",
    "team": "STRIPE_PORTAL_TEAM_CONFIGURATION_ID",
}


def setup_portal_configurations(
    client: stripe.StripeClient, settings: ApiSettings, price_ids: dict[str, str],
) -> dict[str, str]:
    configurations = client.v1.billing_portal.configurations.list({"limit": 100})
    existing: dict[PortalAudience, stripe.billing_portal.Configuration] = {}
    for configuration in configurations.auto_paging_iter():
        metadata = configuration.metadata or {}
        audience = metadata.get("dwellcall_audience")
        if metadata.get("dwellcall_catalog") == "v2" and audience in PORTAL_SETTINGS:
            existing.setdefault(cast(PortalAudience, audience), configuration)
    identifiers: dict[str, str] = {}
    for audience, setting in PORTAL_SETTINGS.items():
        parameters: ConfigurationCreateParams = {
            "metadata": {"dwellcall_catalog": "v2", "dwellcall_audience": audience},
            "business_profile": {"headline": "Manage your DwellCall subscription"},
            "default_return_url": f"{settings.web_origin.rstrip('/')}/billing",
            "features": {
                "customer_update": {"enabled": True, "allowed_updates": ["email", "name", "address"]},
                "invoice_history": {"enabled": True},
                "payment_method_update": {"enabled": True},
                "subscription_cancel": {"enabled": True, "mode": "at_period_end"},
                "subscription_update": {"enabled": False},
            },
        }
        if audience != "management":
            target = "team" if audience == "pro" else "pro"
            parameters["features"]["subscription_update"] = {
                "enabled": True, "default_allowed_updates": ["price"],
                "proration_behavior": "always_invoice",
                "schedule_at_period_end": {"conditions": [{"type": "decreasing_item_amount"}]},
                "products": [{"product": STRIPE_PRODUCT_ID, "prices": [price_ids[target]]}],
            }
        configuration = existing.get(audience)
        if configuration is None:
            configuration = client.v1.billing_portal.configurations.create(
                parameters, options={"idempotency_key": f"dwellcall:catalog:portal:{audience}:v2"},
            )
        else:
            configuration = client.v1.billing_portal.configurations.update(
                configuration.id, cast(ConfigurationUpdateParams, {**parameters, "active": True}),
            )
        identifiers[setting] = configuration.id
    return identifiers
