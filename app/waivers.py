from __future__ import annotations

from dataclasses import dataclass

from .domain import Projection
from .policy import PolicyEngine


@dataclass(frozen=True)
class FabRecommendation:
    add_player_key: str
    drop_player_key: str | None
    bid: int
    net_ros_gain: float
    summary: str


def rank_fab_moves(
    *,
    free_agents: list[Projection],
    roster: list[Projection],
    budget_remaining: int,
    policy: PolicyEngine,
    ros_ranks: dict[str, int],
    manually_protected: set[str],
    starter_vacancies: set[str],
    limit: int = 5,
) -> list[FabRecommendation]:
    droppable = [
        player
        for player in roster
        if not policy.is_protected(
            player, ros_ranks.get(player.player_key), manually_protected
        )
    ]
    recommendations = []
    for candidate in free_agents:
        same_position = [
            player for player in droppable if player.position == candidate.position
        ]
        drop = min(
            same_position or droppable,
            key=lambda player: player.ros_points,
            default=None,
        )
        drop_value = drop.ros_points if drop else 0.0
        gain = round(candidate.ros_points - drop_value, 2)
        if gain <= 0:
            continue
        vacancy = candidate.position in starter_vacancies
        cap = policy.fab_bid_cap(budget_remaining, vacancy)
        bid = min(cap, max(1, round(gain / max(candidate.ros_points, 1) * 100)))
        recommendations.append(
            FabRecommendation(
                add_player_key=candidate.player_key,
                drop_player_key=drop.player_key if drop else None,
                bid=bid,
                net_ros_gain=gain,
                summary=f"Add {candidate.name}"
                + (f", drop {drop.name}" if drop else "")
                + f" for {gain:.1f} ROS points",
            )
        )
    recommendations.sort(
        key=lambda recommendation: recommendation.net_ros_gain, reverse=True
    )
    return recommendations[:limit]


__all__ = ["FabRecommendation", "rank_fab_moves"]
