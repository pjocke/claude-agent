import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from incident_agent.alerts import AlertRegistry
from incident_agent.config import Settings


def _make_settings(**overrides) -> Settings:
    defaults = {
        "anthropic_api_key": "test-key",
        "grafana_url": "http://grafana.test",
        "grafana_service_account_token": "test-token",
        "slack_bot_token": "xoxb-test",
        "slack_channel_id": "C12345",
        "pagerduty_api_key": "test-routing-key",
        "pagerduty_service_id": "PSERVICE1",
    }
    defaults.update(overrides)
    return Settings(**defaults)


SAMPLE_FIRING = {
    "status": "firing",
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "HighErrorRate", "severity": "warning"},
            "annotations": {"summary": "Error rate above 5%"},
            "fingerprint": "abc123",
            "startsAt": "2026-04-10T12:00:00Z",
            "generatorURL": "http://grafana.test/alert/abc123",
        }
    ],
}

SAMPLE_RESOLVED = {
    "status": "resolved",
    "alerts": [
        {
            "status": "resolved",
            "labels": {"alertname": "HighErrorRate"},
            "annotations": {},
            "fingerprint": "abc123",
            "startsAt": "2026-04-10T12:00:00Z",
        }
    ],
}


@pytest.fixture
def settings():
    return _make_settings()


@pytest.fixture
async def client(settings):
    with patch("incident_agent.main.get_settings", return_value=settings):
        with patch("incident_agent.main.run_investigation", new_callable=AsyncMock) as mock_investigate:
            mock_investigate.return_value = None
            from incident_agent.main import app

            # Manually set up state since ASGITransport doesn't trigger lifespan
            app.state.registry = AlertRegistry()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac

            # Cleanup
            await app.state.registry.cancel_all()


@pytest.mark.asyncio
async def test_healthz(client):
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_firing_alert_starts_investigation(client):
    response = await client.post("/api/v1/alerts", json=SAMPLE_FIRING)
    assert response.status_code == 200
    data = response.json()
    assert data["investigations_started"] == 1


@pytest.mark.asyncio
async def test_duplicate_alert_is_deduped(client):
    await client.post("/api/v1/alerts", json=SAMPLE_FIRING)
    response = await client.post("/api/v1/alerts", json=SAMPLE_FIRING)
    data = response.json()
    assert data["investigations_started"] == 0


@pytest.mark.asyncio
async def test_resolved_alert_resolves_investigation(client):
    await client.post("/api/v1/alerts", json=SAMPLE_FIRING)
    response = await client.post("/api/v1/alerts", json=SAMPLE_RESOLVED)
    assert response.status_code == 200

    inv_response = await client.get("/api/v1/investigations")
    investigations = inv_response.json()
    resolved = [i for i in investigations if i["fingerprint"] == "abc123"]
    assert len(resolved) == 1
    assert resolved[0]["status"] == "resolved"


@pytest.mark.asyncio
async def test_resolved_unknown_fingerprint_is_noop(client):
    response = await client.post("/api/v1/alerts", json=SAMPLE_RESOLVED)
    assert response.status_code == 200
    data = response.json()
    assert data["investigations_started"] == 0


@pytest.mark.asyncio
async def test_investigations_endpoint(client):
    await client.post("/api/v1/alerts", json=SAMPLE_FIRING)
    response = await client.get("/api/v1/investigations")
    assert response.status_code == 200
    investigations = response.json()
    assert len(investigations) >= 1
    assert investigations[0]["fingerprint"] == "abc123"
    assert investigations[0]["alert_name"] == "HighErrorRate"
