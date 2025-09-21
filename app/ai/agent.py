from __future__ import annotations

from typing import Dict, Any

from app.inbox import notify, latest_settings_payload
from app.ai.tools import invoke_tool
from app.store import insert_agent_run, finish_agent_run, log_tool_call, insert_decision
import json as _json


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

    run_id = insert_agent_run(task)
    # 1) State
    try:
        state = invoke_tool("get_league_state", {})
        log_tool_call(run_id, "get_league_state", args=_json.dumps({}), result=_json.dumps(state))
    except Exception as err:
        log_tool_call(run_id, "get_league_state", args=_json.dumps({}), error=str(err))
        finish_agent_run(run_id, status="error")
        raise

    # 2) Optionally waivers (skip if offline/testing flag)
    waivers = {"recommendations": []}
    if not constraints.get("offline"):
        try:
            waivers = invoke_tool("rank_waivers", {})
            log_tool_call(run_id, "rank_waivers", args=_json.dumps({}), result=_json.dumps(waivers))
        except Exception as err:
            log_tool_call(run_id, "rank_waivers", args=_json.dumps({}), error=str(err))
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
    insert_decision(run_id, kind="summary", confidence=None, payload=_json.dumps({"message_id": msg_id, "actions": actions}))
    finish_agent_run(run_id, status="ok")
    return msg_id


__all__ = ["run_agent"]


