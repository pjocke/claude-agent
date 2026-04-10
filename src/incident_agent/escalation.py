import logging

import httpx

from incident_agent.alerts import GrafanaAlert
from incident_agent.config import Settings

logger = logging.getLogger(__name__)

SEVERITY_MAP = {
    "critical": "critical",
    "high": "error",
    "warning": "warning",
    "info": "info",
}


def map_severity(alert_labels: dict[str, str]) -> str:
    grafana_severity = alert_labels.get("severity", "high").lower()
    return SEVERITY_MAP.get(grafana_severity, "error")


async def escalate_to_pagerduty(
    alert: GrafanaAlert,
    investigation_summary: str,
    settings: Settings,
) -> str:
    alert_name = alert.labels.get("alertname", "Unknown Alert")
    severity = map_severity(alert.labels)

    payload = {
        "routing_key": settings.pagerduty_api_key,
        "event_action": "trigger",
        "payload": {
            "summary": f"{alert_name} — Auto-investigation exhausted",
            "severity": severity,
            "source": "incident-agent",
            "custom_details": {
                "investigation_summary": investigation_summary,
                "alert_labels": alert.labels,
                "alert_annotations": alert.annotations,
                "started_at": alert.startsAt,
                "generator_url": alert.generatorURL,
            },
        },
        "links": [
            {
                "href": alert.generatorURL,
                "text": "Grafana Alert",
            },
        ],
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://events.pagerduty.com/v2/enqueue",
            json=payload,
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
        dedup_key = data.get("dedup_key", "unknown")
        logger.info("PagerDuty incident created: dedup_key=%s", dedup_key)
        return dedup_key


async def post_escalation_to_slack(
    alert: GrafanaAlert,
    investigation_summary: str,
    pagerduty_dedup_key: str,
    settings: Settings,
) -> None:
    alert_name = alert.labels.get("alertname", "Unknown Alert")

    text = (
        f":rotating_light: *Escalation: {alert_name}*\n\n"
        f"Auto-investigation could not resolve this alert after {settings.max_agent_turns} turns.\n\n"
        f"*Investigation Summary:*\n{investigation_summary}\n\n"
        f"*PagerDuty Incident:* {pagerduty_dedup_key}\n"
        f"*Grafana Alert:* {alert.generatorURL}"
    )

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
            json={
                "channel": settings.slack_channel_id,
                "text": text,
            },
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            logger.error("Slack API error: %s", data.get("error", "unknown"))
        else:
            logger.info("Escalation posted to Slack channel %s", settings.slack_channel_id)
