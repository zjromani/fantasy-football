from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .models import LeagueSettings
from .yahoo_client import YahooClient


def _cache_key_for(path: str, params: Optional[Dict[str, Any]]) -> str:
    base = path.strip()
    if params:
        items = sorted((str(k), str(v)) for k, v in params.items())
        qs = "&".join(f"{k}={v}" for k, v in items)
        base = f"{base}?{qs}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def _cache_read(cache_dir: Path, key: str) -> Optional[Dict[str, Any]]:
    file_path = cache_dir / f"{key}.json"
    if file_path.exists():
        return json.loads(file_path.read_text(encoding="utf-8"))
    return None


def _cache_write(cache_dir: Path, key: str, data: Dict[str, Any]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    file_path = cache_dir / f"{key}.json"
    file_path.write_text(json.dumps(data), encoding="utf-8")


def _get_or_fetch_json(
    client: YahooClient, path: str, *, params: Optional[Dict[str, Any]], cache_dir: Path
) -> Dict[str, Any]:
    key = _cache_key_for(path, params)
    cached = _cache_read(cache_dir, key)
    if cached is not None:
        return cached
    response = client.get(path, params=params)
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict):
        _cache_write(cache_dir, key, data)
    return data


def fetch_league_bundle(
    client: YahooClient, league_key: str, *, cache_dir: Optional[str] = None
) -> Dict[str, Any]:
    cd = Path(cache_dir or ".cache")
    bundle: Dict[str, Any] = {}
    # Endpoints chosen to cover core artifacts; Yahoo uses XML in practice, but we consume JSON here for tests.
    endpoints = {
        "league": f"league/{league_key}",
        "teams": f"league/{league_key}/teams",
        "rosters": f"league/{league_key}/rosters",
        "players": f"league/{league_key}/players",
        "matchups": f"league/{league_key}/scoreboard",
        "standings": f"league/{league_key}/standings",
        "transactions": f"league/{league_key}/transactions",
    }
    for name, ep in endpoints.items():
        bundle[name] = _get_or_fetch_json(client, ep, params=None, cache_dir=cd)
    return bundle


def ingest(client: YahooClient, league_key: str, *, cache_dir: Optional[str] = None) -> Tuple[Dict[str, Any], LeagueSettings]:
    bundle = fetch_league_bundle(client, league_key, cache_dir=cache_dir)
    # Prefer league.settings if present, otherwise pass entire league dict
    league_raw = bundle.get("league", {})
    settings = LeagueSettings.from_yahoo(league_raw)
    return bundle, settings


__all__ = ["fetch_league_bundle", "ingest"]


