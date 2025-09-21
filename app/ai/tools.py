from __future__ import annotations

from typing import Any, Callable, Dict, Tuple

from app.inbox import notify, latest_settings_payload
from app.store import get_connection
from app.waivers import rank_free_agents, free_agents_from_yahoo
from app.models import LeagueSettings
from app.yahoo_client import YahooClient
from app.config import get_settings


ToolFunc = Callable[[Dict[str, Any]], Dict[str, Any]]


def _get_league_state(_: Dict[str, Any]) -> Dict[str, Any]:
    # Compose basic state from DB and last-known settings; avoid network in this tool
    payload = latest_settings_payload() or {}
    con = get_connection()
    try:
        cur = con.cursor()
        cur.execute("SELECT COUNT(1) FROM teams")
        teams = cur.fetchone()[0] if cur.fetchone is not None else 0
        cur.execute("SELECT COUNT(1) FROM players")
        players = cur.fetchone()[0] if cur.fetchone is not None else 0
        cur.execute("SELECT COUNT(1) FROM recommendations WHERE status='pending'")
        pending = cur.fetchone()[0] if cur.fetchone is not None else 0
    finally:
        con.close()
    return {
        "settings": payload,
        "counts": {"teams": teams, "players": players, "pending_recommendations": pending},
    }


def _rank_waivers(_: Dict[str, Any]) -> Dict[str, Any]:
    # Pull free agents live and rank with current settings
    settings_payload = latest_settings_payload() or {}
    if not settings_payload:
        raise RuntimeError("LeagueSettings not loaded")
    settings = LeagueSettings.from_yahoo({"settings": settings_payload})
    s = get_settings()
    if not s.league_key:
        raise RuntimeError("LEAGUE_KEY not configured")
    client = YahooClient()
    fa = free_agents_from_yahoo(client, s.league_key)
    current = {
        "QB": settings.positional_limits.qb,
        "RB": settings.positional_limits.rb,
        "WR": settings.positional_limits.wr,
        "TE": settings.positional_limits.te,
    }
    recs = rank_free_agents(
        settings=settings,
        current_starters_count=current,
        free_agents=fa,
        faab_remaining=settings.faab_budget or 0,
        waiver_type="faab",
        top_n=5,
    )
    out = [r.__dict__ for r in recs]
    return {"recommendations": out}


def _optimize_lineup(_: Dict[str, Any]) -> Dict[str, Any]:
    # Stub for now; agent will use the dedicated module later
    return {"swaps": []}


def _find_trade_opportunities(_: Dict[str, Any]) -> Dict[str, Any]:
    return {"proposals": []}


def _post_inbox(args: Dict[str, Any]) -> Dict[str, Any]:
    kind = str(args.get("kind", "info"))
    title = str(args["title"])  # required
    body = str(args.get("body", ""))
    payload = args.get("payload") or {}
    msg_id = notify(kind, title, body, payload)
    return {"message_id": msg_id}


def _execute_waiver(args: Dict[str, Any]) -> Dict[str, Any]:
    # No-op placeholder; approvals/writes are handled elsewhere
    return {"executed": False, "reason": "approvals_required"}


def registry() -> Dict[str, Tuple[ToolFunc, Dict[str, Any]]]:
    """Return tool name -> (callable, json_schema) mapping."""
    return {
        "get_league_state": (
            _get_league_state,
            {
                "name": "get_league_state",
                "description": "Return league settings and basic counts (teams, players, pending recommendations)",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        ),
        "rank_waivers": (
            _rank_waivers,
            {
                "name": "rank_waivers",
                "description": "Rank free agents using current LeagueSettings",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        ),
        "optimize_lineup": (
            _optimize_lineup,
            {
                "name": "optimize_lineup",
                "description": "Propose swaps with reasons based on positional limits and injuries",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        ),
        "find_trade_opportunities": (
            _find_trade_opportunities,
            {
                "name": "find_trade_opportunities",
                "description": "Find trade proposals that improve both teams",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        ),
        "post_inbox": (
            _post_inbox,
            {
                "name": "post_inbox",
                "description": "Post a message into the Inbox",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string"},
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                        "payload": {"type": "object"},
                    },
                    "required": ["title"],
                    "additionalProperties": False,
                },
            },
        ),
        "execute_waiver": (
            _execute_waiver,
            {
                "name": "execute_waiver",
                "description": "Submit a waiver claim (no-op unless approvals enabled)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "add_player_id": {"type": "string"},
                        "drop_player_id": {"type": "string"},
                        "bid_amount": {"type": "number"},
                    },
                    "required": ["add_player_id"],
                    "additionalProperties": False,
                },
            },
        ),
    }


def invoke_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    tools = registry()
    if name not in tools:
        raise KeyError(f"Unknown tool: {name}")
    func, _schema = tools[name]
    return func(args)


