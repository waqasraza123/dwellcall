import asyncio
from unittest.mock import Mock, patch

from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import Engine

from dwellcall.application import create_app


def test_ghl_endpoints_require_admin_before_body_database_or_provider(settings, ghl_settings):
    engine = Mock(spec=Engine)
    app = create_app(settings, engine, ghl_settings)

    async def request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return [await client.get("/api/v1/crm/ghl/status"), await client.post("/api/v1/crm/ghl/agents/queue", content=b"untrusted"),
                    await client.post("/api/v1/crm/ghl/setup", content=b"untrusted"),
                    await client.post("/api/v1/crm/ghl/locations/provision", content=b"untrusted")]

    with patch("dwellcall.crm.agent_routes.bounded_body") as body:
        responses = asyncio.run(request())
    assert all(row.status_code == 401 for row in responses)
    body.assert_not_called()
    engine.connect.assert_not_called()


def test_disabled_ghl_status_and_workers_work_without_credentials_or_http(settings):
    app = create_app(settings, Mock(spec=Engine))

    async def request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = {"X-Admin-Token": settings.admin_token.get_secret_value()}
            return await client.get("/api/v1/crm/ghl/status", headers=headers), await client.post("/api/v1/crm/ghl/jobs/process", headers=headers)

    status, worker = asyncio.run(request())
    assert status.status_code == 200
    assert status.json()["credentials_configured"] is False
    assert worker.json()["status"] == "disabled"
    assert status.headers["Cache-Control"] == "no-store"


def test_invalid_configuration_request_does_not_echo_private_input(settings, ghl_settings):
    app = create_app(settings, Mock(spec=Engine), ghl_settings)

    async def request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/api/v1/crm/ghl/setup", headers={"X-Admin-Token": settings.admin_token.get_secret_value()},
                                     json={"evidence_reference": "private sensitive input"})

    response = asyncio.run(request())
    assert response.status_code == 422
    assert "private sensitive input" not in response.text
