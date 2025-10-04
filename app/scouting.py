"""
Opponent scouting module.

Generates AI-powered scouting reports on upcoming opponents, analyzing:
- Roster strengths and weaknesses by position
- Recent performance trends and scoring patterns
- Waiver wire activity and team management style
- Head-to-head matchup advantages
- Strategic recommendations for lineup decisions
"""
from __future__ import annotations

import json as _json
from typing import Dict, List, Optional, Tuple

from .store import get_connection
from .models import LeagueSettings
from .config import get_settings
from .ai.client import ask
from .ai.config import get_ai_settings
from .inbox import notify
from .news import fetch_all_news


def _get_opponent_context(my_team_id: str, opponent_team_id: str, current_week: int) -> Dict:
    """Gather detailed context about opponent for scouting report."""
    conn = get_connection()
    try:
        cur = conn.cursor()

        # Get opponent team info
        cur.execute("SELECT id, name, manager FROM teams WHERE id = ?", (opponent_team_id,))
        opp_team = cur.fetchone()
        opponent_name = opp_team[1] if opp_team else "Unknown"
        opponent_manager = opp_team[2] if opp_team else "Unknown"

        # Get my team info
        cur.execute("SELECT name FROM teams WHERE id = ?", (my_team_id,))
        my_team = cur.fetchone()
        my_team_name = my_team[0] if my_team else "Your Team"

        # Get opponent's roster with player details
        # Note: Yahoo roster data may not have slot assignments if we fetched general roster
        # Group by player to avoid duplicates
        cur.execute("""
            SELECT p.name, p.position, p.team, p.bye_week, r.slot, r.status
            FROM rosters r
            JOIN players p ON r.player_id = p.id
            WHERE r.team_id = ? AND r.week = ?
            GROUP BY p.name, p.position, p.team
            ORDER BY
                CASE p.position
                    WHEN 'QB' THEN 1
                    WHEN 'RB' THEN 2
                    WHEN 'WR' THEN 3
                    WHEN 'TE' THEN 4
                    WHEN 'K' THEN 5
                    WHEN 'DEF' THEN 6
                    ELSE 7
                END,
                p.name
        """, (opponent_team_id, current_week))

        opponent_roster = []
        for row in cur.fetchall():
            opponent_roster.append({
                "name": row[0],
                "position": row[1],
                "nfl_team": row[2] or "FA",
                "bye_week": row[3],
                "slot": row[4],
                "status": row[5] or "Active"
            })

        # Get my roster for comparison (deduplicated)
        cur.execute("""
            SELECT p.name, p.position, p.team, p.bye_week, r.slot, r.status
            FROM rosters r
            JOIN players p ON r.player_id = p.id
            WHERE r.team_id = ? AND r.week = ?
            GROUP BY p.name, p.position, p.team
            ORDER BY
                CASE p.position
                    WHEN 'QB' THEN 1
                    WHEN 'RB' THEN 2
                    WHEN 'WR' THEN 3
                    WHEN 'TE' THEN 4
                    WHEN 'K' THEN 5
                    WHEN 'DEF' THEN 6
                    ELSE 7
                END,
                p.name
        """, (my_team_id, current_week))

        my_roster = []
        for row in cur.fetchall():
            my_roster.append({
                "name": row[0],
                "position": row[1],
                "nfl_team": row[2] or "FA",
                "bye_week": row[3],
                "slot": row[4],
                "status": row[5] or "Active"
            })

        # Get recent matchup history (if any)
        cur.execute("""
            SELECT week, projected, actual, result
            FROM matchups
            WHERE team_id = ? AND opponent_id = ?
            ORDER BY week DESC
            LIMIT 3
        """, (my_team_id, opponent_team_id))

        matchup_history = []
        for row in cur.fetchall():
            matchup_history.append({
                "week": row[0],
                "my_projected": row[1],
                "my_actual": row[2],
                "result": row[3]
            })

        # Get opponent's recent transactions
        cur.execute("""
            SELECT kind, raw
            FROM transactions_raw
            WHERE team_id = ?
            ORDER BY id DESC
            LIMIT 10
        """, (opponent_team_id,))

        recent_moves = []
        for row in cur.fetchall():
            try:
                tx_data = _json.loads(row[1]) if row[1] else {}
                recent_moves.append({"type": row[0], "data": tx_data})
            except:
                pass

        # Analyze roster composition
        def analyze_roster(roster: List[Dict]) -> Dict:
            """Count positions and identify starters vs bench."""
            # If slot data is missing, estimate starters based on typical roster (top players by position)
            has_slot_data = any(p.get('slot') for p in roster)

            if has_slot_data:
                starters = [p for p in roster if p.get('slot') not in ['BN', 'IR', None]]
                bench = [p for p in roster if p.get('slot') == 'BN']
            else:
                # Estimate starters: typically first 1-2 per key position
                starters = []
                bench = []
                pos_count = {}
                for p in roster:
                    pos = p.get('position', 'UNKNOWN')
                    count = pos_count.get(pos, 0)
                    # Typical starter slots: 1-2 QB, 2-3 RB, 2-3 WR, 1 TE, 1 K, 1 DEF
                    max_starters = {'QB': 2, 'RB': 3, 'WR': 3, 'TE': 1, 'K': 1, 'DEF': 1}.get(pos, 0)
                    if count < max_starters:
                        starters.append(p)
                    else:
                        bench.append(p)
                    pos_count[pos] = count + 1

            position_counts = {}
            for p in roster:
                pos = p.get('position', 'UNKNOWN')
                position_counts[pos] = position_counts.get(pos, 0) + 1

            return {
                "total": len(roster),
                "starters": len(starters),
                "bench": len(bench),
                "position_breakdown": position_counts,
                "injured": len([p for p in roster if p.get('status') and p['status'] != 'Active']),
                "on_bye": len([p for p in roster if p.get('bye_week') == current_week]),
                "estimated": not has_slot_data
            }

        opponent_analysis = analyze_roster(opponent_roster)
        my_analysis = analyze_roster(my_roster)

        return {
            "my_team_id": my_team_id,
            "my_team_name": my_team_name,
            "my_roster": my_roster,
            "my_analysis": my_analysis,
            "opponent_team_id": opponent_team_id,
            "opponent_name": opponent_name,
            "opponent_manager": opponent_manager,
            "opponent_roster": opponent_roster,
            "opponent_analysis": opponent_analysis,
            "matchup_history": matchup_history,
            "recent_moves": recent_moves,
            "current_week": current_week,
        }
    finally:
        conn.close()


def build_scouting_report(
    settings: LeagueSettings,
    opponent_team_id: str,
    current_week: Optional[int] = None
) -> Tuple[str, str, Dict]:
    """
    Generate AI-powered scouting report on opponent.

    Returns:
        Tuple of (title, body, payload) for Inbox notification
    """
    cfg = get_settings()
    my_team_id = cfg.team_key.split(".")[-1] if cfg.team_key else None

    if not my_team_id:
        return (
            "❌ Scouting Report Error",
            "Cannot generate report: TEAM_KEY not configured",
            {"error": "missing_team_key"}
        )

    # Get opponent context
    if current_week is None:
        # Determine current week from latest matchup
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT MAX(week) FROM matchups")
            result = cur.fetchone()
            current_week = result[0] if result and result[0] else 1
        finally:
            conn.close()

    context = _get_opponent_context(my_team_id, opponent_team_id, current_week)

    # Get latest news for injury/status context
    news = fetch_all_news(max_age_minutes=60, limit_per_source=10)
    injury_updates = [item for item in news if item.category == "injury"][:5]

    news_summary = []
    for item in injury_updates:
        news_summary.append(f"- [{item.source}] {item.title}")

    try:
        # Check if OpenAI is configured
        ai_settings = get_ai_settings()

        # Build AI prompt for scouting
        # Extract top players by position for better analysis
        def get_top_by_position(roster: List[Dict], position: str, limit: int = 3) -> List[str]:
            players = [p for p in roster if p.get('position') == position]
            return [f"{p['name']} ({p['nfl_team']})" for p in players[:limit]]

        my_top_qb = get_top_by_position(context['my_roster'], 'QB', 2)
        my_top_rb = get_top_by_position(context['my_roster'], 'RB', 3)
        my_top_wr = get_top_by_position(context['my_roster'], 'WR', 3)
        my_top_te = get_top_by_position(context['my_roster'], 'TE', 2)

        opp_top_qb = get_top_by_position(context['opponent_roster'], 'QB', 2)
        opp_top_rb = get_top_by_position(context['opponent_roster'], 'RB', 3)
        opp_top_wr = get_top_by_position(context['opponent_roster'], 'WR', 3)
        opp_top_te = get_top_by_position(context['opponent_roster'], 'TE', 2)

        prompt = f"""You are an expert fantasy football analyst generating a scouting report for Week {current_week}.

MATCHUP: {context['my_team_name']} vs. {context['opponent_name']} (Manager: {context['opponent_manager']})

YOUR TEAM KEY PLAYERS:
- QB: {', '.join(my_top_qb) if my_top_qb else 'None listed'}
- RB: {', '.join(my_top_rb) if my_top_rb else 'None listed'}
- WR: {', '.join(my_top_wr) if my_top_wr else 'None listed'}
- TE: {', '.join(my_top_te) if my_top_te else 'None listed'}
- Total roster size: {context['my_analysis']['total']} players
- Position breakdown: {_json.dumps(context['my_analysis']['position_breakdown'])}

OPPONENT'S KEY PLAYERS:
- QB: {', '.join(opp_top_qb) if opp_top_qb else 'None listed'}
- RB: {', '.join(opp_top_rb) if opp_top_rb else 'None listed'}
- WR: {', '.join(opp_top_wr) if opp_top_wr else 'None listed'}
- TE: {', '.join(opp_top_te) if opp_top_te else 'None listed'}
- Total roster size: {context['opponent_analysis']['total']} players
- Position breakdown: {_json.dumps(context['opponent_analysis']['position_breakdown'])}

OPPONENT'S TEAM STATS:
- Starters: {context['opponent_analysis']['starters']}
- Position breakdown: {_json.dumps(context['opponent_analysis']['position_breakdown'])}
- Injured/Out: {context['opponent_analysis']['injured']}
- On bye this week: {context['opponent_analysis']['on_bye']}

RECENT INJURY NEWS (affects both teams):
{chr(10).join(news_summary) if news_summary else "No major injury updates"}

OPPONENT'S RECENT MOVES ({len(context['recent_moves'])} transactions):
{_json.dumps(context['recent_moves'][:3], indent=2) if context['recent_moves'] else "No recent activity"}

MATCHUP HISTORY:
{_json.dumps(context['matchup_history'], indent=2) if context['matchup_history'] else "First matchup this season"}

Generate a comprehensive scouting report with these sections:

**🎯 Executive Summary** (2-3 sentences)
- Overall matchup assessment and win probability
- Key advantage areas

**💪 Opponent's Strengths**
- Top 3 strongest positions with specific player names
- Dangerous players you need to worry about
- Roster depth advantages

**🎯 Opponent's Weaknesses**
- Top 3 exploitable positions
- Injured/questionable players
- Bye week impacts
- Roster gaps you can exploit

**📊 Position-by-Position Breakdown**
For QB, RB, WR, TE:
- Their starters vs yours
- Advantage/disadvantage assessment
- Specific matchup notes

**🔄 Recent Activity & Trends**
- What their recent moves tell you about their strategy
- Are they aggressive or passive on waivers?
- Position they're trying to shore up

**⚡ Keys to Victory**
- 3 specific strategic recommendations
- Which of your players have best matchup advantages
- Lineup tips to exploit their weaknesses

**🎲 X-Factor Players**
- 1-2 players (yours or theirs) who could swing the matchup

Be specific with player names. Use the injury news to flag concerns. Be honest about both teams' chances."""

        # Call OpenAI
        response = ask(
            messages=[{"role": "user", "content": prompt}],
            model="gpt-4o-mini",
            max_tokens=2000,
            temperature=0.7,
        )

        ai_body = response.get("content", "Scouting report generation failed")

        payload = {
            "ai_generated": True,
            "opponent": context['opponent_name'],
            "opponent_manager": context['opponent_manager'],
            "week": current_week,
            "context": {
                "my_analysis": context['my_analysis'],
                "opponent_analysis": context['opponent_analysis'],
                "matchup_history": context['matchup_history'],
            },
            "raw_response": ai_body,
        }

        title = f"🔍 Scouting Report: {context['opponent_name']} (Week {current_week})"

        return title, ai_body, payload

    except Exception as e:
        # Fallback to basic analysis if AI unavailable
        fallback_body = f"""## Scouting Report: {context['opponent_name']}

**Week {current_week} Matchup**

### Opponent Roster Overview
- **Total Players**: {context['opponent_analysis']['total']}
- **Injured/Out**: {context['opponent_analysis']['injured']}
- **On Bye**: {context['opponent_analysis']['on_bye']}

### Position Breakdown
{_json.dumps(context['opponent_analysis']['position_breakdown'], indent=2)}

### Recent Activity
{len(context['recent_moves'])} recent transactions

**Note**: AI-powered analysis unavailable. Configure OPENAI_API_KEY for detailed scouting reports with:
- Strength/weakness analysis
- Position-by-position breakdown
- Strategic recommendations
- X-factor players

Error: {str(e)}"""

        return (
            f"📊 Scouting Report: {context['opponent_name']} (Week {current_week})",
            fallback_body,
            {"ai_generated": False, "error": str(e), "context": context}
        )


def post_scouting_report(settings: LeagueSettings, opponent_team_id: str, current_week: Optional[int] = None) -> int:
    """Generate and post scouting report to Inbox."""
    title, body, payload = build_scouting_report(settings, opponent_team_id, current_week)
    return notify("scouting", title, body, _json.dumps(payload))


def get_next_opponent(my_team_id: str, current_week: int) -> Optional[str]:
    """Get the opponent team ID for the current/next week."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT opponent_id
            FROM matchups
            WHERE team_id = ? AND week = ?
        """, (my_team_id, current_week))

        result = cur.fetchone()
        return result[0] if result else None
    finally:
        conn.close()


__all__ = ["build_scouting_report", "post_scouting_report", "get_next_opponent"]

