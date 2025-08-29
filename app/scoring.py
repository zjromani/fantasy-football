from __future__ import annotations

from typing import Dict

from .models import LeagueSettings, ScoringRules


def _apply_bonuses(total: float, stats: Dict[str, float], scoring: ScoringRules) -> float:
    for bonus in scoring.bonuses:
        value = float(stats.get(bonus.stat, 0))
        if value >= bonus.threshold:
            total += bonus.points
    return total


def _points_offense(stats: Dict[str, float], scoring: ScoringRules) -> float:
    # Passing
    total = 0.0
    total += scoring.pass_td * float(stats.get("pass_td", 0))
    total += scoring.pass_yd * float(stats.get("pass_yd", 0))
    total += scoring.pass_int * float(stats.get("pass_int", 0))

    # Rushing
    total += scoring.rush_td * float(stats.get("rush_td", 0))
    total += scoring.rush_yd * float(stats.get("rush_yd", 0))

    # Receiving
    total += scoring.rec_td * float(stats.get("rec_td", 0))
    total += scoring.rec_yd * float(stats.get("rec_yd", 0))
    total += scoring.ppr * float(stats.get("rec", 0))

    # Fumbles
    total += scoring.fumble_lost * float(stats.get("fumble_lost", 0))

    total = _apply_bonuses(total, stats, scoring)
    return round(total, 2)


def _bucket_points_allowed(points_allowed: float, table: Dict[str, float]) -> float:
    # Table keys like "0", "1-6", "7-13", ..., "35+"
    for key, pts in table.items():
        if key.endswith("+"):
            low = float(key[:-1])
            if points_allowed >= low:
                return pts
        elif "-" in key:
            low_str, high_str = key.split("-")
            low = float(low_str)
            high = float(high_str)
            if low <= points_allowed <= high:
                return pts
        else:
            exact = float(key)
            if points_allowed == exact:
                return pts
    return 0.0


def _points_dst(stats: Dict[str, float], scoring: ScoringRules) -> float:
    total = 0.0
    total += scoring.dst_td * float(stats.get("td", 0))
    total += scoring.dst_sack * float(stats.get("sack", 0))
    total += scoring.dst_int * float(stats.get("int", 0))
    total += scoring.dst_fum_rec * float(stats.get("fum_rec", 0))
    pa = float(stats.get("points_allowed", 0))
    total += _bucket_points_allowed(pa, scoring.dst_pa)
    return round(total, 2)


def compute_points(position: str, stats: Dict[str, float], settings: LeagueSettings) -> float:
    position_upper = position.upper()
    if position_upper in {"DEF", "DST"}:
        return _points_dst(stats, settings.scoring)
    return _points_offense(stats, settings.scoring)


__all__ = ["compute_points"]


