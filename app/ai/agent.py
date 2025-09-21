from __future__ import annotations

from typing import Dict, Any

from app.inbox import notify, latest_settings_payload
from app.ai.tools import invoke_tool


def run_agent(task: str, constraints: Dict[str, Any] | None = None) -> int:
    """Lightweight agent orchestrator.

    - Requires LeagueSettings loaded (banner payload present)
    - Collects league state and (optionally) ranks waivers
    - Posts a single GM Brief-like message to the Inbox

    Returns the Inbox message id.
    """
    constraints = constraints or {}
    payload = latest_settings_payload() or {}
    if not payload:
        raise RuntimeError("LeagueSettings not loaded; load settings before running the agent")

    # 1) State
    state = invoke_tool("get_league_state", {})

    # 2) Optionally waivers (skip if offline/testing flag)
    waivers = {"recommendations": []}
    if not constraints.get("offline"):
        try:
            waivers = invoke_tool("rank_waivers", {})
        except Exception as err:
            waivers = {"error": str(err), "recommendations": []}

    # 3) Compose a concise brief
    actions: list[str] = []
    if waivers.get("recommendations"):
        top = waivers["recommendations"][0]
        actions.append(
            f"Waiver: add {top.get('name')} ({top.get('position')}) — score {top.get('score')} FAAB {top.get('faab_min')}-{top.get('faab_max')}"
        )
    else:
        actions.append("No waivers recommended.")

    actions.append("Lineup: check injuries and BYE exposures.")
    actions.append("Trades: scan for both-sides gain opportunities.")

    lines = ["AI GM Brief", "", "Actions:"] + [f"- {a}" for a in actions]
    body = "\n".join(lines)

    msg_id = notify(
        "brief",
        "AI GM Brief",
        body,
        {
            "task": task,
            "state": state,
            "waivers": waivers,
            "pending_actions": [],
        },
    )
    return msg_id


__all__ = ["run_agent"]


