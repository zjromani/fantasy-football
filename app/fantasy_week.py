from __future__ import annotations

from .yahoo_client import YahooClient


def resolve_fantasy_week(
    *,
    cli_week: int | None,
    env_week: int | None,
    yahoo: YahooClient,
    league_key: str,
) -> int:
    if cli_week is not None:
        return cli_week
    if env_week is not None:
        return env_week
    return yahoo.current_week(league_key)


__all__ = ["resolve_fantasy_week"]
