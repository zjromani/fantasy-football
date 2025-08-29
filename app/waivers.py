from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from .models import LeagueSettings
from .store import migrate
from .inbox import notify
from .store import get_connection


@dataclass
class WaiverCandidate:
    player_id: str
    name: str
    position: str
    proj_base: float
    trend_last2: float  # recent usage/points delta
    schedule_difficulty_next4: float  # 0=easy .. 3=hard


@dataclass
class WaiverRecommendation:
    player_id: str
    name: str
    position: str
    score: float
    faab_min: int
    faab_max: int


def _positional_gaps(settings: LeagueSettings, current_starters_count: Dict[str, int]) -> Dict[str, int]:
    limits = settings.positional_limits
    targets = {"QB": limits.qb, "RB": limits.rb, "WR": limits.wr, "TE": limits.te}
    gaps: Dict[str, int] = {}
    for pos, target in targets.items():
        have = int(current_starters_count.get(pos, 0))
        gaps[pos] = max(0, target - have)
    return gaps


def _score_candidate(c: WaiverCandidate, gaps: Dict[str, int]) -> float:
    # Simple heuristic score
    base = c.proj_base
    trend = 0.5 * c.trend_last2
    schedule = (2.0 - c.schedule_difficulty_next4) * 1.0
    gap_bonus = 2.0 if gaps.get(c.position.upper(), 0) > 0 else 0.0
    return round(base + trend + schedule + gap_bonus, 2)


def _faab_bounds(score: float, faab_remaining: int, waiver_type: str) -> Tuple[int, int]:
    if waiver_type != "faab" or faab_remaining <= 0:
        return (0, 0)
    min_bid = max(1, int(round(score * 0.6)))
    max_bid = max(min_bid + 1, int(round(score * 0.9)))
    min_bid = min(min_bid, faab_remaining)
    max_bid = min(max_bid, faab_remaining)
    return (min_bid, max_bid)


def rank_free_agents(
    *,
    settings: LeagueSettings,
    current_starters_count: Dict[str, int],
    free_agents: List[Dict],
    faab_remaining: int,
    waiver_type: str = "faab",
    top_n: int = 5,
) -> List[WaiverRecommendation]:
    gaps = _positional_gaps(settings, current_starters_count)
    recs: List[WaiverRecommendation] = []
    for fa in free_agents:
        c = WaiverCandidate(
            player_id=str(fa["id"]),
            name=str(fa.get("name", fa["id"])),
            position=str(fa.get("position", "UTIL")).upper(),
            proj_base=float(fa.get("proj_base", 0.0)),
            trend_last2=float(fa.get("trend_last2", 0.0)),
            schedule_difficulty_next4=float(fa.get("schedule_next4", 1.5)),
        )
        score = _score_candidate(c, gaps)
        bmin, bmax = _faab_bounds(score, faab_remaining, waiver_type)
        recs.append(WaiverRecommendation(c.player_id, c.name, c.position, score, bmin, bmax))
    recs.sort(key=lambda r: (r.score, r.faab_max), reverse=True)
    return recs[:top_n]


def persist_recommendations(recs: List[WaiverRecommendation]) -> int:
    if not recs:
        return notify("waivers", "No waiver targets", "No viable free agents were identified.", {})
    connection = get_connection()
    try:
        cur = connection.cursor()
        for r in recs:
            payload = {
                "player_id": r.player_id,
                "position": r.position,
                "score": r.score,
                "faab_min": r.faab_min,
                "faab_max": r.faab_max,
            }
            cur.execute(
                "INSERT INTO recommendations(kind, title, body, payload) VALUES(?, ?, ?, ?)",
                (
                    "waivers",
                    f"Add {r.name} ({r.position})",
                    f"Score {r.score:.1f}. FAAB {r.faab_min}-{r.faab_max}",
                    __import__("json").dumps(payload),
                ),
            )
        connection.commit()
    finally:
        connection.close()

    # Build one inbox message
    lines = [f"{i+1}. {r.name} ({r.position}) — score {r.score:.1f}, FAAB {r.faab_min}-{r.faab_max}" for i, r in enumerate(recs)]
    body = "\n".join(lines)
    msg_id = notify("waivers", "Waiver targets", body, {"items": [r.__dict__ for r in recs]})
    return msg_id


def recommend_waivers(
    *,
    settings: LeagueSettings,
    current_starters_count: Dict[str, int],
    free_agents: List[Dict],
    faab_remaining: int,
    waiver_type: str = "faab",
    top_n: int = 5,
) -> Tuple[List[WaiverRecommendation], int]:
    recs = rank_free_agents(
        settings=settings,
        current_starters_count=current_starters_count,
        free_agents=free_agents,
        faab_remaining=faab_remaining,
        waiver_type=waiver_type,
        top_n=top_n,
    )
    message_id = persist_recommendations(recs)
    return recs, message_id


__all__ = [
    "WaiverRecommendation",
    "rank_free_agents",
    "persist_recommendations",
    "recommend_waivers",
]


