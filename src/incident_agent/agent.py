import asyncio
import logging

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ResultMessage,
    query,
)

from incident_agent.alerts import AlertRegistry, GrafanaAlert
from incident_agent.config import Settings
from incident_agent.escalation import escalate_to_pagerduty, post_escalation_to_slack
from incident_agent.tools.registry import ALLOWED_REMEDIATION_TOOLS, create_remediation_server

logger = logging.getLogger(__name__)


def build_system_prompt(alert: GrafanaAlert, settings: Settings) -> str:
    alert_context = (
        f"Alert Name: {alert.labels.get('alertname', 'Unknown')}\n"
        f"Status: {alert.status}\n"
        f"Severity: {alert.labels.get('severity', 'unknown')}\n"
        f"Labels: {alert.labels}\n"
        f"Annotations: {alert.annotations}\n"
        f"Firing Since: {alert.startsAt}\n"
        f"Grafana URL: {alert.generatorURL}"
    )

    return f"""\
You are an incident response agent investigating a production alert. Your goal is to \
diagnose the issue, attempt safe remediations, and either resolve the alert or prepare \
a detailed summary for human escalation.

## Alert Context

{alert_context}

## Investigation Playbook

You have {settings.max_agent_turns} turns to investigate and resolve this alert.

**Turns 1-3: Observe**
- Query metrics (Prometheus) and logs (Loki) relevant to the alert labels.
- Use the alert labels (namespace, service, alertname) to target your queries directly.
- Check related dashboards and alert rule configuration.
- Do NOT exhaustively explore — focus on what the alert points to.

**Turns 4-8: Act + Evaluate**
- Based on your observations, attempt a safe remediation action.
- After each action, verify whether the alert condition has improved by re-querying metrics.
- If the first remediation doesn't work, try a different approach.
- You may attempt multiple remediation cycles.

**Turns 9-10: Final Evaluation**
- Confirm whether the issue is resolved.
- If resolved, provide a clear summary of root cause and actions taken.
- If not resolved, prepare a structured escalation summary.

## Remediation Guardrails

You may ONLY use these remediation actions:
- `restart_pod`: Restart a specific pod by name and namespace
- `scale_deployment`: Scale a deployment to a specified replica count (0-20)

Only target pods/deployments in allowed namespaces. Always verify the impact after each action.

## Reporting Instructions

Post updates to Slack at these key moments:
- When you start investigating
- When you discover significant findings
- When you attempt a remediation action
- When you verify the result of a remediation
- When you resolve the issue or prepare to escalate

## Escalation Instructions

If you cannot resolve the issue within your turn budget, your final message must include:
- A summary of what you investigated
- Key findings and observations
- Actions attempted and their results
- Current state of the relevant metrics
- Recommended next steps for the human responder
"""


async def run_investigation(
    alert: GrafanaAlert,
    registry: AlertRegistry,
    settings: Settings,
) -> None:
    fingerprint = alert.fingerprint
    alert_name = alert.labels.get("alertname", "Unknown")
    logger.info("Starting investigation for alert=%s fingerprint=%s", alert_name, fingerprint)

    system_prompt = build_system_prompt(alert, settings)

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        max_turns=settings.max_agent_turns,
        permission_mode="bypassPermissions",
        model="claude-sonnet-4-20250514",
        mcp_servers={
            "grafana": {
                "command": "mcp-grafana",
                "args": ["--disable-write"],
                "env": {
                    "GRAFANA_URL": settings.grafana_url,
                    "GRAFANA_SERVICE_ACCOUNT_TOKEN": settings.grafana_service_account_token,
                },
            },
            "slack": {
                "command": "npx",
                "args": ["-y", "@anthropic-ai/mcp-server-slack"],
                "env": {
                    "SLACK_BOT_TOKEN": settings.slack_bot_token,
                    "SLACK_CHANNEL_ID": settings.slack_channel_id,
                },
            },
            "pagerduty": {
                "command": "npx",
                "args": ["-y", "@pagerduty/mcp-server"],
                "env": {
                    "PAGERDUTY_API_KEY": settings.pagerduty_api_key,
                },
            },
            "remediation": create_remediation_server(),
        },
        allowed_tools=[
            "mcp__grafana__*",
            "mcp__slack__send_message",
            "mcp__pagerduty__*",
            *ALLOWED_REMEDIATION_TOOLS,
        ],
    )

    initial_message = (
        f"Alert '{alert_name}' is firing. "
        f"Severity: {alert.labels.get('severity', 'unknown')}. "
        f"Start by posting an investigation notice to Slack, "
        f"then query relevant metrics and logs to understand what is happening."
    )

    try:
        result_message: ResultMessage | None = None

        async for message in query(prompt=initial_message, options=options):
            if hasattr(message, "subtype") and hasattr(message, "is_error"):
                result_message = message

        if result_message is None:
            logger.error("No result message received for fingerprint=%s", fingerprint)
            return

        if result_message.is_error and result_message.subtype == "error_max_turns":
            logger.warning(
                "Investigation hit max turns for fingerprint=%s, escalating",
                fingerprint,
            )
            summary = result_message.result or "No summary available"
            try:
                dedup_key = await escalate_to_pagerduty(alert, summary, settings)
                await post_escalation_to_slack(alert, summary, dedup_key, settings)
            except Exception:
                logger.exception("Failed to escalate for fingerprint=%s", fingerprint)
            await registry.escalate(fingerprint, summary)
        else:
            summary = result_message.result or "Investigation complete"
            logger.info("Investigation resolved for fingerprint=%s", fingerprint)
            await registry.resolve(fingerprint, summary)

    except asyncio.CancelledError:
        logger.info("Investigation cancelled (resolved externally) for fingerprint=%s", fingerprint)
        await registry.resolve(fingerprint, "Resolved externally")
        raise
    except Exception:
        logger.exception("Unexpected error during investigation for fingerprint=%s", fingerprint)
        await registry.escalate(fingerprint, "Investigation failed due to unexpected error")
