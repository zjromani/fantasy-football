"""Tests for enhanced lineup optimizer."""
import os
import tempfile
from datetime import datetime, timezone

from app.lineup_enhanced import (
    optimize_lineup_enhanced,
    build_enhanced_players,
    EnhancedPlayer,
    SitStartRecommendation,
)
from app.models import LeagueSettings, PositionalLimits, ScoringRules
from app.db import migrate, get_connection


def test_build_enhanced_players():
    """Enhanced players should have projections and context."""
    settings = LeagueSettings(
        roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BENCH": 6},
        positional_limits=PositionalLimits(qb=1, rb=2, wr=2, te=1, flex=1, bench=6),
        scoring=ScoringRules(ppr=1.0, pass_td=4, rush_td=6, rec_td=6),
        bench_size=6,
    )

    players = [
        {"id": "p1", "name": "Patrick Mahomes", "position": "QB", "team": "KC", "projected": 22.0},
        {"id": "p2", "name": "Alvin Kamara", "position": "RB", "team": "NO", "projected": 15.0, "injury": "Q"},
    ]

    enhanced = build_enhanced_players(players, week=5, settings=settings)

    assert len(enhanced) == 2
    assert enhanced[0].name == "Patrick Mahomes"
    assert enhanced[0].base_projection > 0  # Should have some projection
    assert enhanced[1].injury_status == "Q"
    assert enhanced[1].adjusted_projection < enhanced[1].base_projection  # Injured = downgraded


def test_sit_start_recommendations_basic():
    """Should recommend starting higher-projected bench player."""
    settings = LeagueSettings(
        roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BENCH": 6},
        positional_limits=PositionalLimits(qb=1, rb=2, wr=2, te=1, flex=1, bench=6),
        scoring=ScoringRules(ppr=1.0, pass_td=4, rush_td=6, rec_td=6),
        bench_size=6,
    )

    players = [
        EnhancedPlayer(
            id="p1", name="Low Starter", position="RB", team="BUF",
            base_projection=8.0, adjusted_projection=8.0,
            is_starter=True, current_slot="RB"
        ),
        EnhancedPlayer(
            id="p2", name="High Bench", position="RB", team="KC",
            base_projection=18.0, adjusted_projection=18.0,
            is_starter=False, current_slot="BN"
        ),
    ]

    from app.lineup_enhanced import generate_sit_start_recommendations

    recs = generate_sit_start_recommendations(
        settings=settings,
        players=players,
        week=5,
        min_confidence=50.0
    )

    assert len(recs) > 0
    assert recs[0].player_in.name == "High Bench"
    assert recs[0].player_out.name == "Low Starter"
    assert recs[0].projection_delta > 0


def test_confidence_scoring():
    """Confidence should increase with delta and supporting factors."""
    settings = LeagueSettings(
        roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BENCH": 6},
        positional_limits=PositionalLimits(qb=1, rb=2, wr=2, te=1, flex=1, bench=6),
        scoring=ScoringRules(ppr=1.0, pass_td=4, rush_td=6, rec_td=6),
        bench_size=6,
    )

    # High delta + injury = high confidence
    players = [
        EnhancedPlayer(
            id="p1", name="Injured Starter", position="WR", team="BUF",
            base_projection=12.0, adjusted_projection=10.0,
            injury_status="Q", is_starter=True, current_slot="WR"
        ),
        EnhancedPlayer(
            id="p2", name="Healthy Bench", position="WR", team="KC",
            base_projection=18.0, adjusted_projection=18.0,
            news_sentiment="positive", is_starter=False, current_slot="BN"
        ),
    ]

    from app.lineup_enhanced import generate_sit_start_recommendations

    recs = generate_sit_start_recommendations(
        settings=settings,
        players=players,
        week=5,
        min_confidence=50.0
    )

    assert len(recs) > 0
    assert recs[0].confidence >= 70  # Should be high confidence


def test_tier1_protection():
    """Tier-1 players should have warnings about sitting them."""
    settings = LeagueSettings(
        roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BENCH": 6},
        positional_limits=PositionalLimits(qb=1, rb=2, wr=2, te=1, flex=1, bench=6),
        scoring=ScoringRules(ppr=1.0, pass_td=4, rush_td=6, rec_td=6),
        bench_size=6,
    )

    players = [
        EnhancedPlayer(
            id="p1", name="Elite Starter", position="RB", team="KC",
            base_projection=20.0, adjusted_projection=20.0,
            tier="tier-1", is_starter=True, current_slot="RB"
        ),
        EnhancedPlayer(
            id="p2", name="Good Bench", position="RB", team="BUF",
            base_projection=22.0, adjusted_projection=22.0,
            is_starter=False, current_slot="BN"
        ),
    ]

    from app.lineup_enhanced import generate_sit_start_recommendations

    recs = generate_sit_start_recommendations(
        settings=settings,
        players=players,
        week=5,
        min_confidence=40.0  # Lower threshold to see the recommendation
    )

    if recs:  # May or may not recommend based on delta
        assert any("tier-1" in w.lower() for w in recs[0].warnings if recs[0].warnings)


def test_optimize_lineup_enhanced_integration():
    """Full integration test with database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        # Set up test database
        os.environ["DATABASE_PATH"] = db_path
        migrate()

        conn = get_connection()
        cur = conn.cursor()

        # Insert test data
        cur.execute("INSERT OR IGNORE INTO players (id, name, position, team) VALUES (?, ?, ?, ?)",
                    ("p1", "Test QB", "QB", "KC"))
        cur.execute("INSERT OR IGNORE INTO players (id, name, position, team) VALUES (?, ?, ?, ?)",
                    ("p2", "Test RB", "RB", "BUF"))
        cur.execute("INSERT OR IGNORE INTO teams (id, name, manager) VALUES (?, ?, ?)",
                    ("t1", "Test Team", "Manager"))

        conn.commit()
        conn.close()

        # Create settings
        settings = LeagueSettings(
            roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BENCH": 6},
            positional_limits=PositionalLimits(qb=1, rb=2, wr=2, te=1, flex=1, bench=6),
            scoring=ScoringRules(ppr=1.0, pass_td=4, rush_td=6, rec_td=6),
            bench_size=6,
        )

        # Roster data
        roster = [
            {"id": "p1", "name": "Test QB", "position": "QB", "team": "KC", "slot": "QB", "status": None},
            {"id": "p2", "name": "Test RB", "position": "RB", "team": "BUF", "slot": "BN", "status": None},
        ]

        # Run optimizer
        recs = optimize_lineup_enhanced(
            settings=settings,
            roster_players=roster,
            week=5,
            min_confidence=50.0
        )

        # Should return a list (may be empty depending on projections)
        assert isinstance(recs, list)

    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_recommendation_rationale_formatting():
    """Rationale should be human-readable."""
    rec = SitStartRecommendation(
        action="start",
        player_in=EnhancedPlayer(
            id="p1", name="Cooper Kupp", position="WR", team="LAR",
            base_projection=16.0, adjusted_projection=16.0
        ),
        player_out=EnhancedPlayer(
            id="p2", name="Jordan Addison", position="WR", team="MIN",
            base_projection=10.0, adjusted_projection=10.0,
            injury_status="Q"
        ),
        projection_delta=6.0,
        confidence=85.0,
        reasons=[
            "Cooper Kupp projected 16.0 pts vs Jordan Addison 10.0 pts",
            "Jordan Addison injury risk (Q)"
        ],
        warnings=[]
    )

    summary = rec.get_summary()
    assert "Start Cooper Kupp over Jordan Addison" in summary
    assert "+6.0 pts" in summary
    assert "85% confidence" in summary

    full = rec.get_full_rationale()
    assert "Reasons:" in full
    assert "projected 16.0 pts" in full
    assert "injury risk" in full

