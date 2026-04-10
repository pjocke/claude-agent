import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI

from incident_agent.agent import run_investigation
from incident_agent.alerts import AlertRegistry, GrafanaWebhookPayload
from incident_agent.config import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app.state.registry = AlertRegistry()
    logger.info("Incident agent started")
    yield
    logger.info("Shutting down, cancelling all investigations...")
    await app.state.registry.cancel_all()


app = FastAPI(title="Incident Response Agent", lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/api/v1/alerts")
async def receive_alerts(payload: GrafanaWebhookPayload):
    registry: AlertRegistry = app.state.registry
    settings = get_settings()
    received = 0

    for alert in payload.alerts:
        fingerprint = alert.fingerprint
        alert_name = alert.labels.get("alertname", "Unknown")

        if alert.status == "resolved":
            if await registry.is_investigating(fingerprint):
                logger.info("Alert resolved externally: %s (fingerprint=%s)", alert_name, fingerprint)
                await registry.resolve(fingerprint, "Resolved externally via Grafana")
            continue

        if await registry.is_investigating(fingerprint):
            logger.info("Dedup: investigation already running for %s (fingerprint=%s)", alert_name, fingerprint)
            continue

        logger.info("New alert received: %s (fingerprint=%s)", alert_name, fingerprint)

        task = asyncio.create_task(
            run_investigation(alert, registry, settings),
            name=f"investigate-{fingerprint}",
        )
        await registry.register(fingerprint, alert.model_dump(), task)
        received += 1

    return {"received": len(payload.alerts), "investigations_started": received}


@app.get("/api/v1/investigations")
async def list_investigations():
    registry: AlertRegistry = app.state.registry
    investigations = await registry.get_all()
    return [
        {
            "fingerprint": inv.fingerprint,
            "status": inv.status,
            "started_at": inv.started_at.isoformat(),
            "summary": inv.summary,
            "alert_name": inv.alert_payload.get("labels", {}).get("alertname", "Unknown"),
        }
        for inv in investigations
    ]


def run():
    uvicorn.run("incident_agent.main:app", host="0.0.0.0", port=8000, reload=True)
