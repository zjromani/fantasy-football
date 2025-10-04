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
    try:
        response = client.get(path, params=params)
        response.raise_for_status()
    except Exception as e:
        # Surface response body if available for better diagnostics
        body = None
        try:
            body = response.text  # type: ignore[name-defined]
        except Exception:
            body = None
        msg = f"ingest fetch failed for {path} params={params}: {e}"
        if body:
            msg += f" | body={body}"
        raise RuntimeError(msg)
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
        # Yahoo requires teams;out=roster to expand rosters for all teams
        "rosters": f"league/{league_key}/teams;out=roster",
        "players": f"league/{league_key}/players",
        "matchups": f"league/{league_key}/scoreboard",
        "standings": f"league/{league_key}/standings",
        "transactions": f"league/{league_key}/transactions",
    }
    for name, ep in endpoints.items():
        bundle[name] = _get_or_fetch_json(client, ep, params={"format": "json"}, cache_dir=cd)
    return bundle


def ingest(client: YahooClient, league_key: str, *, cache_dir: Optional[str] = None) -> Tuple[Dict[str, Any], LeagueSettings]:
    bundle = fetch_league_bundle(client, league_key, cache_dir=cache_dir)
    # Prefer league.settings if present, otherwise pass entire league dict
    league_raw = bundle.get("league", {})
    settings = LeagueSettings.from_yahoo(league_raw)
    return bundle, settings


def persist_bundle(bundle: Dict[str, Any]) -> None:
    # Defensive parsing; if shapes are unexpected, skip rather than error
    import json as _json

    def _flatten_yahoo_list(obj: Any) -> dict:
        """Yahoo returns objects as lists of single-key dicts. Flatten to one dict."""
        if not isinstance(obj, list):
            return obj if isinstance(obj, dict) else {}
        result = {}
        for item in obj:
            if isinstance(item, dict):
                result.update(item)
            elif isinstance(item, list):
                # Nested list (rare)
                nested = _flatten_yahoo_list(item)
                if nested:
                    result.update(nested)
        return result

    def _extract_items(data: Any, *path: str) -> list:
        """Navigate Yahoo's fantasy_content.league.X structure and extract numeric-keyed items.

        Yahoo API returns: fantasy_content.league = [league_obj, sub_resource]
        where sub_resource contains the actual collection (teams, players, etc.)
        """
        current = data
        for key in path:
            if isinstance(current, dict):
                current = current.get(key, {})
            elif isinstance(current, list):
                # Yahoo's league is a list: [league_info, sub_resource]
                # If we're looking for a sub-resource, check index 1
                if key == "league" and len(current) > 0:
                    # Keep it as list so next iteration can handle sub-resource
                    pass
                elif len(current) > 1 and isinstance(current[1], dict) and key in current[1]:
                    # Sub-resource found at index 1
                    current = current[1].get(key, {})
                elif len(current) == 1:
                    current = current[0]
                else:
                    return []
            else:
                return []

        if isinstance(current, list):
            return current
        elif isinstance(current, dict):
            # Yahoo returns collections as {count: N, "0": {...}, "1": {...}}
            items = []
            for k, v in current.items():
                if k.isdigit() and isinstance(v, dict):
                    items.append(v)
            return items
        return []

    # Teams
    teams = bundle.get("teams")
    if isinstance(teams, list):
        for t in teams:
            if not isinstance(t, dict):
                continue
            tid = str(t.get("team_id") or t.get("id") or t.get("team_key") or "")
            name = t.get("name") or (t.get("team") or {}).get("name") or tid
            if isinstance(name, dict):
                name = name.get("full") or name.get("display") or tid
            manager = (t.get("managers") or [{}])[0].get("nickname") if isinstance(t.get("managers"), list) else None
            abbrev = (t.get("team") or {}).get("abbr") or t.get("abbrev")
            if tid and name:
                upsert_team(team_id=tid, name=str(name), manager=manager, abbrev=abbrev)
    elif isinstance(teams, dict):
        # Parse Yahoo structure: fantasy_content.league.teams
        for team_wrap in _extract_items(teams, "fantasy_content", "league", "teams"):
            # team_wrap = {"team": [[{team_key: ...}, {team_id: ...}, ...]]}
            team_list = team_wrap.get("team") if isinstance(team_wrap, dict) else None
            if not isinstance(team_list, list):
                continue
            team = _flatten_yahoo_list(team_list)
            tid = str(team.get("team_id") or team.get("team_key") or "")
            name = team.get("name", "")
            manager = None
            if isinstance(team.get("managers"), list) and team["managers"]:
                mgr_wrap = team["managers"][0]
                if isinstance(mgr_wrap, dict):
                    mgr = mgr_wrap.get("manager", {})
                    manager = mgr.get("nickname") or mgr.get("guid")
            abbrev = None
            if tid and name:
                upsert_team(team_id=tid, name=str(name), manager=manager, abbrev=abbrev)

    # Players
    players = bundle.get("players")
    if isinstance(players, list):
        for p in players:
            if not isinstance(p, dict):
                continue
            pid = str(p.get("player_id") or p.get("id") or p.get("player_key") or "")
            name = p.get("name") or (p.get("player") or {}).get("name") or pid
            if isinstance(name, dict):
                name = name.get("full") or name.get("display") or pid
            pos = p.get("position") or p.get("display_position") or (p.get("player") or {}).get("display_position")
            team = (p.get("editorial_team_abbr") or (p.get("player") or {}).get("editorial_team_abbr"))
            bye = p.get("bye_week") or (p.get("bye_weeks") or {}).get("week")
            if pid and name:
                upsert_player(player_id=pid, name=str(name), position=str(pos) if pos else None, team=str(team) if team else None, bye_week=int(bye) if bye else None)
    elif isinstance(players, dict):
        for player_wrap in _extract_items(players, "fantasy_content", "league", "players"):
            player_list = player_wrap.get("player") if isinstance(player_wrap, dict) else None
            if not isinstance(player_list, list):
                continue
            player = _flatten_yahoo_list(player_list)
            pid = str(player.get("player_id") or player.get("player_key") or "")
            name = player.get("name", {})
            if isinstance(name, dict):
                name = name.get("full") or name.get("ascii_first", "") + " " + name.get("ascii_last", "")
            pos = player.get("display_position") or player.get("primary_position")
            team = player.get("editorial_team_abbr")
            bye = None
            if isinstance(player.get("bye_weeks"), dict):
                bye = player["bye_weeks"].get("week")
            if pid and name:
                upsert_player(player_id=pid, name=str(name).strip(), position=str(pos) if pos else None, team=str(team) if team else None, bye_week=int(bye) if bye else None)

    # Rosters
    rosters = bundle.get("rosters")
    if isinstance(rosters, list):
        for r in rosters:
            if not isinstance(r, dict):
                continue
            team_id = str(r.get("team_id") or r.get("teamKey") or r.get("team_key") or "")
            week_val = r.get("week")
            week = int(week_val) if isinstance(week_val, (int, str)) and str(week_val).isdigit() else 0
            entries = r.get("entries") if isinstance(r.get("entries"), list) else []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                pid = str(entry.get("player_id") or entry.get("id") or entry.get("player_key") or "")
                slot = entry.get("slot") or entry.get("position")
                status = entry.get("status")
                if team_id and pid and week:
                    upsert_roster(team_id=team_id, player_id=pid, week=week, status=status, slot=slot)
    elif isinstance(rosters, dict):
        # Rosters come from teams;out=roster, so parse teams with their rosters
        for team_wrap in _extract_items(rosters, "fantasy_content", "league", "teams"):
            team_list = team_wrap.get("team") if isinstance(team_wrap, dict) else None
            if not isinstance(team_list, list):
                continue
            team = _flatten_yahoo_list(team_list)
            team_id = str(team.get("team_id") or team.get("team_key") or "")
            roster = team.get("roster", {})
            if not isinstance(roster, dict):
                continue
            week = roster.get("week")
            if isinstance(week, str) and week.isdigit():
                week = int(week)
            elif not isinstance(week, int):
                week = 0
            # roster["0"].players contains the actual player list
            roster_wrap = roster.get("0", {})
            players_data = roster_wrap.get("players", {})
            for player_wrap in _extract_items(players_data):
                player_list = player_wrap.get("player") if isinstance(player_wrap, dict) else None
                if not isinstance(player_list, list):
                    continue
                player = _flatten_yahoo_list(player_list)
                pid = str(player.get("player_id") or player.get("player_key") or "")

                # Also upsert player details from roster data
                name = player.get("name", {})
                if isinstance(name, dict):
                    name = name.get("full") or name.get("ascii_first", "") + " " + name.get("ascii_last", "")
                pos = player.get("display_position") or player.get("primary_position")
                team = player.get("editorial_team_abbr")
                bye = None
                if isinstance(player.get("bye_weeks"), dict):
                    bye = player["bye_weeks"].get("week")
                if pid and name:
                    upsert_player(player_id=pid, name=str(name).strip(), position=str(pos) if pos else None, team=str(team) if team else None, bye_week=int(bye) if bye else None)

                # Selected position info
                selected_list = player_wrap.get("selected_position") if isinstance(player_wrap, dict) else None
                if isinstance(selected_list, list):
                    selected = _flatten_yahoo_list(selected_list)
                elif isinstance(selected_list, dict):
                    selected = selected_list
                else:
                    selected = {}
                slot = selected.get("position") if isinstance(selected, dict) else None
                status = player.get("status")
                if team_id and pid and week:
                    upsert_roster(team_id=team_id, player_id=pid, week=week, status=status, slot=slot)

    # Matchups
    matchups_raw = bundle.get("matchups")
    if isinstance(matchups_raw, list):
        for m in matchups_raw:
            if not isinstance(m, dict):
                continue
            week = int(m.get("week") or 0)
            a = m.get("team_a") or m.get("teamA") or {}
            b = m.get("team_b") or m.get("teamB") or {}
            a_id = str(a.get("team_id") or a.get("id") or "") if isinstance(a, dict) else ""
            b_id = str(b.get("team_id") or b.get("id") or "") if isinstance(b, dict) else ""
            if week and a_id and b_id:
                upsert_matchup(week=week, team_id=a_id, opponent_id=b_id, projected=None, actual=None, result=None)
                upsert_matchup(week=week, team_id=b_id, opponent_id=a_id, projected=None, actual=None, result=None)
    elif isinstance(matchups_raw, dict):
        fc = matchups_raw.get("fantasy_content", {})
        league = fc.get("league", [])
        if not isinstance(league, list) or len(league) < 2:
            pass
        else:
            scoreboard = league[1].get("scoreboard", {})
            week = scoreboard.get("week")
            if isinstance(week, str) and week.isdigit():
                week = int(week)
            elif not isinstance(week, int):
                week = 0
            # scoreboard["0"].matchups contains the actual matchups
            sb_wrap = scoreboard.get("0", {})
            matchups_dict = sb_wrap.get("matchups", {})
            for matchup_wrap in _extract_items(matchups_dict):
                matchup_data = matchup_wrap.get("matchup", {}) if isinstance(matchup_wrap, dict) else {}
                if not isinstance(matchup_data, dict):
                    continue
                # matchup_data["0"].teams contains the team list
                teams_wrap = matchup_data.get("0", {})
                teams = teams_wrap.get("teams", {})
                team_list = _extract_items(teams)
                if len(team_list) >= 2:
                    team_a_list = team_list[0].get("team") if isinstance(team_list[0], dict) else None
                    team_b_list = team_list[1].get("team") if isinstance(team_list[1], dict) else None
                    if isinstance(team_a_list, list) and isinstance(team_b_list, list):
                        team_a = _flatten_yahoo_list(team_a_list)
                        team_b = _flatten_yahoo_list(team_b_list)
                        a_id = str(team_a.get("team_id") or team_a.get("team_key") or "")
                        b_id = str(team_b.get("team_id") or team_b.get("team_key") or "")
                        if week and a_id and b_id:
                            upsert_matchup(week=week, team_id=a_id, opponent_id=b_id, projected=None, actual=None, result=None)
                            upsert_matchup(week=week, team_id=b_id, opponent_id=a_id, projected=None, actual=None, result=None)

    # Transactions
    txs = bundle.get("transactions")
    if isinstance(txs, list):
        for tx in txs:
            if not isinstance(tx, dict):
                continue
            kind = str(tx.get("type") or tx.get("kind") or "")
            team_id = str(tx.get("team_id") or tx.get("teamKey") or "")
            insert_transaction_raw(kind=kind or None, team_id=team_id or None, raw=_json.dumps(tx))
    elif isinstance(txs, dict):
        for tx_wrap in _extract_items(txs, "fantasy_content", "league", "transactions"):
            tx_list = tx_wrap.get("transaction") if isinstance(tx_wrap, dict) else None
            if not isinstance(tx_list, list):
                continue
            tx = _flatten_yahoo_list(tx_list)
            kind = str(tx.get("type") or "")
            team_id = None
            # Transactions can have players with source/destination teams
            insert_transaction_raw(kind=kind or None, team_id=team_id, raw=_json.dumps(tx))


__all__ = ["fetch_league_bundle", "ingest"]


