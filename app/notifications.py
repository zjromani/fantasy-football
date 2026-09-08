from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from .config import Settings, get_settings


@dataclass(frozen=True)
class Notification:
    title: str
    message: str
    priority: str = "default"
    approve_url: str | None = None
    ignore_url: str | None = None


class NtfyClient:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = httpx.Client(transport=transport, timeout=15)

    def publish(self, notification: Notification) -> None:
        if not self.settings.ntfy_topic:
            raise RuntimeError("NTFY_TOPIC is required")
        payload: dict[str, object] = {
            "topic": self.settings.ntfy_topic,
            "title": notification.title,
            "message": notification.message,
            "priority": notification.priority,
        }
        if notification.approve_url:
            payload["actions"] = [
                {
                    "action": "http",
                    "label": "Approve",
                    "url": notification.approve_url,
                    "method": "POST",
                    "clear": True,
                },
                {
                    "action": "http",
                    "label": "Ignore",
                    "url": notification.ignore_url,
                    "method": "POST",
                    "clear": True,
                },
            ]
        response = self.client.post(
            self.settings.ntfy_base_url.rstrip("/"),
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
