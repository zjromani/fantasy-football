from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.audit import AuditStore
from app.config import Settings
from app.groupme import (
    GroupMeClient,
    GroupMeMessage,
    GroupMePoller,
    scan_trade_signals,
)
from app.league import GroupMeConfig, LeagueConfig

FIXTURES = Path(__file__).parent / "fixtures"
MESSAGES_FIXTURE = json.loads((FIXTURES / "groupme_messages.json").read_text())


def test_groupme_client_list_messages_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["X-Access-Token"] == "test-token"
        assert request.url.path.endswith("/groups/12345678/messages")
        assert request.url.params["limit"] == "50"
        return httpx.Response(200, json=MESSAGES_FIXTURE)

    client = GroupMeClient("test-token", transport=httpx.MockTransport(handler))
    messages = client.list_messages("12345678", limit=50)
    assert len(messages) == 2
    assert messages[0]["id"] == "msg-100"
    assert len(requests) == 1


def test_poller_ingests_and_scans_trade_signals(tmp_path: Path) -> None:
    pages = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        pages["calls"] += 1
        after_id = request.url.params.get("after_id")
        if after_id == "msg-101":
            return httpx.Response(
                200,
                json={
                    "response": {
                        "messages": [
                            {
                                "id": "msg-102",
                                "user_id": "user-2",
                                "name": "Alex",
                                "text": "Looking for a WR, have RB depth.",
                                "created_at": 1728000200.0,
                                "system": False,
                            }
                        ]
                    }
                },
            )
        return httpx.Response(200, json=MESSAGES_FIXTURE)

    store = AuditStore(tmp_path / "audit.sqlite")
    store.migrate()
    settings = Settings(
        groupme_access_token="test-token",
        groupme_group_id="12345678",
        db_path=str(tmp_path / "audit.sqlite"),
    )
    league = LeagueConfig(
        name="Test",
        league_id="1",
        roster={"QB": 1},
        scoring={"rush_yd": 0.1},
        groupme=GroupMeConfig(enabled=True, group_id="12345678"),
    )
    hook_calls: list[int] = []

    def hook(messages: list[dict]) -> None:
        hook_calls.append(len(messages))

    poller = GroupMePoller(
        settings=settings,
        league=league,
        store=store,
        client=GroupMeClient("test-token", transport=httpx.MockTransport(handler)),
        hooks=[hook],
    )

    first = poller.poll()
    assert first["status"] == "ok"
    assert first["new_messages"] == 2
    assert first["trade_signals"][0]["signal"] == "trade_intent"
    assert hook_calls == [2]

    second = poller.poll()
    assert second["new_messages"] == 1
    assert second["trade_signals"][0]["signal"] == "need_position"
    assert pages["calls"] == 2


def test_poller_skips_without_credentials(tmp_path: Path) -> None:
    store = AuditStore(tmp_path / "audit.sqlite")
    store.migrate()
    settings = Settings(db_path=str(tmp_path / "audit.sqlite"))
    league = LeagueConfig(
        name="Test",
        league_id="1",
        roster={"QB": 1},
        scoring={"rush_yd": 0.1},
    )
    result = GroupMePoller(settings=settings, league=league, store=store).poll()
    assert result["status"] == "skipped"
    assert result["reason"] == "groupme_token_unset"


def test_scan_trade_signals_ignores_system_messages() -> None:
    messages = [
        GroupMeMessage(
            id="1",
            group_id="g",
            user_id="u",
            name="System",
            text="Mike joined",
            created_at=1.0,
            system=True,
        ),
        GroupMeMessage(
            id="2",
            group_id="g",
            user_id="u2",
            name="Sam",
            text="Don't veto this trade please",
            created_at=2.0,
            system=False,
        ),
    ]
    signals = scan_trade_signals(messages)
    assert len(signals) == 1
    assert signals[0]["signal"] == "veto"
