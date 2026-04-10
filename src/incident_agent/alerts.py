import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel


class GrafanaAlert(BaseModel):
    status: Literal["firing", "resolved"]
    labels: dict[str, str]
    annotations: dict[str, str]
    fingerprint: str
    startsAt: str
    generatorURL: str = ""


class GrafanaWebhookPayload(BaseModel):
    status: str
    alerts: list[GrafanaAlert]


@dataclass
class AlertInvestigation:
    fingerprint: str
    status: Literal["investigating", "resolved", "escalated"]
    alert_payload: dict
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    agent_task: asyncio.Task | None = None
    summary: str | None = None


class AlertRegistry:
    def __init__(self) -> None:
        self._investigations: dict[str, AlertInvestigation] = {}
        self._lock = asyncio.Lock()

    async def is_investigating(self, fingerprint: str) -> bool:
        async with self._lock:
            inv = self._investigations.get(fingerprint)
            return inv is not None and inv.status == "investigating"

    async def register(
        self,
        fingerprint: str,
        alert_payload: dict,
        task: asyncio.Task,
    ) -> AlertInvestigation:
        async with self._lock:
            investigation = AlertInvestigation(
                fingerprint=fingerprint,
                status="investigating",
                alert_payload=alert_payload,
                agent_task=task,
            )
            self._investigations[fingerprint] = investigation
            return investigation

    async def resolve(self, fingerprint: str, summary: str | None = None) -> None:
        async with self._lock:
            inv = self._investigations.get(fingerprint)
            if inv is None:
                return
            inv.status = "resolved"
            inv.summary = summary
            if inv.agent_task and not inv.agent_task.done():
                inv.agent_task.cancel()

    async def escalate(self, fingerprint: str, summary: str) -> None:
        async with self._lock:
            inv = self._investigations.get(fingerprint)
            if inv is None:
                return
            inv.status = "escalated"
            inv.summary = summary

    async def get(self, fingerprint: str) -> AlertInvestigation | None:
        async with self._lock:
            return self._investigations.get(fingerprint)

    async def remove(self, fingerprint: str) -> None:
        async with self._lock:
            self._investigations.pop(fingerprint, None)

    async def get_all(self) -> list[AlertInvestigation]:
        async with self._lock:
            return list(self._investigations.values())

    async def cancel_all(self) -> None:
        async with self._lock:
            for inv in self._investigations.values():
                if inv.agent_task and not inv.agent_task.done():
                    inv.agent_task.cancel()
