from __future__ import annotations

from dataclasses import dataclass

from .domain import Projection


@dataclass(frozen=True)
class TradePackage:
    send_player_keys: tuple[str, ...]
    receive_player_keys: tuple[str, ...]
    ros_delta: float
    playoff_delta: float
    structural_delta: float
    risk_delta: float
    score: float

    @property
    def eligible(self) -> bool:
        return (
            self.ros_delta > 0
            and self.playoff_delta >= -2
            and self.structural_delta >= 0
            and self.risk_delta <= 2
        )


def evaluate_trade(
    *,
    send: list[Projection],
    receive: list[Projection],
    roster_need: dict[str, float],
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
    score = ros_delta + playoff_delta * 0.5 + structural_delta * 2 - risk_delta
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
    limit: int = 5,
) -> list[tuple[str, TradePackage]]:
    proposals = []
    for opponent_team_key, opponent_roster in opponents.items():
        for outgoing in roster:
            for incoming in opponent_roster:
                package = evaluate_trade(
                    send=[outgoing],
                    receive=[incoming],
                    roster_need=roster_need,
                )
                if package.eligible:
                    proposals.append((opponent_team_key, package))
    proposals.sort(key=lambda item: item[1].score, reverse=True)
    return proposals[:limit]


def _need_position(position: str) -> str:
    if position in {"IDP", "DL", "LB", "DB", "CB", "S", "DE", "DT"}:
        return "D"
    return position


__all__ = ["TradePackage", "evaluate_trade", "rank_outbound_trades"]
