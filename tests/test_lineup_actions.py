"""Tests for lineup optimizer actions."""
import os
import tempfile

from app.lineup_actions import (
    format_recommendations_for_inbox,
    optimize_and_post_to_inbox,
)
from app.lineup_enhanced import SitStartRecommendation, EnhancedPlayer
from app.models import LeagueSettings, PositionalLimits, ScoringRules
from app.db import migrate, get_connection


def test_format_recommendations_empty():
    """Empty recommendations should return 'optimal' message."""
    title, body, payload = format_recommendations_for_inbox([], week=5)
    
    assert "Week 5" in title
    assert "optimal" in body.lower()
    assert payload["recommendations"] == []


def test_format_recommendations_with_suggestions():
    """Recommendations should be formatted with reasons and warnings."""
    rec = SitStartRecommendation(
        action="start",
        player_in=EnhancedPlayer(
            id="p1", name="Cooper Kupp", position="WR", team="LAR",
            base_projection=16.0, adjusted_projection=16.0
        ),
        player_out=EnhancedPlayer(
            id="p2", name="Jordan Addison", position="WR", team="MIN",
            base_projection=10.0, adjusted_projection=10.0
        ),
        projection_delta=6.0,
        confidence=85.0,
        reasons=[
            "Cooper Kupp projected 16.0 pts vs Jordan Addison 10.0 pts",
            "Positive news for Kupp"
        ],
        warnings=["Monitor injury report"]
    )
    
    title, body, payload = format_recommendations_for_inbox([rec], week=5)
    
    assert "Week 5" in title
    assert "1 suggestion" in title
    assert "Cooper Kupp" in body
    assert "Jordan Addison" in body
    assert "+6.0 pts" in body
    assert "85% confidence" in body
    assert "Reasons:" in body
    assert "Warnings:" in body
    assert "Monitor injury report" in body
    
    # Check payload
    assert payload["recommendation_count"] == 1
    assert payload["recommendations"][0]["player_in"] == "Cooper Kupp"
    assert payload["recommendations"][0]["delta"] == 6.0
    assert payload["recommendations"][0]["confidence"] == 85.0


def test_format_multiple_recommendations():
    """Multiple recommendations should be numbered."""
    recs = [
        SitStartRecommendation(
            action="start",
            player_in=EnhancedPlayer(id="p1", name="Player A", position="RB", team="KC",
                                     base_projection=15.0, adjusted_projection=15.0),
            player_out=EnhancedPlayer(id="p2", name="Player B", position="RB", team="BUF",
                                      base_projection=10.0, adjusted_projection=10.0),
            projection_delta=5.0,
            confidence=75.0,
            reasons=["Reason 1"],
            warnings=[]
        ),
        SitStartRecommendation(
            action="start",
            player_in=EnhancedPlayer(id="p3", name="Player C", position="WR", team="MIA",
                                     base_projection=14.0, adjusted_projection=14.0),
            player_out=EnhancedPlayer(id="p4", name="Player D", position="WR", team="NYJ",
                                      base_projection=9.0, adjusted_projection=9.0),
            projection_delta=5.0,
            confidence=70.0,
            reasons=["Reason 2"],
            warnings=[]
        ),
    ]
    
    title, body, payload = format_recommendations_for_inbox(recs, week=5)
    
    assert "2 suggestions" in title
    assert "1. Start Player A over Player B" in body
    assert "2. Start Player C over Player D" in body
    assert payload["recommendation_count"] == 2


def test_optimize_and_post_integration():
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
        
        # Insert roster
        cur.execute("INSERT OR REPLACE INTO rosters (team_id, player_id, week, slot, status) VALUES (?, ?, ?, ?, ?)",
                    ("t1", "p1", 5, "QB", None))
        cur.execute("INSERT OR REPLACE INTO rosters (team_id, player_id, week, slot, status) VALUES (?, ?, ?, ?, ?)",
                    ("t1", "p2", 5, "BN", None))
        
        # Insert matchup to set current week
        cur.execute("INSERT INTO matchups (week, team_id, opponent_id) VALUES (?, ?, ?)",
                    (5, "t1", "t2"))
        
        conn.commit()
        conn.close()
        
        # Set team key
        os.environ["YAHOO_TEAM_KEY"] = "nfl.l.12345.t.t1"
        
        # Create settings
        settings = LeagueSettings(
            roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BENCH": 6},
            positional_limits=PositionalLimits(qb=1, rb=2, wr=2, te=1, flex=1, bench=6),
            scoring=ScoringRules(ppr=1.0, pass_td=4, rush_td=6, rec_td=6),
            bench_size=6,
        )
        
        # Run optimizer (will likely find no recommendations with test data)
        msg_id = optimize_and_post_to_inbox(settings, week=5, min_confidence=50.0)
        
        # Should return a message ID
        assert msg_id is not None
        assert isinstance(msg_id, int)
        
        # Check notification was created
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT title, kind FROM notifications WHERE id = ?", (msg_id,))
        result = cur.fetchone()
        conn.close()
        
        assert result is not None
        assert "Lineup Optimizer" in result[0]
        assert result[1] == "lineup"
        
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)

