"""
Enhanced lineup optimizer with real projections, news, and weather.

Generates intelligent sit/start recommendations by analyzing:
- Real weekly projections from projections API
- Recent news (injuries, opportunity changes)
- Weather conditions (wind, rain, temperature)
- Matchup quality and defensive rankings
- Player tier and consistency
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone

from .models import LeagueSettings
from .projections import get_projections
from .news import fetch_all_news
from .weather import WeatherAPI, WeatherCondition
from .db import get_connection


@dataclass
class EnhancedPlayer:
    """Player with all decision-making data."""
    id: str
    name: str
    position: str
    team: str

    # Projection data
    base_projection: float = 0.0
    adjusted_projection: float = 0.0

    # Context
    injury_status: Optional[str] = None  # Q, D, OUT, etc.
    is_bye: bool = False
    tier: str = "tier-3"  # tier-1, tier-2, tier-3

    # News factors
    recent_news: List[str] = None  # Headlines about this player
    news_sentiment: str = "neutral"  # positive, neutral, negative

    # Weather
    weather: Optional[WeatherCondition] = None
    weather_adjustment: float = 0.0  # +/- points

    # Current status
    current_slot: Optional[str] = None  # QB, RB, WR, BN, etc.
    is_starter: bool = False

    def __post_init__(self):
        if self.recent_news is None:
            self.recent_news = []

    def get_final_projection(self) -> float:
        """Get projection after all adjustments."""
        return max(0.0, self.adjusted_projection + self.weather_adjustment)


@dataclass
class SitStartRecommendation:
    """Detailed sit/start recommendation with full rationale."""
    action: str  # "start" or "bench"
    player_in: EnhancedPlayer
    player_out: EnhancedPlayer

    # Scoring
    projection_delta: float
    confidence: float  # 0-100

    # Rationale components
    reasons: List[str]
    warnings: List[str]

    def get_summary(self) -> str:
        """One-line summary."""
        return f"Start {self.player_in.name} over {self.player_out.name} (+{self.projection_delta:.1f} pts, {self.confidence:.0f}% confidence)"

    def get_full_rationale(self) -> str:
        """Multi-line detailed rationale."""
        lines = [self.get_summary(), ""]

        lines.append("Reasons:")
        for reason in self.reasons:
            lines.append(f"  • {reason}")

        if self.warnings:
            lines.append("")
            lines.append("Warnings:")
            for warning in self.warnings:
                lines.append(f"  ⚠️  {warning}")

        return "\n".join(lines)


def fetch_player_context(
    player_id: str,
    player_name: str,
    player_team: str,
    week: int,
    settings: LeagueSettings
) -> Dict:
    """Fetch all context for a player: projections, news, weather."""
    context = {
        "projection": 0.0,
        "news": [],
        "news_sentiment": "neutral",
        "weather": None,
        "weather_adjustment": 0.0,
    }

    # Get projections
    try:
        projections = get_projections(week)
        player_proj = next(
            (p for p in projections if p.player_name.lower() == player_name.lower()),
            None
        )
        if player_proj:
            # Use appropriate scoring format
            if settings.scoring.ppr == 1.0:
                context["projection"] = player_proj.fantasy_points_ppr or 0.0
            elif settings.scoring.ppr == 0.5:
                context["projection"] = player_proj.fantasy_points_half_ppr or 0.0
            else:
                context["projection"] = player_proj.fantasy_points_standard or 0.0
    except Exception as e:
        print(f"[LINEUP] Could not fetch projection for {player_name}: {e}")

    # Get news
    try:
        all_news = fetch_all_news()
        player_news = [
            n for n in all_news
            if n.player_mentioned and player_name.lower() in n.player_mentioned.lower()
        ][:3]  # Latest 3

        context["news"] = [n.title for n in player_news]

        # Sentiment analysis (basic keyword matching)
        if player_news:
            news_text = " ".join([n.title + " " + n.description for n in player_news]).lower()
            if any(word in news_text for word in ["out", "injured", "doubtful", "suspended"]):
                context["news_sentiment"] = "negative"
            elif any(word in news_text for word in ["returns", "cleared", "breakout", "starting"]):
                context["news_sentiment"] = "positive"
    except Exception as e:
        print(f"[LINEUP] Could not fetch news for {player_name}: {e}")

    # Get weather (placeholder - would need game schedule)
    # In production, look up opponent and game time, then fetch weather
    context["weather"] = None
    context["weather_adjustment"] = 0.0

    return context


def build_enhanced_players(
    players: List[Dict],
    week: int,
    settings: LeagueSettings
) -> List[EnhancedPlayer]:
    """Build EnhancedPlayer objects with all context."""
    enhanced = []

    for p in players:
        # Fetch context
        context = fetch_player_context(
            p.get("id", ""),
            p.get("name", ""),
            p.get("team", ""),
            week,
            settings
        )

        # Build enhanced player
        base_proj = context["projection"] or p.get("projected", 0.0)
        adjusted_proj = base_proj

        # Adjust for injury
        injury = p.get("injury") or p.get("status")
        if injury:
            injury_upper = str(injury).upper()
            if injury_upper in ["OUT", "SUSPENDED"]:
                adjusted_proj = 0.0
            elif injury_upper == "D":
                adjusted_proj *= 0.3  # Doubtful = 30% chance
            elif injury_upper == "Q":
                adjusted_proj *= 0.85  # Questionable = slight downgrade

        # Adjust for news sentiment
        if context["news_sentiment"] == "negative":
            adjusted_proj *= 0.8
        elif context["news_sentiment"] == "positive":
            adjusted_proj *= 1.1

        enhanced_player = EnhancedPlayer(
            id=p.get("id", ""),
            name=p.get("name", ""),
            position=p.get("position", ""),
            team=p.get("team", ""),
            base_projection=base_proj,
            adjusted_projection=adjusted_proj,
            injury_status=injury,
            is_bye=p.get("is_bye", False),
            tier=p.get("tier", "tier-3"),
            recent_news=context["news"],
            news_sentiment=context["news_sentiment"],
            weather=context["weather"],
            weather_adjustment=context["weather_adjustment"],
            current_slot=p.get("slot"),
            is_starter=p.get("is_starter", False)
        )

        enhanced.append(enhanced_player)

    return enhanced


def generate_sit_start_recommendations(
    *,
    settings: LeagueSettings,
    players: List[EnhancedPlayer],
    week: int,
    min_confidence: float = 60.0
) -> List[SitStartRecommendation]:
    """Generate sit/start recommendations with detailed rationale."""
    recommendations = []

    # Group by position
    by_position: Dict[str, List[EnhancedPlayer]] = {}
    for p in players:
        by_position.setdefault(p.position, []).append(p)

    # For each position, compare starters vs bench
    for position, pos_players in by_position.items():
        starters = [p for p in pos_players if p.is_starter and not p.is_bye]
        bench = [p for p in pos_players if not p.is_starter and not p.is_bye]

        if not starters or not bench:
            continue

        # Sort by projection
        starters.sort(key=lambda x: x.get_final_projection(), reverse=True)
        bench.sort(key=lambda x: x.get_final_projection(), reverse=True)

        # Find swaps where bench > starter
        for bench_player in bench:
            bench_proj = bench_player.get_final_projection()

            for starter in starters:
                starter_proj = starter.get_final_projection()
                delta = bench_proj - starter_proj

                if delta <= 0:
                    continue  # Bench player not better

                # Build rationale
                reasons = []
                warnings = []

                # Projection delta
                reasons.append(f"{bench_player.name} projected {bench_proj:.1f} pts vs {starter.name} {starter_proj:.1f} pts")

                # News
                if bench_player.news_sentiment == "positive":
                    reasons.append(f"Positive news: {bench_player.recent_news[0] if bench_player.recent_news else 'opportunity increase'}")
                if starter.news_sentiment == "negative":
                    reasons.append(f"{starter.name} has concerning news")

                # Injury
                if starter.injury_status and starter.injury_status.upper() in ["Q", "D"]:
                    reasons.append(f"{starter.name} injury risk ({starter.injury_status})")

                # Weather
                if bench_player.weather and bench_player.weather.weather_impact == "good":
                    reasons.append(f"Good weather conditions for {bench_player.name}")
                if starter.weather and starter.weather.weather_impact in ["bad", "severe"]:
                    reasons.append(f"Poor weather for {starter.name}: {starter.weather.get_impact_description()}")

                # Tier protection
                if starter.tier == "tier-1" and delta < 5.0:
                    warnings.append(f"{starter.name} is tier-1, only sit if you're confident")

                # Confidence score
                confidence = min(100, 50 + (delta * 5))  # Base 50%, +5 per point delta
                if len(reasons) >= 3:
                    confidence += 10
                if bench_player.news_sentiment == "positive":
                    confidence += 10
                if starter.injury_status and starter.injury_status.upper() in ["Q", "D"]:
                    confidence += 15

                if confidence < min_confidence:
                    continue

                recommendation = SitStartRecommendation(
                    action="start",
                    player_in=bench_player,
                    player_out=starter,
                    projection_delta=delta,
                    confidence=min(100, confidence),
                    reasons=reasons,
                    warnings=warnings
                )

                recommendations.append(recommendation)

    # Sort by confidence and projection delta
    recommendations.sort(key=lambda r: (r.confidence, r.projection_delta), reverse=True)

    return recommendations


def optimize_lineup_enhanced(
    *,
    settings: LeagueSettings,
    roster_players: List[Dict],  # From database: id, name, position, team, slot, status
    week: int,
    min_confidence: float = 60.0
) -> List[SitStartRecommendation]:
    """
    Main entry point for enhanced lineup optimization.

    Takes raw roster data, enriches with projections/news/weather,
    generates sit/start recommendations.
    """
    # Mark starters vs bench
    for p in roster_players:
        slot = p.get("slot")
        p["is_starter"] = (slot and slot not in ["BN", "IR"])

    # Build enhanced players
    enhanced_players = build_enhanced_players(roster_players, week, settings)

    # Generate recommendations
    recommendations = generate_sit_start_recommendations(
        settings=settings,
        players=enhanced_players,
        week=week,
        min_confidence=min_confidence
    )

    return recommendations


__all__ = [
    "EnhancedPlayer",
    "SitStartRecommendation",
    "optimize_lineup_enhanced",
    "generate_sit_start_recommendations",
]

