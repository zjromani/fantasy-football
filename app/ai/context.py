from __future__ import annotations

from typing import Dict, Any

from app.store import get_connection


def build_context(top_n: int = 10) -> Dict[str, Any]:
    con = get_connection()
    try:
        cur = con.cursor()
        # Very simple context for now; can be expanded
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='players'")
        has_players = bool(cur.fetchone())
        return {"has_players": has_players, "top_free_agents": []}
    finally:
        con.close()


__all__ = ["build_context"]


