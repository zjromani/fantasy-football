"""
Enhanced waiver wire analysis with real projections and drop candidates.

Improves on basic waivers.py by:
- Using real projections instead of position averages
- Filtering out low-value/old players
- Suggesting which bench player to drop for each add
- Providing detailed rationale for each recommendation
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import json as _json

from .models import LeagueSettings
from .yahoo_client import YahooClient
from .waivers import free_agents_from_yahoo, WaiverRecommendation
from .projections import get_projections
from .news import fetch_all_news
from .inbox import notify
from .store import get_connection
from .config import get_settings


@dataclass
class EnhancedWaiverRecommendation:
    """Waiver recommendation with drop candidate and rationale."""
    add_player_id: str
    add_player_name: str
    add_player_position: str
    add_player_team: str
    add_projection: float

    drop_player_id: Optional[str] = None
    drop_player_name: Optional[str] = None
    drop_projection: Optional[float] = None

    score: float = 0.0
    faab_min: int = 0
    faab_max: int = 0

    reasons: List[str] = None

    def __post_init__(self):
        if self.reasons is None:
            self.reasons = []

    def get_delta(self) -> float:
        """Point improvement if swap is made."""
        if self.drop_projection is not None:
            return self.add_projection - self.drop_projection
        return self.add_projection


def get_my_roster(week: int) -> List[Dict]:
    """Get user's current roster from database."""
    cfg = get_settings()
    my_team_id = cfg.team_key.split(".")[-1] if cfg.team_key else None

    if not my_team_id:
        return []

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT p.id, p.name, p.position, p.team, r.slot, r.status
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
                "is_bench": row[4] in ["BN", "IR"] if row[4] else False,
            })
        return roster
    finally:
        conn.close()


def analyze_waivers_enhanced(
    settings: LeagueSettings,
    week: int,
    max_players: int = 50,
    top_n: int = 5
) -> List[EnhancedWaiverRecommendation]:
    """
    Enhanced waiver analysis with projections and drop candidates.
    """
    # Fetch free agents from Yahoo
    client = YahooClient()
    cfg = get_settings()
    free_agents = free_agents_from_yahoo(client, cfg.league_key, max_players=max_players)

    if not free_agents:
        return []

    # Get real projections
    try:
        projections = get_projections(week)
        proj_dict = {p.player_name.lower(): p for p in projections}
    except Exception as e:
        print(f"[WAIVERS] Could not load projections: {e}")
        proj_dict = {}

    # Get news for context
    try:
        news = fetch_all_news(max_age_minutes=120, limit_per_source=20)
        news_by_player = {}
        for item in news:
            if item.player_mentioned:
                key = item.player_mentioned.lower()
                if key not in news_by_player:
                    news_by_player[key] = []
                news_by_player[key].append(item)
    except Exception as e:
        print(f"[WAIVERS] Could not load news: {e}")
        news_by_player = {}

    # Get my roster
    my_roster = get_my_roster(week)
    bench_players = [p for p in my_roster if p.get("is_bench")]

    # Score each free agent
    recommendations = []

    for fa in free_agents:
        name = fa["name"]
        position = fa["position"]
        
        # Skip non-fantasy positions
        if position not in ["QB", "RB", "WR", "TE", "K", "DEF"]:
            continue
        
        # Get projection
        proj_obj = proj_dict.get(name.lower())
        if proj_obj:
            if settings.scoring.ppr == 1.0:
                projection = proj_obj.fantasy_points_ppr or 0
            elif settings.scoring.ppr == 0.5:
                projection = proj_obj.fantasy_points_half_ppr or 0
            else:
                projection = proj_obj.fantasy_points_standard or 0
        else:
            # Better fallback: use position-specific baselines
            # If no projections available, use Yahoo's ownership % as a rough proxy
            ownership = fa.get("ownership_pct", 0)
            if ownership > 50:
                # Likely a starter
                position_baseline = {"QB": 18, "RB": 12, "WR": 10, "TE": 8, "K": 8, "DEF": 8}
                projection = position_baseline.get(position, 10.0)
            else:
                # Likely a backup or low-value player
                projection = 5.0
        
        # Skip very low projections (not fantasy-relevant)
        # Raise threshold to filter out more low-value players
        if projection < 8.0:
            continue

        # Find best drop candidate (lowest projected bench player at same position)
        drop_candidate = None
        drop_projection = None

        bench_at_position = [p for p in bench_players if p["position"] == position]
        if bench_at_position:
            # Get projections for bench players
            bench_with_proj = []
            for bench_p in bench_at_position:
                bench_proj_obj = proj_dict.get(bench_p["name"].lower())
                if bench_proj_obj:
                    if settings.scoring.ppr == 1.0:
                        bp = bench_proj_obj.fantasy_points_ppr or 0
                    elif settings.scoring.ppr == 0.5:
                        bp = bench_proj_obj.fantasy_points_half_ppr or 0
                    else:
                        bp = bench_proj_obj.fantasy_points_standard or 0
                else:
                    # Better fallback for bench players
                    # If they're on my bench, assume they have some value
                    # Use position baseline adjusted for injury status
                    if bench_p.get("status") in ["O", "D", "IR"]:
                        bp = 0.0  # Injured players worth nothing
                    else:
                        # Assume bench players are worth ~40% of a starter
                        position_baseline = {"QB": 18, "RB": 12, "WR": 10, "TE": 8, "K": 8, "DEF": 8}
                        bp = position_baseline.get(position, 10.0) * 0.4
                
                bench_with_proj.append((bench_p, bp))

            # Sort by projection (lowest first)
            bench_with_proj.sort(key=lambda x: x[1])

            if bench_with_proj:
                drop_candidate, drop_projection = bench_with_proj[0]

        # Calculate score (higher projection = better)
        score = projection

        # Only recommend if better than drop candidate
        if drop_projection is not None and projection <= drop_projection:
            continue

        # Build reasons
        reasons = []
        reasons.append(f"Projected {projection:.1f} pts this week")

        if drop_candidate:
            delta = projection - drop_projection
            reasons.append(f"Upgrade over {drop_candidate['name']} (+{delta:.1f} pts)")

        # Add news context
        player_news = news_by_player.get(name.lower(), [])
        if player_news:
            for item in player_news[:1]:  # Top news item
                if item.category == "injury":
                    reasons.append(f"Injury update: {item.title[:60]}")
                else:
                    reasons.append(f"News: {item.title[:60]}")

        # FAAB calculation
        faab_remaining = settings.faab_budget or 100
        faab_min = max(1, int(score * 0.4))
        faab_max = max(faab_min + 2, int(score * 0.7))
        faab_min = min(faab_min, faab_remaining)
        faab_max = min(faab_max, faab_remaining)

        rec = EnhancedWaiverRecommendation(
            add_player_id=fa["id"],
            add_player_name=name,
            add_player_position=position,
            add_player_team=fa.get("team", ""),
            add_projection=projection,
            drop_player_id=drop_candidate["id"] if drop_candidate else None,
            drop_player_name=drop_candidate["name"] if drop_candidate else None,
            drop_projection=drop_projection,
            score=score,
            faab_min=faab_min,
            faab_max=faab_max,
            reasons=reasons
        )

        recommendations.append(rec)

    # Sort by delta (biggest improvement first)
    recommendations.sort(key=lambda r: r.get_delta(), reverse=True)

    return recommendations[:top_n]


def post_enhanced_waivers_to_inbox(
    recommendations: List[EnhancedWaiverRecommendation],
    week: int
) -> int:
    """Post enhanced waiver recommendations to Inbox."""
    if not recommendations:
        return notify("waivers", "No waiver targets",
                     "No viable free agents with projections better than your bench.", {})

    # Build detailed message
    lines = [f"🎯 Top {len(recommendations)} Waiver Targets for Week {week}\n"]

    for i, rec in enumerate(recommendations, 1):
        lines.append(f"\n{i}. **Add {rec.add_player_name}** ({rec.add_player_position}, {rec.add_player_team})")
        lines.append(f"   Projected: {rec.add_projection:.1f} pts | FAAB: ${rec.faab_min}-${rec.faab_max}")

        if rec.drop_player_name:
            lines.append(f"   Drop: {rec.drop_player_name} ({rec.drop_projection:.1f} pts)")
            lines.append(f"   Improvement: +{rec.get_delta():.1f} pts")

        lines.append("   Reasons:")
        for reason in rec.reasons:
            lines.append(f"   • {reason}")

    lines.append("\n" + "─" * 50)
    lines.append("\n💡 Review each recommendation and approve to add to pending waiver claims.")

    body = "\n".join(lines)

    # Save to recommendations table for approval flow
    conn = get_connection()
    try:
        cur = conn.cursor()
        for rec in recommendations:
            payload = {
                "add_player_id": rec.add_player_id,
                "add_player_name": rec.add_player_name,
                "drop_player_id": rec.drop_player_id,
                "drop_player_name": rec.drop_player_name,
                "position": rec.add_player_position,
                "projection": rec.add_projection,
                "faab_min": rec.faab_min,
                "faab_max": rec.faab_max,
                "delta": rec.get_delta(),
                "reasons": rec.reasons,
            }
            cur.execute(
                "INSERT INTO recommendations(kind, title, body, payload, status) VALUES(?, ?, ?, ?, ?)",
                (
                    "waivers",
                    f"Add {rec.add_player_name}",
                    f"+{rec.get_delta():.1f} pts | ${rec.faab_min}-${rec.faab_max}",
                    _json.dumps(payload),
                    "pending"
                ),
            )
        conn.commit()
    finally:
        conn.close()

    # Post to Inbox
    payload = {
        "week": week,
        "recommendations": [
            {
                "add": rec.add_player_name,
                "drop": rec.drop_player_name,
                "delta": rec.get_delta(),
                "faab_range": f"${rec.faab_min}-${rec.faab_max}"
            }
            for rec in recommendations
        ]
    }

    msg_id = notify("waivers", f"⚡ {len(recommendations)} Waiver Targets", body, payload)
    return msg_id


__all__ = [
    "EnhancedWaiverRecommendation",
    "analyze_waivers_enhanced",
    "post_enhanced_waivers_to_inbox",
]

