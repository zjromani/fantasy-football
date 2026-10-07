from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from .domain import Projection
from .league import GmProfile


@dataclass(frozen=True)
class TradePackage:
    send_player_keys: tuple[str, ...]
    receive_player_keys: tuple[str, ...]
    ros_delta: float
    playoff_delta: float
    structural_delta: float
    risk_delta: float
    score: float

    def eligible(self, profile: GmProfile | None = None) -> bool:
        rules = profile or GmProfile()
        return (
            self.ros_delta >= rules.trade_min_ros_delta
            and self.playoff_delta >= rules.trade_playoff_delta_floor
            and self.structural_delta >= rules.trade_structural_delta_floor
            and self.risk_delta <= rules.trade_max_risk_delta
        )


def evaluate_trade(
    *,
    send: list[Projection],
    receive: list[Projection],
    roster_need: dict[str, float],
    profile: GmProfile | None = None,
) -> TradePackage:
    ros_delta = sum(player.ros_points for player in receive) - sum(
        player.ros_points for player in send
    )
    playoff_delta = sum(player.playoff_points for player in receive) - sum(
        player.playoff_points for player in send
    )
    structural_delta = sum(
        roster_need.get(_need_position(player.position), 0) for player in receive
    ) - sum(roster_need.get(_need_position(player.position), 0) for player in send)
    risk_delta = sum(player.volatility for player in receive) - sum(
        player.volatility for player in send
    )
    rules = profile or GmProfile()
    score = (
        ros_delta
        + playoff_delta * 0.5
        + structural_delta * 2
        - risk_delta * (0.5 if rules.trade_max_risk_delta > 2 else 1.0)
    )
    return TradePackage(
        send_player_keys=tuple(player.player_key for player in send),
        receive_player_keys=tuple(player.player_key for player in receive),
        ros_delta=round(ros_delta, 2),
        playoff_delta=round(playoff_delta, 2),
        structural_delta=round(structural_delta, 2),
        risk_delta=round(risk_delta, 2),
        score=round(score, 2),
    )


def rank_outbound_trades(
    *,
    roster: list[Projection],
    opponents: dict[str, list[Projection]],
    roster_need: dict[str, float],
    profile: GmProfile | None = None,
    tradable_player_keys: set[str] | None = None,
    limit: int | None = None,
) -> list[tuple[str, TradePackage]]:
    rules = profile or GmProfile()
    proposal_limit = limit if limit is not None else rules.trade_proposal_limit
    tradable = [
        player
        for player in roster
        if tradable_player_keys is None or player.player_key in tradable_player_keys
    ]
    proposals: list[tuple[str, TradePackage]] = []
    for opponent_team_key, opponent_roster in opponents.items():
        for outgoing in tradable:
            for incoming in opponent_roster:
                package = evaluate_trade(
                    send=[outgoing],
                    receive=[incoming],
                    roster_need=roster_need,
                    profile=rules,
                )
                if package.eligible(rules):
                    proposals.append((opponent_team_key, package))
        if rules.trade_two_for_one_enabled and len(tradable) >= 2:
            for outgoing_pair in combinations(tradable, 2):
                for incoming in opponent_roster:
                    package = evaluate_trade(
                        send=list(outgoing_pair),
                        receive=[incoming],
                        roster_need=roster_need,
                        profile=rules,
                    )
                    if package.eligible(rules):
                        proposals.append((opponent_team_key, package))
    proposals.sort(key=lambda item: item[1].score, reverse=True)
    return proposals[:proposal_limit]


def _need_position(position: str) -> str:
    if position in {"IDP", "DL", "LB", "DB", "CB", "S", "DE", "DT"}:
        return "D"
    return position


__all__ = ["TradePackage", "evaluate_trade", "rank_outbound_trades"]
