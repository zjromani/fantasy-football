from __future__ import annotations

import sys
from typing import Optional

from .models import LeagueSettings
from .brief import post_gm_brief
from .ai.agent import run_agent
from .config import get_settings
from .yahoo_client import YahooClient
from .ingest import fetch_league_bundle, persist_bundle


def sync_league_data() -> bool:
    """Sync fresh data from Yahoo before running scheduled tasks."""
    try:
        settings = get_settings()
        if not settings.league_key:
            print("[SYNC] No league_key configured, skipping sync")
            return False

        client = YahooClient()
        print("[SYNC] Fetching league data from Yahoo...")
        bundle = fetch_league_bundle(client, settings.league_key, cache_dir=".cache")
        persist_bundle(bundle)
        print("[SYNC] League data synced successfully")
        return True
    except Exception as e:
        print(f"[SYNC] Error syncing league data: {e}")
        print("[SYNC] Continuing with cached/existing data...")
        return False


def gm_brief() -> int:
    # For now, use a default settings object; in real use, this would follow ingest
    settings = LeagueSettings.from_yahoo({"settings": {"roster_positions": [{"position": "QB", "count": 1}, {"position": "RB", "count": 2}, {"position": "WR", "count": 2}, {"position": "TE", "count": 1}, {"position": "W/R/T", "count": 1}, {"position": "BN", "count": 5}], "scoring": {"ppr": "full"}}})
    post_gm_brief(settings)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: python -m app.schedule <gm_brief|ai_morning|ai_tuesday|ai_gameday>")
        return 2
    if argv[0] == "gm_brief":
        return gm_brief()
    if argv[0] == "ai_morning":
        sync_league_data()
        run_agent("daily_brief", constraints={})
        print("ai_morning posted")
        return 0
    if argv[0] == "ai_tuesday":
        sync_league_data()
        run_agent("tuesday_waivers", constraints={})
        print("ai_tuesday posted")
        return 0
    if argv[0] == "ai_gameday":
        sync_league_data()
        run_agent("gameday", constraints={})
        print("ai_gameday posted")
        return 0
    print(f"unknown command: {argv[0]}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
