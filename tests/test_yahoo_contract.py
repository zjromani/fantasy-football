from __future__ import annotations

import json
import stat
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.yahoo_client import YahooClient, YahooWriteUnavailable


def settings(tmp_path: Path) -> Settings:
    return Settings(
        yahoo_client_id="client",
        yahoo_client_secret="secret",
        yahoo_redirect_uri="http://localhost/callback",
        yahoo_token_path=str(tmp_path / "tokens.json"),
        cache_dir=str(tmp_path / "cache"),
    )


def test_refresh_rotation_permissions_and_roster_xml(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/get_token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "new-access",
                    "refresh_token": "rotated-refresh",
                    "expires_in": 3600,
                },
            )
        return httpx.Response(200, json={"ok": True})

    token_path = tmp_path / "tokens.json"
    token_path.write_text(
        json.dumps(
            {
                "access_token": "expired",
                "refresh_token": "old-refresh",
                "expires_at": 0,
            }
        )
    )
    client = YahooClient(
        settings=settings(tmp_path), transport=httpx.MockTransport(handler)
    )

    client.set_roster("449.l.1.t.1", 3, {"449.p.1": "QB", "449.p.2": "BN"})

    saved = json.loads(token_path.read_text())
    assert saved["refresh_token"] == "rotated-refresh"
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
    write = requests[-1]
    assert write.method == "PUT"
    assert write.headers["authorization"] == "Bearer new-access"
    assert "<week>3</week>" in write.content.decode()
    assert "<position>QB</position>" in write.content.decode()


def test_every_http_error_is_raised(tmp_path: Path) -> None:
    token_path = tmp_path / "tokens.json"
    token_path.write_text(
        json.dumps(
            {
                "access_token": "valid",
                "refresh_token": "refresh",
                "expires_at": 4_000_000_000,
            }
        )
    )
    client = YahooClient(
        settings=settings(tmp_path),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )

    with pytest.raises(httpx.HTTPStatusError):
        client.get("league/449.l.1")


def test_read_only_write_becomes_typed_error(tmp_path: Path) -> None:
    token_path = tmp_path / "tokens.json"
    token_path.write_text(
        json.dumps(
            {
                "access_token": "valid",
                "refresh_token": "refresh",
                "expires_at": 4_000_000_000,
            }
        )
    )
    client = YahooClient(
        settings=settings(tmp_path),
        transport=httpx.MockTransport(lambda request: httpx.Response(403)),
    )

    with pytest.raises(YahooWriteUnavailable):
        client.set_roster("449.l.1.t.1", 1, {"449.p.1": "QB"})


def test_oauth_state_must_match(tmp_path: Path) -> None:
    client = YahooClient(settings=settings(tmp_path))
    with pytest.raises(ValueError, match="state mismatch"):
        client.exchange_code_for_tokens(
            "code", expected_state="expected", received_state="attacker"
        )


def test_available_players_are_paginated(tmp_path: Path) -> None:
    token_path = tmp_path / "tokens.json"
    token_path.write_text(
        json.dumps(
            {
                "access_token": "valid",
                "refresh_token": "refresh",
                "expires_at": 4_000_000_000,
            }
        )
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        count = 25 if "start=0" in str(request.url) else 1
        return httpx.Response(
            200,
            json={
                "fantasy_content": {
                    "players": [
                        {"player": [{"player_key": f"449.p.{index}"}]}
                        for index in range(count)
                    ]
                }
            },
        )

    client = YahooClient(
        settings=settings(tmp_path), transport=httpx.MockTransport(handler)
    )

    result = client.get_available_players("449.l.1")

    assert len(result["pages"]) == 2
    assert "start=0" in str(requests[0].url)
    assert "start=25" in str(requests[1].url)
