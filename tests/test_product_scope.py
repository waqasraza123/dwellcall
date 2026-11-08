from unittest.mock import Mock

from dwellcall.application import create_app
from dwellcall.crm.settings import CrmSettings
from dwellcall.listings.settings import ListingSettings
from dwellcall.settings import ApiSettings


def test_focused_scope_keeps_calls_and_excludes_platform_routes(settings):
    configuration = ApiSettings.model_validate({**settings.model_dump(exclude={"platform_extensions_enabled"})})
    assert configuration.platform_extensions_enabled is False
    app = create_app(configuration, Mock())
    paths = {route.path for route in app.routes}
    assert "/api/v1/outbound/calls" in paths
    assert "/api/v1/outbound/calls/{call_id}/intelligence" in paths
    assert "/api/v1/outbound-demo/webhook" in paths
    assert "/api/v1/account/auth/me" in paths
    assert "/api/v1/billing/plans" not in paths
    assert "/api/v1/crm/providers" not in paths
    assert not any(path.startswith("/api/v1/intelligence/") for path in paths)
    assert not any(path.startswith("/api/v1/account/call-leads") for path in paths)
    assert not any(path.startswith("/api/v1/browser-conversations") for path in paths)


def test_explicit_extensions_restore_routes_without_activating_providers(settings):
    configuration = settings.model_copy(update={"platform_extensions_enabled": True})
    app = create_app(configuration, Mock(),
        CrmSettings(_env_file=None, app_environment="development"),
        ListingSettings(_env_file=None, app_environment="development"))
    paths = {route.path for route in app.routes}
    assert "/api/v1/billing/plans" in paths
    assert "/api/v1/crm/providers" in paths
    assert any(path.startswith("/api/v1/intelligence/") for path in paths)
    assert "/api/v1/account/call-leads/{call_id}" in paths
    assert not configuration.billing_enabled and not configuration.outbound_enabled
