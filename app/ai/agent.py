from __future__ import annotations

from typing import Dict, Any

from app.inbox import notify, latest_settings_payload
from app.ai.tools import invoke_tool
from app.store import insert_agent_run, finish_agent_run, log_tool_call, insert_decision
import json as _json
from app.ai.config import get_ai_settings
from app.ai.policy import can_execute_waiver
from app.config import get_settings
from app.yahoo_client import YahooClient


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
    pending_actions = []
    if waivers.get("recommendations"):
        top = waivers["recommendations"][0]
        actions.append(
            f"Waiver: add {top.get('name')} ({top.get('position')}) — score {top.get('score')} FAAB {top.get('faab_min')}-{top.get('faab_max')}"
        )
        # Add as a pending action unless executed by autopilot
        pending_actions.append(
            {
                "type": "waiver",
                "add_player_id": top.get("player_id"),
                "drop_player_id": None,
                "bid_amount": top.get("faab_min"),
                "score": top.get("score"),
            }
        )
    else:
        actions.append("No waivers recommended.")

    actions.append("Lineup: check injuries and BYE exposures.")
    actions.append("Trades: scan for both-sides gain opportunities.")

    # Optional autopilot execution (waivers only)
    if pending_actions and not constraints.get("offline"):
        try:
            ai_settings = get_ai_settings()
            if not ai_settings.ai_autopilot:
                raise RuntimeError("autopilot disabled")
            act = pending_actions[0]
            score = float(act.get("score") or 0)
            bid = float(act.get("bid_amount") or 0)
            # Use FAAB budget as cap proxy; remaining would be better when available
            s = get_settings()
            faab_total = s.league_key and (latest_settings_payload() or {}).get("faab_budget")
            if can_execute_waiver(score, confidence=None, faab_bid=bid, faab_total=faab_total):
                league_key = s.league_key
                team_key = s.team_key
                if not league_key or not team_key:
                    raise RuntimeError("LEAGUE_KEY and TEAM_KEY must be set for autopilot writes")
                xml = f"""
<fantasy_content>
  <transaction>
    <type>add</type>
    <faab_bid>{int(bid)}</faab_bid>
    <player>
      <player_key>{act.get('add_player_id')}</player_key>
    </player>
    <team_key>{team_key}</team_key>
  </transaction>
</fantasy_content>""".strip()
                client = YahooClient()
                resp = client.post_xml(f"league/{league_key}/transactions", xml)
                actions.append(f"Autopilot: submitted waiver for {act.get('add_player_id')} (bid {int(bid)})")
                # Clear pending since executed
                pending_actions = []
        except Exception as err:
            actions.append(f"Autopilot skipped: {err}")

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
            "pending_actions": pending_actions,
        },
    )
    insert_decision(run_id, kind="summary", confidence=None, payload=_json.dumps({"message_id": msg_id, "actions": actions}))
    finish_agent_run(run_id, status="ok")
    return msg_id


__all__ = ["run_agent"]


