from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

ActionKind = Literal["lineup", "ir", "fab", "trade_accept", "trade_propose"]


@dataclass(frozen=True)
class Projection:
    player_key: str
    name: str
    position: str
    nfl_team: str
    week_points: float
    ros_points: float
    playoff_points: float = 0.0
    injury_status: str = ""
    is_active: bool = True
    bye_week: int | None = None
    volatility: float = 0.0
    source_updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_updated_at"] = self.source_updated_at.isoformat()
        return payload


@dataclass(frozen=True)
class RosterPlayer:
    player_key: str
    eligible_positions: tuple[str, ...]
    selected_position: str
    locked: bool = False


@dataclass(frozen=True)
class Decision:
    kind: ActionKind
    score: float
    summary: str
    payload: dict[str, Any]
    source_updated_at: datetime
    requires_approval: bool
    policy_reasons: tuple[str, ...] = ()
    inputs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_updated_at"] = self.source_updated_at.isoformat()
        return payload
