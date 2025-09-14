from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .models import LeagueSettings
from .store import upsert_player, upsert_team, upsert_roster, upsert_matchup, insert_transaction_raw
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


def persist_bundle(bundle: Dict[str, Any]) -> None:
    # Defensive parsing; shapes vary for Yahoo JSON, focus on common fields
    # Teams
    teams = bundle.get("teams") or []
    for t in teams:
        tid = str(t.get("team_id") or t.get("id") or t.get("team_key") or t)
        name = str(t.get("name") or (t.get("team") or {}).get("name") or tid)
        manager = (t.get("managers") or [{}])[0].get("nickname") if isinstance(t.get("managers"), list) else None
        abbrev = (t.get("team") or {}).get("abbr") or t.get("abbrev")
        if tid and name:
            upsert_team(team_id=tid, name=name, manager=manager, abbrev=abbrev)

    # Players
    players = bundle.get("players") or []
    for p in players:
        pid = str(p.get("player_id") or p.get("id") or p.get("player_key") or p)
        name = p.get("name") or (p.get("player") or {}).get("name") or pid
        if isinstance(name, dict):
            name = name.get("full") or name.get("display") or pid
        pos = p.get("position") or p.get("display_position") or (p.get("player") or {}).get("display_position")
        team = (p.get("editorial_team_abbr") or (p.get("player") or {}).get("editorial_team_abbr"))
        bye = p.get("bye_week") or (p.get("bye_weeks") or {}).get("week")
        upsert_player(player_id=pid, name=str(name), position=str(pos) if pos else None, team=str(team) if team else None, bye_week=int(bye) if bye else None)

    # Rosters
    rosters = bundle.get("rosters") or []
    for r in rosters:
        team_id = str(r.get("team_id") or r.get("teamKey") or r.get("team_key") or "")
        week = int(r.get("week") or 0)
        for entry in r.get("entries", []):
            pid = str(entry.get("player_id") or entry.get("id") or entry.get("player_key") or "")
            slot = entry.get("slot") or entry.get("position")
            status = entry.get("status")
            if team_id and pid and week:
                upsert_roster(team_id=team_id, player_id=pid, week=week, status=status, slot=slot)

    # Matchups
    matchups = bundle.get("matchups") or bundle.get("scoreboard") or []
    for m in matchups:
        week = int(m.get("week") or 0)
        a = m.get("team_a") or m.get("teamA") or {}
        b = m.get("team_b") or m.get("teamB") or {}
        a_id = str(a.get("team_id") or a.get("id") or "")
        b_id = str(b.get("team_id") or b.get("id") or "")
        if week and a_id and b_id:
            upsert_matchup(week=week, team_id=a_id, opponent_id=b_id, projected=None, actual=None, result=None)
            upsert_matchup(week=week, team_id=b_id, opponent_id=a_id, projected=None, actual=None, result=None)

    # Transactions
    txs = bundle.get("transactions") or []
    import json as _json
    for tx in txs:
        kind = str(tx.get("type") or tx.get("kind") or "")
        team_id = str(tx.get("team_id") or tx.get("teamKey") or "")
        insert_transaction_raw(kind=kind or None, team_id=team_id or None, raw=_json.dumps(tx))


__all__ = ["fetch_league_bundle", "ingest"]


