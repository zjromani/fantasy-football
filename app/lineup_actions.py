"""
Lineup optimizer actions and Inbox posting.

Generates and posts sit/start recommendations to the Inbox.
"""
from __future__ import annotations

from typing import List, Dict, Optional

from .lineup_enhanced import optimize_lineup_enhanced, SitStartRecommendation
from .models import LeagueSettings
from .inbox import notify
from .db import get_connection
from .config import get_settings


def get_roster_for_optimization(week: int) -> List[Dict]:
    """Fetch current roster from database for optimization."""
    cfg = get_settings()
    my_team_id = cfg.team_key.split(".")[-1] if cfg.team_key else None
    
    if not my_team_id:
        return []
    
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                p.id,
                p.name,
                p.position,
                p.team,
                r.slot,
                r.status
            FROM rosters r
            JOIN players p ON r.player_id = p.id
            WHERE r.team_id = ? AND r.week = ?
            ORDER BY p.position, p.name
        """, (my_team_id, week))
        
        roster = []
        for row in cur.fetchall():
            roster.append({
                "id": row[0],
                "name": row[1],
                "position": row[2],
                "team": row[3],
                "slot": row[4],
                "status": row[5],
            })
        
        return roster
    finally:
        conn.close()


def format_recommendations_for_inbox(
    recommendations: List[SitStartRecommendation],
    week: int
) -> tuple[str, str, dict]:
    """Format recommendations into Inbox message."""
    if not recommendations:
        title = f"⚡ Lineup Optimizer - Week {week}"
        body = "Your lineup looks optimal! No recommended changes at this time.\n\n✅ All set for this week."
        payload = {"week": week, "recommendations": []}
        return title, body, payload
    
    title = f"⚡ Lineup Optimizer - Week {week} ({len(recommendations)} suggestion{'s' if len(recommendations) > 1 else ''})"
    
    # Build body
    lines = [
        f"Found {len(recommendations)} potential lineup improvement{'s' if len(recommendations) > 1 else ''}:\n"
    ]
    
    for i, rec in enumerate(recommendations, 1):
        lines.append(f"\n{i}. {rec.get_summary()}")
        lines.append("")
        lines.append("   Reasons:")
        for reason in rec.reasons:
            lines.append(f"   • {reason}")
        
        if rec.warnings:
            lines.append("")
            lines.append("   Warnings:")
            for warning in rec.warnings:
                lines.append(f"   ⚠️  {warning}")
    
    lines.append("\n" + "─" * 50)
    lines.append("\n💡 Tip: Review these suggestions before making changes.")
    lines.append("Consider checking the latest news and injury reports.")
    
    body = "\n".join(lines)
    
    # Payload for programmatic access
    payload = {
        "week": week,
        "recommendation_count": len(recommendations),
        "recommendations": [
            {
                "player_in": rec.player_in.name,
                "player_in_id": rec.player_in.id,
                "player_out": rec.player_out.name,
                "player_out_id": rec.player_out.id,
                "position": rec.player_in.position,
                "delta": rec.projection_delta,
                "confidence": rec.confidence,
                "reasons": rec.reasons,
                "warnings": rec.warnings,
            }
            for rec in recommendations
        ]
    }
    
    return title, body, payload


def optimize_and_post_to_inbox(
    settings: LeagueSettings,
    week: int,
    min_confidence: float = 65.0
) -> Optional[int]:
    """
    Run lineup optimizer and post results to Inbox.
    
    Returns notification ID if posted, None if error.
    """
    try:
        # Get roster
        roster = get_roster_for_optimization(week)
        
        if not roster:
            notify("info", "Lineup Optimizer", "No roster data found. Run 'Sync Yahoo Data' first.", {})
            return None
        
        # Run optimizer
        recommendations = optimize_lineup_enhanced(
            settings=settings,
            roster_players=roster,
            week=week,
            min_confidence=min_confidence
        )
        
        # Format and post
        title, body, payload = format_recommendations_for_inbox(recommendations, week)
        
        msg_id = notify("lineup", title, body, payload)
        
        return msg_id
    
    except Exception as e:
        notify("info", "Lineup Optimizer Error", f"Failed to generate recommendations: {e}", {})
        return None


def get_current_week() -> int:
    """Get current NFL week from database."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT MAX(week) FROM matchups")
        result = cur.fetchone()
        return result[0] if result and result[0] else 1
    finally:
        conn.close()


def run_lineup_optimizer_action(settings: LeagueSettings) -> Optional[int]:
    """
    Main entry point for lineup optimizer action.
    
    Called from UI or scheduled job.
    Returns notification ID.
    """
    week = get_current_week()
    return optimize_and_post_to_inbox(settings, week)


__all__ = [
    "optimize_and_post_to_inbox",
    "run_lineup_optimizer_action",
    "get_roster_for_optimization",
    "format_recommendations_for_inbox",
]

