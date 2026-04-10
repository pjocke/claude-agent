# Incident Response Agent

[![Tests](https://github.com/pjocke/claude-agent/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/pjocke/claude-agent/actions/workflows/tests.yml)

An autonomous incident response agent powered by [Claude](https://www.anthropic.com/claude) and the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python). It receives Grafana alert webhooks, investigates using observability data (logs, metrics, traces) via MCP, attempts safe remediations, posts status updates to Slack, and escalates to PagerDuty when the issue cannot be resolved.

## How It Works

1. **Grafana alert fires** — webhook hits the agent's `/api/v1/alerts` endpoint
2. **Alert is deduped** by fingerprint — duplicate alerts for the same issue are skipped
3. **Claude Agent session spawns** with full alert context and access to observability tools
4. **Agent investigates** — queries Prometheus metrics, Loki logs, dashboards, and alert rules via the Grafana MCP server
5. **Agent remediates** — attempts safe actions like restarting pods or scaling deployments
6. **Agent resolves or escalates**:
   - If the issue clears within 10 turns: posts a resolution summary to Slack
   - If not: creates a PagerDuty incident with a full investigation summary and notifies Slack

## Architecture

Single-process Python service (FastAPI) with the Claude Agent SDK at its core. Each alert investigation is an async task running a `query()` call with MCP tool access.

```
Grafana Alert ──webhook──▶ FastAPI ──spawn──▶ Claude Agent Session
                              │                      │
                              │                      ├── Grafana MCP (logs, metrics, traces)
                              │                      ├── Slack MCP (status updates)
                              │                      ├── PagerDuty MCP (context)
                              │                      └── Remediation Tools (restart, scale)
                              │
                              ├── GET /healthz
                              └── GET /api/v1/investigations
```

## Setup

### Prerequisites

- Python 3.11+
- [mcp-grafana](https://github.com/grafana/mcp-grafana) installed and available on PATH
- Node.js (for Slack and PagerDuty MCP servers via npx)

### Install

```bash
git clone https://github.com/pjocke/claude-agent.git
cd claude-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Configure

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Claude API key |
| `GRAFANA_URL` | Grafana instance URL |
| `GRAFANA_SERVICE_ACCOUNT_TOKEN` | Grafana service account token |
| `SLACK_BOT_TOKEN` | Slack bot token |
| `SLACK_CHANNEL_ID` | Channel for incident updates |
| `PAGERDUTY_API_KEY` | PagerDuty routing key (Events API v2) |
| `PAGERDUTY_SERVICE_ID` | Default PagerDuty service for escalations |
| `MAX_AGENT_TURNS` | Max autonomous loops (default: 10) |
| `LOG_LEVEL` | Logging level (default: INFO) |

### Run

```bash
uvicorn incident_agent.main:app --reload
```

The server starts on `http://localhost:8000`. Point your Grafana alert contact point webhook to `http://<host>:8000/api/v1/alerts`.

## API

### `POST /api/v1/alerts`

Receives Grafana alerting webhook payloads. Automatically deduplicates by alert fingerprint and spawns investigations for new firing alerts.

### `GET /api/v1/investigations`

Returns the current state of all investigations (fingerprint, status, start time, summary).

### `GET /healthz`

Health check endpoint.

## Remediation Tools

The agent has access to pluggable remediation tools via a custom MCP server:

- **`restart_pod`** — Restart a Kubernetes pod by name and namespace
- **`scale_deployment`** — Scale a deployment to a target replica count

These are currently stubs. To implement real remediation, replace the stub logic in `src/incident_agent/tools/remediation.py` with actual Kubernetes API calls or kubectl commands.

Allowed namespaces are configured in `remediation.py` (`ALLOWED_NAMESPACES`). The agent cannot target namespaces outside this allowlist.

## Testing

```bash
pytest tests/ -v
```

46 tests covering:
- Alert payload parsing and dedup logic
- Remediation tool validation (namespace allowlist, replica bounds, dry-run)
- PagerDuty escalation and Slack notification formatting
- Agent prompt construction and result handling
- FastAPI webhook endpoint behavior
- Full integration lifecycle (fire → investigate → resolve/escalate)

## Project Structure

```
src/incident_agent/
├── main.py             # FastAPI app, webhook endpoint, lifespan
├── agent.py            # Agent session: prompt construction, query(), result handling
├── alerts.py           # Grafana alert models, dedup registry
├── escalation.py       # PagerDuty + Slack escalation logic
├── config.py           # Pydantic Settings
└── tools/
    ├── registry.py     # SDK MCP server, tool registration
    └── remediation.py  # Pluggable remediation tool stubs
```

## Design

See [docs/superpowers/specs/2026-04-10-incident-response-agent-design.md](docs/superpowers/specs/2026-04-10-incident-response-agent-design.md) for the full design spec.
