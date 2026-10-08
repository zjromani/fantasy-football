from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from .audit import AuditStore
from .config import Settings
from .league import LeagueConfig

GROUPME_API_BASE = "https://api.groupme.com/v3"

TRADE_SIGNAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "trade_intent",
        re.compile(r"\b(trading|trade for|looking to move|anyone want)\b", re.I),
    ),
    (
        "need_position",
        re.compile(
            r"\b(need a|desperate for|looking for)\s+(?:a\s+)?(qb|rb|wr|te)\b",
            re.I,
        ),
    ),
    ("veto", re.compile(r"\b(don't veto|no veto|league vote)\b", re.I)),
)

MessageIntelHook = Callable[[list[dict[str, Any]]], None]


@dataclass(frozen=True)
class GroupMeMessage:
    id: str
    group_id: str
    user_id: str
    name: str
    text: str
    created_at: float
    system: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "group_id": self.group_id,
            "user_id": self.user_id,
            "name": self.name,
            "text": self.text,
            "created_at": self.created_at,
            "system": self.system,
        }

    @classmethod
    def from_api(cls, payload: dict[str, Any], *, group_id: str) -> GroupMeMessage:
        return cls(
            id=str(payload["id"]),
            group_id=group_id,
            user_id=str(payload.get("user_id", "")),
            name=str(payload.get("name", "")),
            text=str(payload.get("text", "")),
            created_at=float(payload.get("created_at", 0)),
            system=bool(payload.get("system", False)),
        )


class GroupMeClient:
    def __init__(
        self,
        token: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=GROUPME_API_BASE,
            headers={"X-Access-Token": token},
            transport=transport,
            timeout=30.0,
        )

    def list_messages(
        self,
        group_id: str,
        *,
        limit: int = 100,
        after_id: str | None = None,
        before_id: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str | int] = {"limit": min(max(limit, 1), 100)}
        if after_id:
            params["after_id"] = after_id
        if before_id:
            params["before_id"] = before_id
        response = self._client.get(f"/groups/{group_id}/messages", params=params)
        if response.status_code == 304:
            return []
        response.raise_for_status()
        body = response.json()
        messages = body.get("response", {}).get("messages")
        if messages is None:
            raise RuntimeError("GroupMe messages response missing messages array")
        return messages


def resolve_group_id(settings: Settings, league: LeagueConfig) -> str | None:
    if settings.groupme_group_id:
        return settings.groupme_group_id
    if league.groupme.group_id and league.groupme.enabled:
        return league.groupme.group_id
    return None


def scan_trade_signals(messages: Sequence[GroupMeMessage]) -> list[dict[str, str]]:
    signals: list[dict[str, str]] = []
    for message in messages:
        if message.system or not message.text.strip():
            continue
        for signal_type, pattern in TRADE_SIGNAL_PATTERNS:
            if pattern.search(message.text):
                signals.append(
                    {
                        "signal": signal_type,
                        "message_id": message.id,
                        "user_id": message.user_id,
                        "name": message.name,
                        "text": message.text,
                    }
                )
                break
    return signals


class GroupMePoller:
    def __init__(
        self,
        *,
        settings: Settings,
        league: LeagueConfig,
        store: AuditStore,
        client: GroupMeClient | None = None,
        hooks: Sequence[MessageIntelHook] | None = None,
    ) -> None:
        self.settings = settings
        self.league = league
        self.store = store
        self._client = client
        self._hooks = list(hooks or [])

    def poll(self, *, max_pages: int = 5) -> dict[str, Any]:
        token = self.settings.groupme_access_token
        group_id = resolve_group_id(self.settings, self.league)
        if not token:
            return {"status": "skipped", "reason": "groupme_token_unset"}
        if not group_id:
            return {"status": "skipped", "reason": "groupme_group_id_unset"}

        client = self._client or GroupMeClient(token)
        cursor = self.store.groupme_last_message_id(group_id)
        ingested: list[GroupMeMessage] = []

        for _ in range(max_pages):
            raw_messages = client.list_messages(
                group_id,
                limit=100,
                after_id=cursor,
            )
            if not raw_messages:
                break
            batch = [
                GroupMeMessage.from_api(item, group_id=group_id)
                for item in raw_messages
                if item.get("id") is not None
            ]
            if cursor and batch and batch[0].id == cursor:
                batch = batch[1:]
            if not batch:
                break
            new_rows = self.store.save_groupme_messages(batch)
            ingested.extend(new_rows)
            newest = max(batch, key=lambda message: message.created_at)
            cursor = newest.id
            self.store.set_groupme_last_message_id(group_id, cursor)
            if len(raw_messages) < 100:
                break

        message_dicts = [message.to_dict() for message in ingested]
        for hook in self._hooks:
            hook(message_dicts)
        signals = scan_trade_signals(ingested)
        return {
            "status": "ok",
            "group_id": group_id,
            "new_messages": len(ingested),
            "trade_signals": signals,
        }
