from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain import Projection, RosterPlayer
from app.league import GmProfile, LeagueConfig, builtin_gm_profiles
from app.lineup import optimize_lineup
from app.policy import PolicyEngine
from app.trades import evaluate_trade, rank_outbound_trades
from app.value import score_projected_stats
from app.waivers import rank_fab_moves


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

    balanced = GmProfile()
    trade = evaluate_trade(
        send=[outgoing],
        receive=[incoming],
        roster_need={"RB": 1},
        profile=balanced,
    )

    assert trade.ros_delta > 0
    assert not trade.eligible(balanced)


def test_win_aggressive_profile_raises_fab_bids_and_allows_need_trades() -> None:
    aggressive = builtin_gm_profiles()["win_aggressive"]
    policy = PolicyEngine(
        LeagueConfig.model_validate(
            {
                **league().model_dump(),
                "profile": "win_aggressive",
            }
        )
    )
    assert policy.fab_bid_cap(100, starter_vacancy=False) == 25

    steady = projection("steady", "RB", 10)
    risky = Projection(
        player_key="risky",
        name="risky",
        position="RB",
        nfl_team="TST",
        week_points=12,
        ros_points=steady.ros_points + 5,
        playoff_points=steady.playoff_points,
        volatility=3,
    )
    trade = evaluate_trade(
        send=[steady], receive=[risky], roster_need={"RB": 2}, profile=aggressive
    )
    assert trade.eligible(aggressive)


def test_two_for_one_trade_proposal_when_aggressive() -> None:
    aggressive = builtin_gm_profiles()["win_aggressive"]
    depth_a = projection("a", "RB", 6)
    depth_b = projection("b", "WR", 5)
    depth_a = Projection(
        player_key="a",
        name="a",
        position="RB",
        nfl_team="TST",
        week_points=6,
        ros_points=40,
        playoff_points=10,
    )
    depth_b = Projection(
        player_key="b",
        name="b",
        position="WR",
        nfl_team="TST",
        week_points=5,
        ros_points=35,
        playoff_points=8,
    )
    star = Projection(
        player_key="star",
        name="star",
        position="RB",
        nfl_team="TST",
        week_points=18,
        ros_points=120,
        playoff_points=30,
        volatility=1,
    )
    proposals = rank_outbound_trades(
        roster=[depth_a, depth_b],
        opponents={"opp.t.1": [star]},
        roster_need={"RB": 2.5},
        profile=aggressive,
        tradable_player_keys={"a", "b"},
    )
    two_for_one = [
        package for _, package in proposals if len(package.send_player_keys) == 2
    ]
    assert two_for_one


def test_lineup_upside_weight_prefers_higher_ceiling() -> None:
    roster = [
        RosterPlayer("safe", ("RB",), "RB"),
        RosterPlayer("boom", ("RB",), "BN"),
        RosterPlayer("wr", ("WR",), "W/R/T"),
    ]
    projections = {
        "safe": Projection(
            player_key="safe",
            name="safe",
            position="RB",
            nfl_team="TST",
            week_points=10.0,
            ros_points=100,
            volatility=0,
        ),
        "boom": Projection(
            player_key="boom",
            name="boom",
            position="RB",
            nfl_team="TST",
            week_points=9.0,
            ros_points=100,
            volatility=8.0,
        ),
        "wr": projection("wr", "WR", 12),
    }
    conservative = optimize_lineup(
        league().model_copy(update={"profile": "balanced"}),
        roster,
        projections,
        upside_weight=0.0,
    )
    aggressive = optimize_lineup(
        league().model_copy(update={"profile": "win_aggressive"}),
        roster,
        projections,
        upside_weight=0.15,
    )
    assert conservative.positions["safe"] == "RB"
    assert aggressive.positions["boom"] == "RB"


def test_aggressive_fab_bid_uses_multiplier() -> None:
    aggressive = builtin_gm_profiles()["win_aggressive"]
    league_config = LeagueConfig.model_validate(
        {**league().model_dump(), "profile": "win_aggressive"}
    )
    policy = PolicyEngine(league_config)
    free_agent = projection("fa", "RB", 16, status="")
    free_agent = Projection(
        player_key="fa",
        name="fa",
        position="RB",
        nfl_team="TST",
        week_points=16,
        ros_points=170,
    )
    roster_player = Projection(
        player_key="drop",
        name="drop",
        position="RB",
        nfl_team="TST",
        week_points=8,
        ros_points=100,
    )
    balanced_moves = rank_fab_moves(
        free_agents=[free_agent],
        roster=[roster_player],
        budget_remaining=100,
        policy=policy,
        ros_ranks={"drop": 80},
        manually_protected=set(),
        starter_vacancies=set(),
        profile=GmProfile(),
    )
    aggressive_moves = rank_fab_moves(
        free_agents=[free_agent],
        roster=[roster_player],
        budget_remaining=100,
        policy=policy,
        ros_ranks={"drop": 80},
        manually_protected=set(),
        starter_vacancies=set(),
        profile=aggressive,
    )
    assert aggressive_moves[0].bid >= balanced_moves[0].bid
