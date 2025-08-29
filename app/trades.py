from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from .models import LeagueSettings
from .inbox import notify


@dataclass
class Player:
    id: str
    name: str
    position: str
    proj_next3: float  # total projected points next 3 weeks if starting
    playoff_proj: float  # total projected Weeks 15-17
    bye_next3: int  # number of byes in next 3
    injury: str = ""
    volatility: float = 0.0  # higher is riskier


@dataclass
class TeamState:
    team_id: str
    starters_by_slot: Dict[str, int]  # required starters per slot
    bench_redundancy: Dict[str, int]  # counts by pos
    bye_exposure: int  # projected zeros next 3 weeks
    injuries: int
    schedule_difficulty: float  # 0 easy .. 3 hard
    manager_profile: Dict
    roster: List[Player]


@dataclass
class TradeProposal:
    offer_from: str
    offer_to: str
    send: List[str]  # player ids from offer_from
    receive: List[str]  # player ids going to offer_from
    score: float
    rationale: str


def _need_score(state: TeamState) -> Dict[str, float]:
    # Simple needs: if bench redundancy low and required starters high, higher need
    need: Dict[str, float] = {}
    for pos, req in state.starters_by_slot.items():
        redundancy = state.bench_redundancy.get(pos, 0)
        need[pos] = max(0.0, req - redundancy * 0.7)
    return need


def _player_value_for_team(player: Player, state: TeamState, pos_need: float) -> float:
    base = player.proj_next3
    bye_penalty = 3.0 * player.bye_next3
    injury_penalty = 2.0 if player.injury.upper() in {"D", "OUT"} else 1.0 if player.injury.upper() == "Q" else 0.0
    vol_penalty = player.volatility
    schedule_impact = -1.0 * state.schedule_difficulty
    need_bonus = 2.0 * pos_need
    return round(base - bye_penalty - injury_penalty - vol_penalty + schedule_impact + need_bonus, 2)


def _trade_delta_for_teams(a: TeamState, b: TeamState, send_from_a: List[Player], send_from_b: List[Player]) -> Tuple[float, float]:
    need_a = _need_score(a)
    need_b = _need_score(b)
    # Value leaving and incoming
    out_a = sum(_player_value_for_team(p, a, need_a.get(p.position, 0.0)) for p in send_from_a)
    in_a = sum(_player_value_for_team(p, a, need_a.get(p.position, 0.0)) for p in send_from_b)
    out_b = sum(_player_value_for_team(p, b, need_b.get(p.position, 0.0)) for p in send_from_b)
    in_b = sum(_player_value_for_team(p, b, need_b.get(p.position, 0.0)) for p in send_from_a)

    delta_a = in_a - out_a
    delta_b = in_b - out_b

    # BYE relief credit if removes projected zero
    bye_relief_a = 2.5 if a.bye_exposure > 0 and any(p.bye_next3 == 0 for p in send_from_b) else 0.0
    bye_relief_b = 2.5 if b.bye_exposure > 0 and any(p.bye_next3 == 0 for p in send_from_a) else 0.0

    # Playoff bonus
    playoff_a = 0.5 * sum(p.playoff_proj for p in send_from_b) - 0.5 * sum(p.playoff_proj for p in send_from_a)
    playoff_b = 0.5 * sum(p.playoff_proj for p in send_from_a) - 0.5 * sum(p.playoff_proj for p in send_from_b)

    # Risk penalty
    risk_a = 0.3 * sum(p.volatility for p in send_from_b)
    risk_b = 0.3 * sum(p.volatility for p in send_from_a)

    delta_a = round(delta_a + bye_relief_a + playoff_a - risk_a, 2)
    delta_b = round(delta_b + bye_relief_b + playoff_b - risk_b, 2)
    return delta_a, delta_b


def propose_trades(settings: LeagueSettings, team_a: TeamState, team_b: TeamState, *, top_k: int = 3) -> List[TradeProposal]:
    proposals: List[TradeProposal] = []
    # 1-for-1
    for pa in team_a.roster:
        for pb in team_b.roster:
            da, db = _trade_delta_for_teams(team_a, team_b, [pa], [pb])
            if da > 0 and db > 0:
                score = round(da + db, 2)
                rationale = f"A +{da:.1f}, B +{db:.1f}; BYE relief/PO considerations included"
                proposals.append(
                    TradeProposal(
                        offer_from=team_a.team_id,
                        offer_to=team_b.team_id,
                        send=[pa.id],
                        receive=[pb.id],
                        score=score,
                        rationale=rationale,
                    )
                )

    # 2-for-2: pick top two by position needs heuristics (simple pair generation)
    a_pairs = [(team_a.roster[i], team_a.roster[j]) for i in range(len(team_a.roster)) for j in range(i + 1, len(team_a.roster))]
    b_pairs = [(team_b.roster[i], team_b.roster[j]) for i in range(len(team_b.roster)) for j in range(i + 1, len(team_b.roster))]
    for pa1, pa2 in a_pairs[:6]:
        for pb1, pb2 in b_pairs[:6]:
            da, db = _trade_delta_for_teams(team_a, team_b, [pa1, pa2], [pb1, pb2])
            if da > 0 and db > 0:
                score = round(da + db, 2)
                rationale = f"A +{da:.1f}, B +{db:.1f}; 2-for-2 package"
                proposals.append(
                    TradeProposal(
                        offer_from=team_a.team_id,
                        offer_to=team_b.team_id,
                        send=[pa1.id, pa2.id],
                        receive=[pb1.id, pb2.id],
                        score=score,
                        rationale=rationale,
                    )
                )

    proposals.sort(key=lambda p: p.score, reverse=True)
    return proposals[:top_k]


def propose_and_notify(settings: LeagueSettings, team_a: TeamState, team_b: TeamState, *, top_k: int = 3) -> Tuple[List[TradeProposal], int]:
    props = propose_trades(settings, team_a, team_b, top_k=top_k)
    if not props:
        msg_id = notify("trades", "No mutually beneficial trades found", "No 1-for-1 or 2-for-2 trades improved both teams.", {})
        return [], msg_id
    # Build concise inbox message
    lines = []
    for i, p in enumerate(props):
        send = ",".join(p.send)
        recv = ",".join(p.receive)
        lines.append(f"{i+1}. {p.offer_from} send [{send}] ⇄ get [{recv}] — score {p.score:.1f}")
    body = "\n".join(lines)
    payload = {"proposals": [p.__dict__ for p in props]}
    msg_id = notify("trades", "Trade proposals", body, payload)
    return props, msg_id


__all__ = [
    "Player",
    "TeamState",
    "TradeProposal",
    "propose_trades",
    "propose_and_notify",
]


