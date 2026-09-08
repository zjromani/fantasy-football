from __future__ import annotations

from dataclasses import replace

from .domain import Projection


def score_projected_stats(stats: dict[str, float], scoring: dict[str, float]) -> float:
    total = sum(
        value * scoring.get(name, 0)
        for name, value in stats.items()
        if not name.endswith("_allowed")
    )
    total += _tier_bonus(stats, scoring, "pass_yd", (200, 300, 400))
    total += _tier_bonus(stats, scoring, "rush_yd", (100, 150, 200))
    total += _tier_bonus(stats, scoring, "rec_yd", (100, 150, 200))
    total += _tier_bonus(stats, scoring, "return_yd", (100, 150, 200))
    total += _points_allowed_score(stats.get("dst_points_allowed"), scoring)
    return round(total, 2)


def _tier_bonus(
    stats: dict[str, float],
    scoring: dict[str, float],
    stat_name: str,
    thresholds: tuple[int, ...],
) -> float:
    value = stats.get(stat_name, 0)
    earned = 0.0
    for threshold in thresholds:
        if value >= threshold:
            earned = scoring.get(f"{stat_name}_bonus_{threshold}", earned)
    return earned


def _points_allowed_score(
    points_allowed: float | None, scoring: dict[str, float]
) -> float:
    if points_allowed is None:
        return 0
    if points_allowed == 0:
        return scoring.get("dst_pa_0", 0)
    for lower, upper, key in (
        (1, 6, "dst_pa_1_6"),
        (7, 13, "dst_pa_7_13"),
        (14, 20, "dst_pa_14_20"),
        (21, 27, "dst_pa_21_27"),
        (28, 34, "dst_pa_28_34"),
    ):
        if lower <= points_allowed <= upper:
            return scoring.get(key, 0)
    return scoring.get("dst_pa_35_plus", 0)


def value_over_replacement(
    projections: list[Projection], replacement_counts: dict[str, int]
) -> dict[str, float]:
    by_position: dict[str, list[Projection]] = {}
    for projection in projections:
        by_position.setdefault(projection.position, []).append(projection)
    replacements = {}
    for position, players in by_position.items():
        ordered = sorted(players, key=lambda player: player.ros_points, reverse=True)
        index = min(max(replacement_counts.get(position, 1) - 1, 0), len(ordered) - 1)
        replacements[position] = ordered[index].ros_points
    return {
        projection.player_key: round(
            projection.ros_points - replacements.get(projection.position, 0), 2
        )
        for projection in projections
    }


def apply_recent_workload(
    projection: Projection, recent_opportunity_share: float, baseline_share: float
) -> Projection:
    if baseline_share <= 0:
        return projection
    ratio = min(1.25, max(0.75, recent_opportunity_share / baseline_share))
    return replace(
        projection,
        week_points=round(projection.week_points * ratio, 2),
        ros_points=round(projection.ros_points * ratio, 2),
    )
