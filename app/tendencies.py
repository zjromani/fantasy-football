from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict

from .store import get_connection


def profile_manager(team_id: str) -> Dict[str, Any]:
    connection = get_connection()
    try:
        cur = connection.cursor()
        cur.execute(
            "SELECT kind, raw, created_at FROM transactions_raw WHERE team_id = ? ORDER BY created_at ASC",
            (team_id,),
        )
        rows = cur.fetchall()
    finally:
        connection.close()

    adds = 0
    drops = 0
    faab_total = 0.0
    faab_bids = []
    trades = 0
    trades_accepted = 0
    pos_counter = Counter()
    action_hours = []

    for r in rows:
        kind = (r["kind"] or "").lower()
        raw = {}
        try:
            raw = json.loads(r["raw"]) if r["raw"] else {}
        except Exception:
            raw = {}

        created = r["created_at"]
        try:
            # created_at is stored as SQLite datetime('now') string
            if created:
                action_hours.append(datetime.fromisoformat(created).hour)
        except Exception:
            pass

        if kind in {"add", "drop", "add_drop", "waiver"}:
            if kind in {"add", "add_drop", "waiver"}:
                adds += 1
            if kind in {"drop", "add_drop"}:
                drops += 1
            pos = str(raw.get("position") or raw.get("pos") or "").upper()
            if pos:
                pos_counter[pos] += 1
            faab = raw.get("faab") or raw.get("bid") or 0
            try:
                val = float(faab)
                faab_total += val
                if val > 0:
                    faab_bids.append(val)
            except Exception:
                pass
        elif kind == "trade":
            trades += 1
            status = str(raw.get("status", "")).lower()
            if status in {"accepted", "complete", "completed"}:
                trades_accepted += 1

    faab_spend_rate = faab_total
    avg_bid = (sum(faab_bids) / len(faab_bids)) if faab_bids else 0.0
    position_bias = dict(pos_counter)
    typical_hour = int(round(sum(action_hours) / len(action_hours))) if action_hours else None
    acceptance_rate = (trades_accepted / trades) if trades else 0.0

    return {
        "team_id": team_id,
        "add_count": adds,
        "drop_count": drops,
        "faab_spend_total": round(faab_spend_rate, 2),
        "faab_avg_bid": round(avg_bid, 2),
        "position_bias": position_bias,
        "trade_count": trades,
        "trade_acceptance_rate": round(acceptance_rate, 3),
        "typical_action_hour": typical_hour,
    }


__all__ = ["profile_manager"]


