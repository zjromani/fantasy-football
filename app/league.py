from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class GmProfile(BaseModel):
    """GM preset from built-ins and league.yml overrides."""

    trade_min_ros_delta: float = 0.0
    trade_playoff_delta_floor: float = -2.0
    trade_structural_delta_floor: float = 0.0
    trade_max_risk_delta: float = 2.0
    trade_proposal_limit: int = 5
    trade_two_for_one_enabled: bool = False

    fab_bid_multiplier: float = 1.0
    fab_min_ros_gain: float = 0.0
    fab_standard_max_percent_override: int | None = None
    fab_starter_vacancy_max_percent_override: int | None = None

    protected_ros_rank: int = 30
    lineup_upside_weight: float = 0.0


def builtin_gm_profiles() -> dict[str, GmProfile]:
    return {
        "balanced": GmProfile(),
        "win_aggressive": GmProfile(
            trade_min_ros_delta=-1.0,
            trade_playoff_delta_floor=-5.0,
            trade_structural_delta_floor=-0.5,
            trade_max_risk_delta=4.0,
            trade_proposal_limit=10,
            trade_two_for_one_enabled=True,
            fab_bid_multiplier=1.35,
            fab_min_ros_gain=0.5,
            fab_standard_max_percent_override=25,
            fab_starter_vacancy_max_percent_override=55,
            protected_ros_rank=24,
            lineup_upside_weight=0.15,
        ),
    }


class FabPolicy(BaseModel):
    weekly_claim_limit: int = 2
    standard_max_percent: int = 15
    starter_vacancy_max_percent: int = 40


class FreshnessPolicy(BaseModel):
    yahoo_minutes: int = 15
    weekly_projections_hours: int = 24
    rest_of_season_hours: int = 72


class LeagueConfig(BaseModel):
    name: str
    league_id: str
    league_key: str | None = None
    team_key: str | None = None
    roster: dict[str, int]
    scoring: dict[str, float]
    validation_scoring: dict[str, float] = Field(default_factory=dict)
    playoff_weeks: list[int] = Field(default_factory=lambda: [15, 16, 17])
    trade_deadline: str | None = None
    fab: FabPolicy = Field(default_factory=FabPolicy)
    freshness: FreshnessPolicy = Field(default_factory=FreshnessPolicy)
    protected_player_keys: list[str] = Field(default_factory=list)
    profile: str = "win_aggressive"
    profiles: dict[str, GmProfile] = Field(default_factory=dict)

    def gm_profile(self) -> GmProfile:
        merged = dict(builtin_gm_profiles())
        merged.update(self.profiles)
        if self.profile not in merged:
            raise ValueError(f"Unknown GM profile {self.profile!r}")
        return merged[self.profile]

    @classmethod
    def load(cls, path: str | Path) -> LeagueConfig:
        payload = yaml.safe_load(Path(path).read_text())
        return cls.model_validate(payload)

    def validate_yahoo_settings(self, actual: dict[str, Any]) -> list[str]:
        drift = []
        actual_roster = actual.get("roster", {})
        for slot, expected_count in self.roster.items():
            actual_count = actual_roster.get(slot)
            if actual_count is None:
                drift.append(f"roster.{slot}: missing from Yahoo settings")
            elif int(actual_count) != expected_count:
                drift.append(
                    f"roster.{slot}: expected {expected_count}, got {actual_count}"
                )
        actual_scoring = actual.get("scoring", {})
        for stat, expected_value in self.validation_scoring.items():
            actual_value = actual_scoring.get(stat)
            if actual_value is None:
                drift.append(f"scoring.{stat}: missing from Yahoo settings")
            elif float(actual_value) != expected_value:
                drift.append(
                    f"scoring.{stat}: expected {expected_value}, got {actual_value}"
                )
        return drift
