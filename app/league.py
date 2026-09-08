from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


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
