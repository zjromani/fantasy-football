from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .domain import ActionKind, Projection
from .league import LeagueConfig


@dataclass(frozen=True)
class PolicyResult:
    allowed: bool
    requires_approval: bool
    reasons: tuple[str, ...]


class PolicyEngine:
    def __init__(self, league: LeagueConfig) -> None:
        self.league = league

    def evaluate(
        self,
        kind: ActionKind,
        *,
        source_updated_at: datetime,
        writes_enabled: bool,
        dry_run: bool,
        safe_correction: bool = False,
    ) -> PolicyResult:
        reasons = []
        stale = datetime.now(UTC) - source_updated_at > self._max_age(kind)
        if stale and not (kind in {"lineup", "ir"} and safe_correction):
            reasons.append("stale data blocks this action")
        if not writes_enabled:
            reasons.append("write kill switch is disabled")
        if dry_run:
            reasons.append("dry-run mode")
        requires_approval = kind in {"fab", "trade_accept", "trade_propose"}
        return PolicyResult(
            allowed=(not stale or safe_correction) and writes_enabled and not dry_run,
            requires_approval=requires_approval,
            reasons=tuple(reasons),
        )

    def fab_bid_cap(self, budget_remaining: int, starter_vacancy: bool) -> int:
        percent = (
            self.league.fab.starter_vacancy_max_percent
            if starter_vacancy
            else self.league.fab.standard_max_percent
        )
        return max(0, int(budget_remaining * percent / 100))

    def is_protected(
        self, player: Projection, ros_rank: int | None, manual: set[str]
    ) -> bool:
        return (
            player.player_key in manual
            or player.player_key in self.league.protected_player_keys
            or (ros_rank is not None and ros_rank <= 30)
        )

    def _max_age(self, kind: ActionKind) -> timedelta:
        if kind in {"lineup", "ir", "fab"}:
            return timedelta(hours=self.league.freshness.weekly_projections_hours)
        return timedelta(hours=self.league.freshness.rest_of_season_hours)
