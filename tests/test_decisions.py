from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain import Projection, RosterPlayer
from app.league import LeagueConfig
from app.lineup import optimize_lineup
from app.policy import PolicyEngine
from app.trades import evaluate_trade
from app.value import score_projected_stats


def league() -> LeagueConfig:
    return LeagueConfig.model_validate(
        {
            "name": "Test",
            "league_id": "1",
            "roster": {"RB": 1, "W/R/T": 1, "BN": 2},
            "scoring": {"rush_yd": 0.125, "reception": 0.5},
            "validation_scoring": {"rush_yd": 0.125, "reception": 0.5},
        }
    )


def projection(key: str, position: str, points: float, status: str = "") -> Projection:
    return Projection(
        player_key=key,
        name=key,
        position=position,
        nfl_team="TST",
        week_points=points,
        ros_points=points * 10,
        injury_status=status,
    )


def test_lineup_is_whole_roster_legal_and_questionable_players_are_eligible() -> None:
    roster = [
        RosterPlayer("rb1", ("RB",), "RB"),
        RosterPlayer("rb2", ("RB",), "BN"),
        RosterPlayer("wr", ("WR",), "W/R/T"),
        RosterPlayer("out", ("WR",), "BN"),
    ]
    projections = {
        "rb1": projection("rb1", "RB", 8),
        "rb2": projection("rb2", "RB", 14, "Q"),
        "wr": projection("wr", "WR", 12),
        "out": projection("out", "WR", 30, "OUT"),
    }

    plan = optimize_lineup(league(), roster, projections)

    assert plan.positions["rb2"] == "RB"
    assert plan.positions["wr"] == "W/R/T"
    assert plan.positions["out"] == "BN"


def test_stale_data_blocks_transactions_but_allows_safe_lineup_correction() -> None:
    policy = PolicyEngine(league())
    stale = datetime.now(UTC) - timedelta(days=4)

    fab = policy.evaluate(
        "fab", source_updated_at=stale, writes_enabled=True, dry_run=False
    )
    lineup = policy.evaluate(
        "lineup",
        source_updated_at=stale,
        writes_enabled=True,
        dry_run=False,
        safe_correction=True,
    )

    assert not fab.allowed
    assert lineup.allowed


def test_custom_eight_yards_per_rushing_point() -> None:
    points = score_projected_stats(
        {"rush_yd": 80, "reception": 4},
        {"rush_yd": 0.125, "reception": 0.5},
    )
    assert points == 12

    bonus_points = score_projected_stats(
        {"rush_yd": 160, "reception": 4},
        {
            "rush_yd": 0.125,
            "reception": 0.5,
            "rush_yd_bonus_100": 1,
            "rush_yd_bonus_150": 2,
            "rush_yd_bonus_200": 3,
        },
    )
    assert bonus_points == 24


def test_league_settings_drift_is_explicit() -> None:
    drift = league().validate_yahoo_settings(
        {
            "roster": {"RB": 2, "W/R/T": 1, "BN": 2},
            "scoring": {"rush_yd": 0.1, "reception": 0.5},
        }
    )

    assert "roster.RB: expected 1, got 2" in drift
    assert "scoring.rush_yd: expected 0.125, got 0.1" in drift


def test_trade_rejects_material_risk_regression() -> None:
    outgoing = projection("steady", "RB", 10)
    incoming = Projection(
        player_key="risky",
        name="risky",
        position="RB",
        nfl_team="TST",
        week_points=12,
        ros_points=outgoing.ros_points + 10,
        playoff_points=outgoing.playoff_points,
        volatility=5,
    )

    trade = evaluate_trade(send=[outgoing], receive=[incoming], roster_need={"RB": 1})

    assert trade.ros_delta > 0
    assert not trade.eligible
