"""Integration tests exercising the full webhook -> agent -> escalation flow."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from incident_agent.alerts import AlertRegistry


@pytest.fixture
async def app_client(test_settings):
    """Create a test client with mocked agent and external services."""
    with patch("incident_agent.main.get_settings", return_value=test_settings):
        with patch("incident_agent.main.run_investigation", new_callable=AsyncMock) as mock_investigate:
            mock_investigate.return_value = None
            from incident_agent.main import app

            app.state.registry = AlertRegistry()
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac, mock_investigate, app.state.registry
            await app.state.registry.cancel_all()


@pytest.mark.asyncio
async def test_firing_alert_triggers_investigation(app_client, sample_firing_payload):
    client, mock_investigate, registry = app_client

    response = await client.post("/api/v1/alerts", json=sample_firing_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["investigations_started"] == 1

    # Verify the investigation was registered
    assert await registry.is_investigating("abc123")


@pytest.mark.asyncio
async def test_duplicate_fingerprint_deduped(app_client, sample_firing_payload):
    client, mock_investigate, registry = app_client

    # First alert starts investigation
    response1 = await client.post("/api/v1/alerts", json=sample_firing_payload)
    assert response1.json()["investigations_started"] == 1

    # Second alert with same fingerprint is deduped
    response2 = await client.post("/api/v1/alerts", json=sample_firing_payload)
    assert response2.json()["investigations_started"] == 0


@pytest.mark.asyncio
async def test_resolved_alert_cancels_investigation(app_client, sample_firing_payload, sample_resolved_payload):
    client, mock_investigate, registry = app_client

    # Start investigation
    await client.post("/api/v1/alerts", json=sample_firing_payload)
    assert await registry.is_investigating("abc123")

    # Resolve it
    await client.post("/api/v1/alerts", json=sample_resolved_payload)
    inv = await registry.get("abc123")
    assert inv.status == "resolved"


@pytest.mark.asyncio
async def test_concurrent_alerts_different_fingerprints(app_client):
    client, mock_investigate, registry = app_client

    payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "HighErrorRate", "severity": "warning"},
                "annotations": {"summary": "Error 1"},
                "fingerprint": "fp1",
                "startsAt": "2026-04-10T12:00:00Z",
            },
            {
                "status": "firing",
                "labels": {"alertname": "HighLatency", "severity": "critical"},
                "annotations": {"summary": "Latency spike"},
                "fingerprint": "fp2",
                "startsAt": "2026-04-10T12:01:00Z",
            },
        ],
    }

    response = await client.post("/api/v1/alerts", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["investigations_started"] == 2

    assert await registry.is_investigating("fp1")
    assert await registry.is_investigating("fp2")


@pytest.mark.asyncio
async def test_investigations_endpoint_shows_all(app_client):
    client, mock_investigate, registry = app_client

    payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "Alert1"},
                "annotations": {},
                "fingerprint": "fp1",
                "startsAt": "2026-04-10T12:00:00Z",
            },
            {
                "status": "firing",
                "labels": {"alertname": "Alert2"},
                "annotations": {},
                "fingerprint": "fp2",
                "startsAt": "2026-04-10T12:00:00Z",
            },
        ],
    }

    await client.post("/api/v1/alerts", json=payload)
    response = await client.get("/api/v1/investigations")
    assert response.status_code == 200
    investigations = response.json()
    fingerprints = {inv["fingerprint"] for inv in investigations}
    assert "fp1" in fingerprints
    assert "fp2" in fingerprints


@pytest.mark.asyncio
async def test_full_lifecycle_fire_resolve(app_client, sample_firing_payload, sample_resolved_payload):
    """Test complete lifecycle: fire -> investigate -> resolve externally."""
    client, mock_investigate, registry = app_client

    # Fire
    await client.post("/api/v1/alerts", json=sample_firing_payload)
    inv = await registry.get("abc123")
    assert inv.status == "investigating"

    # Resolve externally
    await client.post("/api/v1/alerts", json=sample_resolved_payload)
    inv = await registry.get("abc123")
    assert inv.status == "resolved"

    # Verify investigations endpoint reflects the status
    response = await client.get("/api/v1/investigations")
    data = response.json()
    abc_inv = next(i for i in data if i["fingerprint"] == "abc123")
    assert abc_inv["status"] == "resolved"
