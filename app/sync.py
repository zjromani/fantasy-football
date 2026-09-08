from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .league import LeagueConfig
from .providers.base import ProjectionProvider
from .yahoo_client import YahooClient


def sync_raw_state(
    *,
    yahoo: YahooClient,
    fantasypros: ProjectionProvider,
    league: LeagueConfig,
    week: int,
    output: str | Path,
    include_playoffs: bool = False,
) -> Path:
    if not league.league_key or not league.team_key:
        raise RuntimeError(
            "league_key and team_key must be set in config/league.yml or environment"
        )
    provider_health = fantasypros.health()
    weekly = fantasypros.weekly_projections(week)
    rest_of_season = fantasypros.rest_of_season_rankings()
    news = fantasypros.news()
    playoff_projections = {}
    if include_playoffs:
        for playoff_week in league.playoff_weeks:
            try:
                playoff_projections[playoff_week] = fantasypros.projections(
                    playoff_week
                )
            except httpx.HTTPStatusError:
                playoff_projections = {}
                break
    snapshot = {
        "source_updated_at": datetime.now(UTC).isoformat(),
        "week": week,
        "yahoo": {
            "league": yahoo.get_json(
                f"league/{league.league_key}/settings", cache_ttl_seconds=900
            ),
            "team": yahoo.get_json(f"team/{league.team_key}", cache_ttl_seconds=300),
            "roster": yahoo.get_json(
                f"team/{league.team_key}/roster;week={week}",
                cache_ttl_seconds=300,
            ),
            "teams": yahoo.get_json(
                f"league/{league.league_key}/teams;out=roster",
                {"week": week},
                cache_ttl_seconds=900,
            ),
            "transactions": yahoo.get_json(
                f"league/{league.league_key}/transactions",
                cache_ttl_seconds=300,
            ),
            "available_players": yahoo.get_available_players(league.league_key),
        },
        "fantasypros": {
            "health": {
                "healthy": provider_health.healthy,
                "detail": provider_health.detail,
            },
            "weekly": {
                "data": weekly.data,
                "fetched_at": weekly.fetched_at.isoformat(),
                "from_cache": weekly.from_cache,
            },
            "ros": {
                "data": rest_of_season.data,
                "fetched_at": rest_of_season.fetched_at.isoformat(),
                "from_cache": rest_of_season.from_cache,
            },
            "news": {
                "data": news.data,
                "fetched_at": news.fetched_at.isoformat(),
                "from_cache": news.from_cache,
            },
            "playoffs": {
                str(playoff_week): {
                    "data": response.data,
                    "fetched_at": response.fetched_at.isoformat(),
                    "from_cache": response.from_cache,
                }
                for playoff_week, response in playoff_projections.items()
            },
        },
    }
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True))
    return output_path
