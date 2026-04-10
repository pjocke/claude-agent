import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from incident_agent.alerts import AlertRegistry, GrafanaAlert
from incident_agent.agent import build_system_prompt, run_investigation
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


def _make_alert(**overrides) -> GrafanaAlert:
    defaults = {
        "status": "firing",
        "labels": {"alertname": "HighErrorRate", "severity": "warning", "namespace": "default"},
        "annotations": {"summary": "Error rate above 5%"},
        "fingerprint": "abc123",
        "startsAt": "2026-04-10T12:00:00Z",
        "generatorURL": "http://grafana.test/alert/abc123",
    }
    defaults.update(overrides)
    return GrafanaAlert(**defaults)


class TestBuildSystemPrompt:
    def test_includes_role(self):
        prompt = build_system_prompt(_make_alert(), _make_settings())
        assert "incident response agent" in prompt

    def test_includes_alert_context(self):
        prompt = build_system_prompt(_make_alert(), _make_settings())
        assert "HighErrorRate" in prompt
        assert "warning" in prompt
        assert "2026-04-10T12:00:00Z" in prompt

    def test_includes_playbook(self):
        prompt = build_system_prompt(_make_alert(), _make_settings())
        assert "Observe" in prompt
        assert "Act" in prompt
        assert "Evaluate" in prompt

    def test_includes_remediation_guardrails(self):
        prompt = build_system_prompt(_make_alert(), _make_settings())
        assert "restart_pod" in prompt
        assert "scale_deployment" in prompt

    def test_includes_reporting_instructions(self):
        prompt = build_system_prompt(_make_alert(), _make_settings())
        assert "Slack" in prompt

    def test_includes_escalation_instructions(self):
        prompt = build_system_prompt(_make_alert(), _make_settings())
        assert "escalat" in prompt.lower()

    def test_includes_turn_count(self):
        settings = _make_settings(max_agent_turns=15)
        prompt = build_system_prompt(_make_alert(), settings)
        assert "15" in prompt


@pytest.mark.asyncio
async def test_run_investigation_success():
    alert = _make_alert()
    settings = _make_settings()
    registry = AlertRegistry()

    # Use a dummy completed task so resolve() doesn't cancel the test
    dummy_task = asyncio.create_task(asyncio.sleep(0))
    await dummy_task
    await registry.register("abc123", alert.model_dump(), dummy_task)

    result_msg = MagicMock()
    result_msg.is_error = False
    result_msg.subtype = "success"
    result_msg.result = "Issue resolved: restarted pod"

    async def mock_query(**kwargs):
        yield result_msg

    with patch("incident_agent.agent.query", side_effect=mock_query):
        with patch("incident_agent.agent.create_remediation_server"):
            await run_investigation(alert, registry, settings)

    inv = await registry.get("abc123")
    assert inv.status == "resolved"
    assert inv.summary == "Issue resolved: restarted pod"


@pytest.mark.asyncio
async def test_run_investigation_max_turns_escalates():
    alert = _make_alert()
    settings = _make_settings()
    registry = AlertRegistry()

    dummy_task = asyncio.create_task(asyncio.sleep(0))
    await dummy_task
    await registry.register("abc123", alert.model_dump(), dummy_task)

    result_msg = MagicMock()
    result_msg.is_error = True
    result_msg.subtype = "error_max_turns"
    result_msg.result = "Could not resolve the issue"

    async def mock_query(**kwargs):
        yield result_msg

    with patch("incident_agent.agent.query", side_effect=mock_query):
        with patch("incident_agent.agent.create_remediation_server"):
            with patch("incident_agent.agent.escalate_to_pagerduty", new_callable=AsyncMock, return_value="pd-123"):
                with patch("incident_agent.agent.post_escalation_to_slack", new_callable=AsyncMock):
                    await run_investigation(alert, registry, settings)

    inv = await registry.get("abc123")
    assert inv.status == "escalated"
    assert inv.summary == "Could not resolve the issue"


@pytest.mark.asyncio
async def test_run_investigation_cancelled():
    alert = _make_alert()
    settings = _make_settings()
    registry = AlertRegistry()

    dummy_task = asyncio.create_task(asyncio.sleep(0))
    await dummy_task
    await registry.register("abc123", alert.model_dump(), dummy_task)

    async def mock_query(**kwargs):
        raise asyncio.CancelledError()
        yield  # make it a generator

    with patch("incident_agent.agent.query", side_effect=mock_query):
        with patch("incident_agent.agent.create_remediation_server"):
            with pytest.raises(asyncio.CancelledError):
                await run_investigation(alert, registry, settings)

    inv = await registry.get("abc123")
    assert inv.status == "resolved"
    assert inv.summary == "Resolved externally"
