"""
Test AI prompts for quality, structure, and constraint enforcement.
"""
import pytest
from app.ai.prompts import (
    build_waiver_prompt,
    build_trade_prompt,
    build_lineup_prompt,
    WAIVER_SYSTEM,
    TRADE_SYSTEM,
    LINEUP_SYSTEM,
)


def test_waiver_prompt_structure():
    """Test waiver prompt includes all required sections."""
    league_settings = {
        "scoring": {"ppr": 1.0, "pass_td": 4, "rush_td": 6},
        "roster_slots": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BENCH": 6},
    }
    
    my_roster = [
        {"name": "Patrick Mahomes", "position": "QB", "team": "KC", "slot": "QB", "projection": 22.0, "status": ""},
        {"name": "Lamar Jackson", "position": "QB", "team": "Bal", "slot": "BN", "projection": 0.0, "status": "O"},
    ]
    
    free_agents = [
        {"name": "Matthew Stafford", "position": "QB", "team": "LAR", "projection": 18.0, "status": "", "bye_week": 6},
        {"name": "Tua Tagovailoa", "position": "QB", "team": "Mia", "projection": 16.0, "status": "", "bye_week": 7},
    ]
    
    prompt = build_waiver_prompt(
        league_settings=league_settings,
        my_roster=my_roster,
        free_agents=free_agents,
        current_week=5,
        faab_remaining=85
    )
    
    # Check all required sections are present
    assert "LEAGUE SETTINGS" in prompt
    assert "MY ROSTER" in prompt
    assert "FREE AGENTS" in prompt
    assert "TASK" in prompt
    assert "CONSTRAINTS" in prompt
    assert "OUTPUT FORMAT" in prompt
    
    # Check key data is included
    assert "PPR: 1.0" in prompt
    assert "$85" in prompt  # FAAB budget
    assert "Patrick Mahomes" in prompt
    assert "Matthew Stafford" in prompt
    assert "Lamar Jackson" in prompt
    
    # Check constraints are explicit
    assert "Only recommend players from the FREE AGENTS list" in prompt
    assert "Do not suggest dropping starters" in prompt
    assert 'Skip players with status "O"' in prompt


def test_trade_prompt_structure():
    """Test trade prompt includes mutual benefit requirement."""
    league_settings = {
        "scoring": {"ppr": 1.0},
        "roster_slots": {"QB": 1, "RB": 2, "WR": 2},
    }
    
    my_roster = [
        {"name": "Alvin Kamara", "position": "RB", "team": "NO", "slot": "RB", "projection": 15.0},
        {"name": "Puka Nacua", "position": "WR", "team": "LAR", "slot": "WR", "projection": 18.0},
    ]
    
    opponent_roster = [
        {"name": "Tyreek Hill", "position": "WR", "team": "Mia", "projection": 20.0},
        {"name": "Saquon Barkley", "position": "RB", "team": "NYG", "projection": 17.0},
    ]
    
    prompt = build_trade_prompt(
        league_settings=league_settings,
        my_roster=my_roster,
        opponent_roster=opponent_roster,
        opponent_name="Max",
        current_week=5
    )
    
    # Check structure
    assert "LEAGUE SETTINGS" in prompt
    assert "MY ROSTER" in prompt
    assert "OPPONENT'S ROSTER (Max)" in prompt
    assert "TASK" in prompt
    assert "CONSTRAINTS" in prompt
    
    # Check key requirements
    assert "2 fair trade ideas" in prompt
    assert "acceptance_probability" in prompt
    assert "net_points_gain" in prompt
    assert "Both sides must gain" in prompt
    assert "Do not trade away my highest-projected starter" in prompt
    
    # Check data is present
    assert "Alvin Kamara" in prompt
    assert "Tyreek Hill" in prompt


def test_lineup_prompt_structure():
    """Test lineup prompt respects positional constraints."""
    league_settings = {
        "scoring": {"ppr": 1.0},
        "roster_slots": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BENCH": 6},
    }
    
    my_roster = [
        {"name": "Josh Allen", "position": "QB", "team": "Buf", "slot": "QB", "projection": 24.0, "opponent": "KC", "status": ""},
        {"name": "Derrick Henry", "position": "RB", "team": "Ten", "slot": "RB", "projection": 16.0, "opponent": "Jax", "status": ""},
        {"name": "Austin Ekeler", "position": "RB", "team": "Was", "slot": "BN", "projection": 12.0, "opponent": "NYG", "status": ""},
    ]
    
    prompt = build_lineup_prompt(
        league_settings=league_settings,
        my_roster=my_roster,
        current_week=5
    )
    
    # Check structure
    assert "LEAGUE SETTINGS" in prompt
    assert "MY ROSTER (Current Lineup)" in prompt
    assert "TASK" in prompt
    assert "CONSTRAINTS" in prompt
    
    # Check key requirements
    assert "Optimize my starting lineup" in prompt
    assert "starters" in prompt
    assert "bench" in prompt
    assert "swaps" in prompt
    assert "Delta points" in prompt
    
    # Check constraints
    assert "Respect positional eligibility and slot counts" in prompt
    assert 'Do not start players with status "O"' in prompt
    
    # Check data
    assert "Josh Allen" in prompt
    assert "Derrick Henry" in prompt
    assert "Current Slot: QB" in prompt


def test_system_prompts_exist():
    """Test that all system prompts are defined."""
    assert WAIVER_SYSTEM
    assert TRADE_SYSTEM
    assert LINEUP_SYSTEM
    
    # Check they contain key phrases
    assert "analytics engine" in WAIVER_SYSTEM
    assert "do not hallucinate" in WAIVER_SYSTEM
    assert "trade advisor" in TRADE_SYSTEM
    assert "one-sided" in TRADE_SYSTEM.lower()
    assert "lineup optimizer" in LINEUP_SYSTEM
    assert "eligible players" in LINEUP_SYSTEM


def test_waiver_prompt_limits_free_agents():
    """Test that waiver prompt limits FA list to top 50."""
    league_settings = {"scoring": {"ppr": 1.0}, "roster_slots": {}}
    my_roster = []
    
    # Create 100 free agents
    free_agents = [
        {"name": f"Player {i}", "position": "RB", "team": "??", "projection": 10.0}
        for i in range(100)
    ]
    
    prompt = build_waiver_prompt(
        league_settings=league_settings,
        my_roster=my_roster,
        free_agents=free_agents,
        current_week=5,
        faab_remaining=100
    )
    
    # Should only include top 50
    assert "Top 50 Available" in prompt
    assert "Player 0" in prompt
    assert "Player 49" in prompt
    # Should not include beyond 50
    assert "Player 99" not in prompt


def test_trade_prompt_with_tendencies():
    """Test that manager tendencies are included when provided."""
    league_settings = {"scoring": {"ppr": 1.0}}
    my_roster = []
    opponent_roster = []
    
    tendencies = {
        "trade_accept_rate": "30%",
        "position_bias": "Prefers RBs",
        "action_time": "Usually trades on Tuesdays"
    }
    
    prompt = build_trade_prompt(
        league_settings=league_settings,
        my_roster=my_roster,
        opponent_roster=opponent_roster,
        opponent_name="Chris",
        current_week=5,
        manager_tendencies=tendencies
    )
    
    assert "OPPONENT TENDENCIES (Chris)" in prompt
    assert "30%" in prompt
    assert "Prefers RBs" in prompt
    assert "Tuesdays" in prompt


def test_lineup_prompt_with_weather():
    """Test that weather context is included when provided."""
    league_settings = {"scoring": {"ppr": 1.0}, "roster_slots": {}}
    my_roster = []
    
    weather = {
        "KC vs BUF": "Heavy rain, 20mph winds",
        "LAR vs SF": "Perfect conditions"
    }
    
    prompt = build_lineup_prompt(
        league_settings=league_settings,
        my_roster=my_roster,
        current_week=5,
        weather=weather
    )
    
    assert "WEATHER ALERTS" in prompt
    assert "Heavy rain" in prompt
    assert "Perfect conditions" in prompt


if __name__ == "__main__":
    # Run a sample test to see prompt output
    print("=" * 70)
    print("SAMPLE WAIVER PROMPT OUTPUT")
    print("=" * 70)
    
    league_settings = {
        "scoring": {"ppr": 1.0, "pass_td": 4, "rush_td": 6},
        "roster_slots": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BENCH": 6},
    }
    
    my_roster = [
        {"name": "Patrick Mahomes", "position": "QB", "team": "KC", "slot": "QB", "projection": 22.0, "status": ""},
        {"name": "Lamar Jackson", "position": "QB", "team": "Bal", "slot": "BN", "projection": 0.0, "status": "O"},
        {"name": "Alvin Kamara", "position": "RB", "team": "NO", "slot": "RB", "projection": 15.0, "status": ""},
    ]
    
    free_agents = [
        {"name": "Matthew Stafford", "position": "QB", "team": "LAR", "projection": 18.0, "status": "", "bye_week": 6},
        {"name": "Justice Hill", "position": "RB", "team": "Bal", "projection": 8.0, "status": "", "bye_week": 14},
    ]
    
    prompt = build_waiver_prompt(
        league_settings=league_settings,
        my_roster=my_roster,
        free_agents=free_agents,
        current_week=5,
        faab_remaining=85
    )
    
    print(prompt)

