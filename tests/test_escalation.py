from unittest.mock import AsyncMock, Mock, patch

import pytest

from incident_agent.alerts import GrafanaAlert
from incident_agent.config import Settings
from incident_agent.escalation import (
    escalate_to_pagerduty,
    map_severity,
    post_escalation_to_slack,
)


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
        "labels": {"alertname": "HighErrorRate", "severity": "warning"},
        "annotations": {"summary": "Error rate above 5%"},
        "fingerprint": "abc123",
        "startsAt": "2026-04-10T12:00:00Z",
        "generatorURL": "http://grafana.test/alert/abc123",
    }
    defaults.update(overrides)
    return GrafanaAlert(**defaults)


class TestMapSeverity:
    def test_critical(self):
        assert map_severity({"severity": "critical"}) == "critical"

    def test_warning(self):
        assert map_severity({"severity": "warning"}) == "warning"

    def test_info(self):
        assert map_severity({"severity": "info"}) == "info"

    def test_unknown_defaults_to_error(self):
        assert map_severity({"severity": "banana"}) == "error"

    def test_missing_severity_defaults_to_error(self):
        assert map_severity({}) == "error"

    def test_case_insensitive(self):
        assert map_severity({"severity": "CRITICAL"}) == "critical"


@pytest.mark.asyncio
async def test_escalate_to_pagerduty():
    settings = _make_settings()
    alert = _make_alert()

    mock_response = Mock()
    mock_response.json.return_value = {"dedup_key": "pd-123"}
    mock_response.raise_for_status = Mock()

    with patch("incident_agent.escalation.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        dedup_key = await escalate_to_pagerduty(alert, "Investigation summary here", settings)

    assert dedup_key == "pd-123"
    call_kwargs = mock_client.post.call_args
    assert call_kwargs[0][0] == "https://events.pagerduty.com/v2/enqueue"
    payload = call_kwargs[1]["json"]
    assert "HighErrorRate" in payload["payload"]["summary"]
    assert payload["payload"]["severity"] == "warning"
    assert payload["routing_key"] == "test-routing-key"


@pytest.mark.asyncio
async def test_post_escalation_to_slack():
    settings = _make_settings()
    alert = _make_alert()

    mock_response = Mock()
    mock_response.json.return_value = {"ok": True}
    mock_response.raise_for_status = Mock()

    with patch("incident_agent.escalation.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await post_escalation_to_slack(alert, "Summary text", "pd-123", settings)

    call_kwargs = mock_client.post.call_args
    assert call_kwargs[0][0] == "https://slack.com/api/chat.postMessage"
    json_body = call_kwargs[1]["json"]
    assert json_body["channel"] == "C12345"
    assert "HighErrorRate" in json_body["text"]
    assert "Summary text" in json_body["text"]
    assert "pd-123" in json_body["text"]
