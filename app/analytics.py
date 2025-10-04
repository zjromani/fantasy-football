"""
League Health Analytics: Team Power Index, Positional Depth, and League Rankings.

This module provides the "Director of Player Personnel" view — surfacing league-wide
dynamics, strengths, weaknesses, and trade opportunities.
"""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from .db import get_connection
from .models import LeagueSettings


@dataclass
class PositionalGrade:
    """Grade for a specific position group."""
    position: str
    starter_avg: float  # Avg projection of starters
    depth_count: int    # Number of bench players at this position
    injury_risk: int    # Count of injured players
    grade: str          # A/B/C/D/F


@dataclass
class TeamHealth:
    """Health snapshot for a single team."""
    team_id: str
    team_name: str
    manager: str
    power_index: float          # Overall roster strength score
    projected_points: float     # Weekly projected points from starters
    positional_grades: Dict[str, PositionalGrade]
    injury_count: int
    bye_exposure: int           # Players on bye this/next week
    rank: int = 0               # Set after comparison


@dataclass
class LeagueSnapshot:
    """Complete league health overview."""
    current_week: int
    total_teams: int
    team_health: List[TeamHealth]
    my_team_id: Optional[str] = None
    
    @property
    def my_team(self) -> Optional[TeamHealth]:
        """Get current user's team health."""
        if not self.my_team_id:
            return None
        return next((t for t in self.team_health if t.team_id == self.my_team_id), None)
    
    @property
    def strongest_teams(self) -> List[TeamHealth]:
        """Top 3 strongest teams by power index."""
        return sorted(self.team_health, key=lambda t: t.power_index, reverse=True)[:3]
    
    @property
    def weakest_teams(self) -> List[TeamHealth]:
        """Bottom 3 weakest teams (trade targets)."""
        return sorted(self.team_health, key=lambda t: t.power_index)[:3]


def _calculate_positional_depth(
    roster_data: List[Tuple],
    position: str,
    starter_count: int
) -> PositionalGrade:
    """
    Calculate depth grade for a specific position.
    
    Args:
        roster_data: List of (player_id, name, position, proj, status, slot) tuples
        position: Position to grade (QB, RB, WR, TE)
        starter_count: Number of starters needed at this position
    
    Returns:
        PositionalGrade with score and letter grade
    """
    # Filter to this position only
    position_players = [p for p in roster_data if p[2] == position]
    
    if not position_players:
        return PositionalGrade(
            position=position,
            starter_avg=0.0,
            depth_count=0,
            injury_risk=0,
            grade="F"
        )
    
    # Sort by projection (highest first)
    sorted_players = sorted(position_players, key=lambda p: p[3], reverse=True)
    
    # Get starters (top N by projection)
    starters = sorted_players[:starter_count]
    bench = sorted_players[starter_count:]
    
    # Calculate metrics
    starter_avg = sum(p[3] for p in starters) / len(starters) if starters else 0.0
    depth_count = len(bench)
    injury_risk = sum(1 for p in position_players if p[4] in ["Q", "D", "O", "IR"])
    
    # Grade logic (position-specific thresholds)
    grade_thresholds = {
        "QB": {"A": 20.0, "B": 16.0, "C": 12.0, "D": 8.0},
        "RB": {"A": 14.0, "B": 11.0, "C": 8.0, "D": 5.0},
        "WR": {"A": 13.0, "B": 10.0, "C": 7.0, "D": 4.0},
        "TE": {"A": 11.0, "B": 8.0, "C": 6.0, "D": 3.0},
    }
    
    thresholds = grade_thresholds.get(position, {"A": 10.0, "B": 7.0, "C": 5.0, "D": 3.0})
    
    if starter_avg >= thresholds["A"]:
        grade = "A"
    elif starter_avg >= thresholds["B"]:
        grade = "B"
    elif starter_avg >= thresholds["C"]:
        grade = "C"
    elif starter_avg >= thresholds["D"]:
        grade = "D"
    else:
        grade = "F"
    
    # Penalize for lack of depth or high injury risk
    if depth_count == 0 and grade in ["A", "B"]:
        grade = chr(ord(grade) + 1)  # Downgrade one letter
    if injury_risk >= 2 and grade in ["A", "B", "C"]:
        grade = chr(ord(grade) + 1)
    
    return PositionalGrade(
        position=position,
        starter_avg=round(starter_avg, 1),
        depth_count=depth_count,
        injury_risk=injury_risk,
        grade=grade
    )


def calculate_team_power(
    team_id: str,
    settings: LeagueSettings,
    current_week: int
) -> TeamHealth:
    """
    Calculate comprehensive team health metrics.
    
    Combines projected starter points, positional depth quality, and injury risk
    into a single Power Index score.
    
    Returns:
        TeamHealth object with all metrics
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        # Get team info
        cur.execute("SELECT name, manager FROM teams WHERE id = ?", (team_id,))
        team_row = cur.fetchone()
        if not team_row:
            raise ValueError(f"Team {team_id} not found")
        team_name, manager = team_row
        
        # Get roster with baseline projections
        # TODO: Replace with real projections when available
        cur.execute("""
            SELECT
                p.id, p.name, p.position, p.team, p.bye_week, r.slot, r.status
            FROM rosters r
            JOIN players p ON r.player_id = p.id
            WHERE r.team_id = ? AND r.week = ?
        """, (team_id, current_week))
        
        roster_raw = cur.fetchall()
        
        # Build roster with projections
        roster_data = []
        for row in roster_raw:
            player_id, name, position, team, bye_week, slot, status = row
            
            # Baseline projections by position
            proj_baseline = {
                "QB": 18.0, "RB": 12.0, "WR": 11.0,
                "TE": 9.0, "K": 8.0, "DEF": 7.0
            }.get(position, 8.0)
            
            roster_data.append((player_id, name, position, proj_baseline, status, slot))
        
        # Calculate positional grades
        positional_grades = {}
        
        # Core positions
        for pos, count in [("QB", 1), ("RB", 2), ("WR", 2), ("TE", 1)]:
            roster_count = settings.roster_slots.get(pos, count)
            positional_grades[pos] = _calculate_positional_depth(roster_data, pos, roster_count)
        
        # FLEX considerations (treat as combined RB/WR depth)
        flex_count = settings.roster_slots.get("FLEX", 0)
        if flex_count > 0:
            # Combine RB/WR for flex evaluation
            flex_players = [p for p in roster_data if p[2] in ["RB", "WR"]]
            if flex_players:
                positional_grades["FLEX"] = _calculate_positional_depth(
                    flex_players, "FLEX", flex_count
                )
        
        # Calculate projected weekly points (sum of top starters)
        projected_points = 0.0
        starter_slots = {}
        for pos, count in settings.roster_slots.items():
            if pos not in ["BENCH", "IR"]:
                starter_slots[pos] = count
        
        # Simple heuristic: take best players at each position
        for pos in ["QB", "RB", "WR", "TE", "K", "DEF"]:
            count = starter_slots.get(pos, 0)
            pos_players = sorted(
                [p for p in roster_data if p[2] == pos],
                key=lambda p: p[3],
                reverse=True
            )[:count]
            projected_points += sum(p[3] for p in pos_players)
        
        # Add FLEX (best remaining RB/WR)
        flex_count = starter_slots.get("FLEX", 0)
        if flex_count > 0:
            rb_count = starter_slots.get("RB", 0)
            wr_count = starter_slots.get("WR", 0)
            flex_candidates = sorted(
                [p for p in roster_data if p[2] in ["RB", "WR"]],
                key=lambda p: p[3],
                reverse=True
            )[rb_count + wr_count : rb_count + wr_count + flex_count]
            projected_points += sum(p[3] for p in flex_candidates)
        
        # Count injuries and bye exposure
        injury_count = sum(1 for p in roster_data if p[4] in ["Q", "D", "O", "IR"])
        bye_exposure = sum(
            1 for p in roster_raw
            if p[4] and current_week <= p[4] <= current_week + 1  # Bye this/next week
        )
        
        # Calculate Power Index
        # Formula: projected_points + (depth_quality * 10) - (injury_penalty * 2)
        depth_quality = sum(
            1.0 if g.grade == "A" else 0.75 if g.grade == "B" else 0.5 if g.grade == "C" else 0.25 if g.grade == "D" else 0.0
            for g in positional_grades.values()
        )
        injury_penalty = injury_count + (bye_exposure * 0.5)
        
        power_index = projected_points + (depth_quality * 10) - (injury_penalty * 2)
        
        return TeamHealth(
            team_id=team_id,
            team_name=team_name,
            manager=manager,
            power_index=round(power_index, 1),
            projected_points=round(projected_points, 1),
            positional_grades=positional_grades,
            injury_count=injury_count,
            bye_exposure=bye_exposure
        )
        
    finally:
        conn.close()


def league_health_snapshot(
    settings: LeagueSettings,
    current_week: int,
    my_team_id: Optional[str] = None
) -> LeagueSnapshot:
    """
    Generate complete league health overview.
    
    Calculates power index for all teams, ranks them, and identifies
    strongest/weakest teams.
    
    Args:
        settings: League configuration
        current_week: Current week number
        my_team_id: User's team ID for highlighting
    
    Returns:
        LeagueSnapshot with all team health metrics and rankings
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        # Get all teams
        cur.execute("SELECT id FROM teams ORDER BY name")
        team_ids = [row[0] for row in cur.fetchall()]
        
        # Calculate health for each team
        team_health_list = []
        for tid in team_ids:
            try:
                health = calculate_team_power(tid, settings, current_week)
                team_health_list.append(health)
            except Exception as e:
                # Skip teams with missing data
                print(f"Warning: Failed to calculate health for team {tid}: {e}")
                continue
        
        # Rank teams by power index
        sorted_teams = sorted(team_health_list, key=lambda t: t.power_index, reverse=True)
        for rank, team in enumerate(sorted_teams, start=1):
            team.rank = rank
        
        return LeagueSnapshot(
            current_week=current_week,
            total_teams=len(sorted_teams),
            team_health=sorted_teams,
            my_team_id=my_team_id
        )
        
    finally:
        conn.close()

