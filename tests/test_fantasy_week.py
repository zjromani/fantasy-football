from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.config import Settings
from app.fantasy_week import resolve_fantasy_week
from app.yahoo_client import YahooClient

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "yahoo_league_meta.json").read_text()
)


def settings(tmp_path: Path) -> Settings:
    return Settings(
        yahoo_client_id="client",
        yahoo_client_secret="secret",
        yahoo_token_path=str(tmp_path / "tokens.json"),
        cache_dir=str(tmp_path / "cache"),
        fantasy_week=None,
    )


def test_yahoo_current_week_reads_league_metadata(tmp_path: Path) -> None:
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
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=FIXTURE)
        ),
    )

    assert client.current_week("470.l.196780") == 6


def test_resolve_fantasy_week_prefers_cli_then_env_then_yahoo(
    tmp_path: Path,
) -> None:
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
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=FIXTURE)
        ),
    )

    assert (
        resolve_fantasy_week(
            cli_week=3,
            env_week=4,
            yahoo=client,
            league_key="470.l.196780",
        )
        == 3
    )
    assert (
        resolve_fantasy_week(
            cli_week=None,
            env_week=4,
            yahoo=client,
            league_key="470.l.196780",
        )
        == 4
    )
    assert (
        resolve_fantasy_week(
            cli_week=None,
            env_week=None,
            yahoo=client,
            league_key="470.l.196780",
        )
        == 6
    )


def test_settings_coerces_empty_fantasy_week_env() -> None:
    assert Settings(fantasy_week="").fantasy_week is None
