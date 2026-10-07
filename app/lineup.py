from __future__ import annotations

from dataclasses import dataclass

from .domain import Projection, RosterPlayer
from .league import LeagueConfig


@dataclass(frozen=True)
class LineupPlan:
    positions: dict[str, str]
    projected_points: float
    current_projected_points: float

    @property
    def delta(self) -> float:
        return round(self.projected_points - self.current_projected_points, 2)


def optimize_lineup(
    league: LeagueConfig,
    roster: list[RosterPlayer],
    projections: dict[str, Projection],
    *,
    upside_weight: float | None = None,
) -> LineupPlan:
    if upside_weight is None:
        upside_weight = league.gm_profile().lineup_upside_weight
    starter_slots = []
    for slot, count in league.roster.items():
        if slot not in {"BN", "IR"}:
            starter_slots.extend([slot] * count)

    locked_positions = {
        player.player_key: player.selected_position
        for player in roster
        if player.locked and player.selected_position not in {"BN", "IR"}
    }
    available_slots = list(starter_slots)
    for position in locked_positions.values():
        available_slots.remove(position)

    candidates = [
        player
        for player in roster
        if not player.locked and _can_start(projections.get(player.player_key))
    ]
    best_score = float("-inf")
    best_positions: dict[str, str] = {}

    def assign(
        index: int,
        remaining: list[RosterPlayer],
        positions: dict[str, str],
        score: float,
    ) -> None:
        nonlocal best_score, best_positions
        if index == len(available_slots):
            if score > best_score:
                best_score = score
                best_positions = dict(positions)
            return
        slot = available_slots[index]
        for player in remaining:
            if _eligible(player, slot):
                projection = projections[player.player_key]
                positions[player.player_key] = slot
                assign(
                    index + 1,
                    [candidate for candidate in remaining if candidate != player],
                    positions,
                    score + _starter_value(projection, upside_weight),
                )
                positions.pop(player.player_key)

    locked_score = sum(
        _starter_value(projections[key], upside_weight)
        for key in locked_positions
        if key in projections
    )
    assign(0, candidates, {}, locked_score)
    if best_score == float("-inf"):
        raise ValueError("No legal complete lineup is available")

    positions = {
        player.player_key: (
            player.selected_position
            if player.locked or player.selected_position == "IR"
            else "BN"
        )
        for player in roster
    }
    positions.update(locked_positions)
    positions.update(best_positions)
    current_score = sum(
        _starter_value(projections[player.player_key], upside_weight)
        for player in roster
        if player.selected_position not in {"BN", "IR"}
        and player.player_key in projections
        and _can_start(projections[player.player_key])
    )
    return LineupPlan(positions, round(best_score, 2), round(current_score, 2))


def _starter_value(projection: Projection, upside_weight: float) -> float:
    return projection.week_points + upside_weight * projection.volatility


def _can_start(projection: Projection | None) -> bool:
    return bool(
        projection
        and projection.is_active
        and projection.injury_status.upper() not in {"OUT", "IR", "PUP", "SUSP"}
        and projection.bye_week is None
    )


def _eligible(player: RosterPlayer, slot: str) -> bool:
    eligible = set(player.eligible_positions)
    if slot in eligible:
        return True
    if slot == "W/R/T":
        return bool(eligible & {"WR", "RB", "TE"})
    if slot == "D":
        return bool(eligible & {"D", "DB", "DL", "LB", "S", "CB", "DE", "DT"})
    return False


__all__ = ["LineupPlan", "optimize_lineup"]
