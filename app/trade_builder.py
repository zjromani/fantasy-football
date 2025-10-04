"""
Build TeamState and analyze manager tendencies for trade finder.
"""
from typing import Dict, List
from .trades import Player, TeamState
from .db import get_connection
from .models import LeagueSettings


def build_team_state(team_id: str, settings: LeagueSettings, current_week: int) -> TeamState:
    """Build TeamState from database roster/matchup data."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        # Get roster for this team
        cur.execute("""
            SELECT 
                p.id, p.name, p.position, p.team, p.bye_week, r.slot, r.status
            FROM rosters r
            JOIN players p ON r.player_id = p.id
            WHERE r.team_id = ? AND r.week = ?
            ORDER BY p.position, p.name
        """, (team_id, current_week))
        
        roster_data = cur.fetchall()
        
        # Build player list with simplified projections
        roster: List[Player] = []
        for row in roster_data:
            player_id, name, position, team, bye_week, slot, status = row
            
            # Simplified: Use position-based baseline projections
            # TODO: Integrate real projections from projections table or API
            proj_baseline = {
                "QB": 18.0, "RB": 12.0, "WR": 11.0, 
                "TE": 9.0, "K": 8.0, "DEF": 7.0
            }.get(position, 8.0)
            
            # Calculate byes in next 3 weeks
            bye_in_next_3 = 1 if bye_week and current_week <= bye_week <= current_week + 3 else 0
            
            roster.append(Player(
                id=player_id,
                name=name,
                position=position,
                proj_next3=proj_baseline * 3,  # 3 weeks
                playoff_proj=proj_baseline * 3,  # weeks 15-17
                bye_next3=bye_in_next_3,
                injury=status if status in ["Q", "D", "O", "IR"] else "",
                volatility=0.5  # default moderate risk
            ))
        
        # Count bench redundancy by position
        bench_redundancy: Dict[str, int] = {}
        for p in roster_data:
            position = p[2]
            slot = p[5]
            if slot == "BN":
                bench_redundancy[position] = bench_redundancy.get(position, 0) + 1
        
        # Count injuries
        injury_count = sum(1 for p in roster_data if p[6] in ["Q", "D", "O"])
        
        # Count bye exposure
        bye_exposure = sum(1 for p in roster if p.bye_next3 > 0)
        
        # Get schedule difficulty (placeholder)
        # TODO: Calculate from opponent strength of schedule
        schedule_difficulty = 1.5  # neutral
        
        # Get manager profile
        manager_profile = analyze_manager_tendencies(team_id, cur)
        
        # Get required starters by slot from league settings
        starters_by_slot = {
            "QB": 1,
            "RB": 2,
            "WR": 2,
            "TE": 1,
            "FLEX": 1,
            "K": 1,
            "DEF": 1,
        }
        # TODO: Extract actual from settings.roster_slots
        
        return TeamState(
            team_id=team_id,
            starters_by_slot=starters_by_slot,
            bench_redundancy=bench_redundancy,
            bye_exposure=bye_exposure,
            injuries=injury_count,
            schedule_difficulty=schedule_difficulty,
            manager_profile=manager_profile,
            roster=roster
        )
        
    finally:
        conn.close()


def analyze_manager_tendencies(team_id: str, cur) -> Dict:
    """Analyze manager's past behavior to predict trade acceptance."""
    
    # Get transaction history from transactions_raw table
    try:
        cur.execute("""
            SELECT kind, raw, created_at
            FROM transactions_raw
            WHERE team_id = ? OR team_id IS NULL
            ORDER BY created_at DESC
            LIMIT 50
        """, (team_id,))
        
        transactions = cur.fetchall()
    except Exception:
        # Table might not exist or be empty
        transactions = []
    
    # Count trade activity
    trade_count = sum(1 for t in transactions if t[0] and 'trade' in t[0].lower())
    waiver_count = sum(1 for t in transactions if t[0] and ('waiver' in t[0].lower() or 'add' in t[0].lower()))
    
    # Default moderate acceptance if no history
    trade_acceptance_rate = 0.5
    
    # If manager makes lots of moves, they're more active/likely to trade
    if waiver_count > 10:
        trade_acceptance_rate = 0.65
    if trade_count > 2:
        trade_acceptance_rate = 0.7
    
    # If no transaction data, use neutral assumptions
    if len(transactions) == 0:
        return {
            "trade_acceptance_rate": 0.5,
            "position_preference": "balanced",
            "recent_activity": "no transaction history",
            "trade_count": 0,
            "active_manager": False,
        }
    
    # Analyze position preferences from adds/drops
    # TODO: Parse transaction raw JSON to identify position patterns
    position_preference = "balanced"
    
    recent_activity = f"{trade_count} trades, {waiver_count} waivers" if trade_count + waiver_count > 0 else "minimal activity"
    
    return {
        "trade_acceptance_rate": trade_acceptance_rate,
        "position_preference": position_preference,
        "recent_activity": recent_activity,
        "trade_count": trade_count,
        "active_manager": waiver_count > 8,
    }


__all__ = [
    "build_team_state",
    "analyze_manager_tendencies",
]

