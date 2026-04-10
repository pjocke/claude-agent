import asyncio

import pytest

from incident_agent.alerts import (
    AlertRegistry,
    GrafanaAlert,
    GrafanaWebhookPayload,
)

SAMPLE_WEBHOOK = {
    "status": "firing",
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "HighErrorRate", "severity": "warning", "namespace": "default"},
            "annotations": {"summary": "Error rate above 5%"},
            "fingerprint": "abc123",
            "startsAt": "2026-04-10T12:00:00Z",
            "generatorURL": "http://grafana.example.com/alerting/abc123/view",
        }
    ],
}


def test_parse_webhook_payload():
    payload = GrafanaWebhookPayload(**SAMPLE_WEBHOOK)
    assert payload.status == "firing"
    assert len(payload.alerts) == 1
    alert = payload.alerts[0]
    assert alert.fingerprint == "abc123"
    assert alert.labels["alertname"] == "HighErrorRate"
    assert alert.status == "firing"


def test_parse_resolved_alert():
    data = {
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
    payload = GrafanaWebhookPayload(**data)
    assert payload.alerts[0].status == "resolved"


@pytest.fixture
def registry():
    return AlertRegistry()


@pytest.mark.asyncio
async def test_register_and_is_investigating(registry):
    task = asyncio.create_task(asyncio.sleep(100))
    try:
        await registry.register("fp1", {"test": True}, task)
        assert await registry.is_investigating("fp1") is True
        assert await registry.is_investigating("fp_unknown") is False
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_resolve_cancels_task(registry):
    task = asyncio.create_task(asyncio.sleep(100))
    await registry.register("fp1", {}, task)

    await registry.resolve("fp1", summary="Issue resolved")

    inv = await registry.get("fp1")
    assert inv.status == "resolved"
    assert inv.summary == "Issue resolved"
    # Wait for the task to finish cancellation
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_resolve_unknown_fingerprint_is_noop(registry):
    await registry.resolve("nonexistent")  # should not raise


@pytest.mark.asyncio
async def test_escalate(registry):
    task = asyncio.create_task(asyncio.sleep(100))
    try:
        await registry.register("fp1", {}, task)
        await registry.escalate("fp1", "Could not resolve")

        inv = await registry.get("fp1")
        assert inv.status == "escalated"
        assert inv.summary == "Could not resolve"
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_dedup_prevents_double_investigation(registry):
    task = asyncio.create_task(asyncio.sleep(100))
    try:
        await registry.register("fp1", {}, task)
        assert await registry.is_investigating("fp1") is True
        # A second check should still return True (caller skips)
        assert await registry.is_investigating("fp1") is True
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_remove(registry):
    task = asyncio.create_task(asyncio.sleep(0))
    await task
    await registry.register("fp1", {}, task)
    await registry.remove("fp1")
    assert await registry.get("fp1") is None
