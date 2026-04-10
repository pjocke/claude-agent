import pytest

from incident_agent.alerts import GrafanaAlert, GrafanaWebhookPayload
from incident_agent.config import Settings


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        anthropic_api_key="test-key",
        grafana_url="http://grafana.test",
        grafana_service_account_token="test-token",
        slack_bot_token="xoxb-test",
        slack_channel_id="C12345",
        pagerduty_api_key="test-routing-key",
        pagerduty_service_id="PSERVICE1",
        max_agent_turns=10,
    )


@pytest.fixture
def sample_firing_payload() -> dict:
    return {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "HighErrorRate",
                    "severity": "warning",
                    "namespace": "default",
                    "service": "api-gateway",
                },
                "annotations": {
                    "summary": "Error rate above 5% for api-gateway",
                    "description": "The error rate for api-gateway has exceeded 5% for the last 5 minutes.",
                },
                "fingerprint": "abc123",
                "startsAt": "2026-04-10T12:00:00Z",
                "generatorURL": "http://grafana.test/alerting/abc123/view",
            }
        ],
    }


@pytest.fixture
def sample_resolved_payload() -> dict:
    return {
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
def sample_alert() -> GrafanaAlert:
    return GrafanaAlert(
        status="firing",
        labels={
            "alertname": "HighErrorRate",
            "severity": "warning",
            "namespace": "default",
            "service": "api-gateway",
        },
        annotations={"summary": "Error rate above 5% for api-gateway"},
        fingerprint="abc123",
        startsAt="2026-04-10T12:00:00Z",
        generatorURL="http://grafana.test/alerting/abc123/view",
    )
