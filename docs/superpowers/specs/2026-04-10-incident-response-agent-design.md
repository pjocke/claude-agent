# Incident Response Agent — Design Spec

## Overview

An autonomous incident response agent built with Python, the Claude Agent SDK, and MCP integrations. It receives Grafana alert webhooks, investigates using observability data, attempts safe remediations, and escalates to humans via PagerDuty when it cannot resolve the issue.

## Architecture

**Single-service monolith:** A FastAPI application with the Claude Agent SDK at its core. Each alert investigation is a single `query()` call that runs as an async task within the FastAPI event loop.

### Core Flow

1. Grafana alert fires -> webhook hits `POST /api/v1/alerts`
2. Alert is deduped by fingerprint — if investigation already running, skip
3. If alert status is "resolved", cancel any in-flight investigation
4. New `asyncio.Task` spawns a Claude Agent session with alert context
5. Agent runs up to 10 observe-act-evaluate turns using MCP tools
6. If resolved -> post summary to Slack, mark complete
7. If not resolved after 10 turns -> escalate to PagerDuty with investigation summary

## Agent Loop

### Turn Budget

`max_turns=10` (configurable via `MAX_AGENT_TURNS` env var).

Prompt guidance for turn allocation:
- Turns 1-3: Observe — query metrics, logs, traces, dashboards relevant to the alert. Use alert labels to target queries directly.
- Turns 4-8: Act + evaluate — attempt remediation, verify impact, iterate if needed.
- Turns 9-10: Final evaluation — confirm resolution or compile escalation summary.

This is guidance, not a hard constraint. The agent adapts based on what it finds.

### System Prompt Structure

The agent receives a system prompt composed of:

1. **Role definition**: "You are an incident response agent investigating a production alert."
2. **Alert context**: Full Grafana alert payload (labels, annotations, severity, dashboard URL, firing time).
3. **Investigation playbook**: Start with targeted observation using alert labels, then move to remediation. Verify after each action.
4. **Remediation guardrails**: Explicit list of allowed actions and their constraints.
5. **Reporting instructions**: Post findings to Slack at key moments (investigation started, key findings, remediation attempts, verification, resolution/escalation).
6. **Escalation instructions**: If unresolved after investigation, prepare a structured summary for human handoff.

### Result Handling

After `query()` completes:
- `success` -> Extract final summary, post to Slack, mark alert as resolved
- `error_max_turns` -> Trigger PagerDuty escalation with investigation summary
- Other errors -> Log infrastructure error, alert on agent health

## Tools & MCP Integration

### Grafana MCP (`mcp-grafana`)

External official server, run as a stdio process.

Tools used:
- `query_prometheus` — PromQL queries for metrics
- `query_loki` — LogQL queries for logs
- `get_dashboard` / `get_dashboard_panels` — Fetch relevant dashboards
- `list_alert_rules` / `get_alert_rule` — Understand alert configuration

Runs in read-only mode (`--disable-write`).

Config: `GRAFANA_URL`, `GRAFANA_SERVICE_ACCOUNT_TOKEN`

### Slack MCP

External server for posting investigation updates.

Tools used:
- `send_message` — Post updates to the configured incident channel

Config: `SLACK_BOT_TOKEN`, `SLACK_CHANNEL_ID`

### PagerDuty MCP

External official server, used only for escalation (outbound).

Tools used:
- `create_incident` — Escalate with investigation summary
- `list_services` / `get_on_call_members` — Route to the right team

Config: `PAGERDUTY_API_KEY`, `PAGERDUTY_SERVICE_ID`

### Remediation Tools (Custom SDK MCP Server)

In-process MCP server created via `create_sdk_mcp_server()`.

Design principles:
- Each tool has a clear description, input validation, and audit logging
- Only explicitly allowed services/namespaces can be targeted
- Dry-run mode available for testing
- New tools added by writing a function and registering it

Initial tools (stubs — actual implementation depends on infrastructure):
- `restart_pod` — Restart a specific pod by name/namespace
- `scale_deployment` — Scale a deployment up/down

The agent's `allowed_tools` list explicitly names every permitted tool. No wildcards on remediation tools.

## Alert Handling & Dedup

### Webhook Endpoint

`POST /api/v1/alerts` receives the standard Grafana alerting webhook payload:
- `status`: "firing" or "resolved"
- `alerts[]`: array of alert instances with `labels`, `annotations`, `fingerprint`, `startsAt`, `generatorURL`

### Dedup Logic

In-memory registry keyed by alert `fingerprint`:
- If investigation already running for this fingerprint -> skip, log dedup event
- If status is "resolved" -> cancel running investigation, post resolution to Slack
- Otherwise -> register and spawn new investigation

### Alert Registry Model

```
AlertInvestigation:
  fingerprint: str
  status: "investigating" | "resolved" | "escalated"
  alert_payload: dict
  started_at: datetime
  agent_task: asyncio.Task
  summary: str | None
```

### Concurrency

Each investigation runs as an `asyncio.Task`. Multiple investigations run concurrently for different fingerprints. The registry prevents duplicates.

### Cancellation

When a "resolved" webhook arrives for a fingerprint with a running investigation, the task is cancelled via `task.cancel()`. The agent session wrapper catches `asyncio.CancelledError`, posts a "resolved externally" notice to Slack, and cleans up the registry entry. The Claude Agent SDK `query()` generator is closed on cancellation — no special SDK-level handling is needed.

## Escalation

When the agent hits `max_turns` without resolving:

1. Extract the agent's last message as investigation summary
2. Create a PagerDuty incident:
   - Title: `{alert_name} — Auto-investigation exhausted`
   - Body: investigation summary, actions attempted, current metric state
   - Severity: mapped from Grafana alert labels
   - Service: derived from alert labels (configurable mapping)
3. Post escalation notice to Slack:
   - What was investigated
   - What the agent found
   - What remediation was attempted
   - Link to the PagerDuty incident
4. Update alert registry status to "escalated"

## Slack Reporting

The agent posts to Slack at key moments during investigation (via system prompt instructions):

- **Investigation started**: "Investigating alert: {name}. Querying metrics and logs..."
- **Key findings**: "Found elevated error rate in service X. Checking related logs..."
- **Remediation attempt**: "Attempting to restart pod Y in namespace Z..."
- **Verification**: "Pod restarted. Error rate dropping — monitoring..."
- **Resolution**: "Alert resolved. Root cause: {cause}. Action taken: {action}."
- **Escalation**: "Unable to resolve after 10 turns. Escalating to PagerDuty."

All messages go to a single configured channel (`SLACK_CHANNEL_ID`). No thread management in v1.

## Project Structure

```
claude-agent/
├── pyproject.toml
├── src/
│   └── incident_agent/
│       ├── __init__.py
│       ├── main.py             # FastAPI app, webhook endpoint, lifespan
│       ├── agent.py            # Agent session: prompt, query(), result handling
│       ├── alerts.py           # Alert model, dedup registry
│       ├── escalation.py       # PagerDuty escalation logic
│       ├── config.py           # Pydantic Settings
│       └── tools/
│           ├── __init__.py
│           ├── registry.py     # Tool registration, SDK MCP server
│           └── remediation.py  # Built-in safe remediation tools
├── tests/
│   ├── test_alerts.py
│   ├── test_agent.py
│   └── test_escalation.py
└── .env.example
```

## Configuration

Environment variables (managed via Pydantic Settings):

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Claude API key | required |
| `GRAFANA_URL` | Grafana instance URL | required |
| `GRAFANA_SERVICE_ACCOUNT_TOKEN` | Grafana service account token | required |
| `SLACK_BOT_TOKEN` | Slack bot token | required |
| `SLACK_CHANNEL_ID` | Channel for incident updates | required |
| `PAGERDUTY_API_KEY` | PagerDuty API key | required |
| `PAGERDUTY_SERVICE_ID` | Default service for escalations | required |
| `MAX_AGENT_TURNS` | Max observe-act-evaluate turns | 10 |
| `LOG_LEVEL` | Logging level | INFO |

## Dependencies

- `claude-agent-sdk` — Agent orchestration
- `fastapi` + `uvicorn` — HTTP server
- `pydantic-settings` — Config management
- `mcp-grafana` — Grafana MCP server (external process)
- PagerDuty and Slack MCP servers (external processes)

## Testing Strategy

- **Unit tests**: Alert parsing, dedup logic, prompt construction, escalation formatting
- **Integration tests**: Mock Claude API responses to verify full flow (webhook -> agent -> escalation)
- **Dry-run mode**: Remediation tools support dry-run for safe testing
- **Manual testing**: Send test Grafana webhook payloads to verify end-to-end flow
