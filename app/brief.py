from __future__ import annotations

from typing import Dict, List, Tuple

from .inbox import notify
from .models import LeagueSettings


def build_gm_brief(settings: LeagueSettings) -> Tuple[str, str, Dict]:
    # Deterministic brief content for now
    title = "Tuesday GM Brief"
    actions = [
        "Confirm injuries and practice reports",
        "Review waiver priorities and FAAB ranges",
        "Scout two trade partners for needs fit",
    ]
    lineup = [
        "No lineup changes proposed — revisit Thu AM after practice reports.",
    ]
    waivers = [
        "1) RB Target — FAAB 8–12",
        "2) WR Streamer — FAAB 3–6",
        "3) TE Upside — FAAB 1–3",
        "4) QB Bye cover — FAAB 0–2",
        "5) DEF Matchup — FAAB 0–1",
    ]
    trades = [
        "1) 1-for-1 swap that improves both teams (details in Trades)",
        "2) 2-for-2 package balancing depth and needs",
        "3) Backup-for-upgrade offer with bye relief",
    ]
    survivor = "Survivor: CHI over ARI (home, trench + turnover edge)"

    lines: List[str] = []
    lines.append("Actions:")
    for a in actions:
        lines.append(f"- {a}")
    lines.append("")
    lines.append("Lineup:")
    for l in lineup:
        lines.append(f"- {l}")
    lines.append("")
    lines.append("Waivers:")
    for w in waivers:
        lines.append(f"- {w}")
    lines.append("")
    lines.append("Trades:")
    for t in trades:
        lines.append(f"- {t}")
    lines.append("")
    lines.append(survivor)

    body = "\n".join(lines)
    payload = {
        "actions": actions,
        "lineup": lineup,
        "waivers": waivers,
        "trades": trades,
        "survivor": survivor,
        "settings": settings.model_dump(),
    }
    return title, body, payload


def post_gm_brief(settings: LeagueSettings) -> int:
    title, body, payload = build_gm_brief(settings)
    return notify("brief", title, body, payload)


__all__ = ["build_gm_brief", "post_gm_brief"]


