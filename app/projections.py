"""
Player projections module.

Provides weekly fantasy projections with pluggable sources.

Current sources:
- Placeholder/mock projections (always available)
- Future: Add your own projections source (FantasyPros, Sleeper, etc.)

Note: Finding reliable, free projection APIs is challenging. Most require paid subscriptions.
The app works great without projections - AI uses news, player stats, and matchups instead.
"""
from __future__ import annotations

import os
import json
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


@dataclass
class PlayerProjection:
    """Weekly fantasy projection for a player."""
    player_name: str
    position: str
    team: str
    week: int
    
    # Standard stats
    pass_yds: Optional[float] = None
    pass_tds: Optional[float] = None
    pass_ints: Optional[float] = None
    rush_yds: Optional[float] = None
    rush_tds: Optional[float] = None
    receptions: Optional[float] = None
    rec_yds: Optional[float] = None
    rec_tds: Optional[float] = None
    
    # Fantasy points (various scoring formats)
    fantasy_points_ppr: Optional[float] = None
    fantasy_points_half_ppr: Optional[float] = None
    fantasy_points_standard: Optional[float] = None
    
    # Metadata
    source: str = "fantasypros"
    fetched_at: Optional[datetime] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "player_name": self.player_name,
            "position": self.position,
            "team": self.team,
            "week": self.week,
            "pass_yds": self.pass_yds,
            "pass_tds": self.pass_tds,
            "pass_ints": self.pass_ints,
            "rush_yds": self.rush_yds,
            "rush_tds": self.rush_tds,
            "receptions": self.receptions,
            "rec_yds": self.rec_yds,
            "rec_tds": self.rec_tds,
            "fantasy_points_ppr": self.fantasy_points_ppr,
            "fantasy_points_half_ppr": self.fantasy_points_half_ppr,
            "fantasy_points_standard": self.fantasy_points_standard,
            "source": self.source,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> PlayerProjection:
        """Create from dictionary."""
        fetched_at = None
        if data.get("fetched_at"):
            try:
                fetched_at = datetime.fromisoformat(data["fetched_at"])
            except Exception:
                pass
        return cls(
            player_name=data["player_name"],
            position=data["position"],
            team=data["team"],
            week=data["week"],
            pass_yds=data.get("pass_yds"),
            pass_tds=data.get("pass_tds"),
            pass_ints=data.get("pass_ints"),
            rush_yds=data.get("rush_yds"),
            rush_tds=data.get("rush_tds"),
            receptions=data.get("receptions"),
            rec_yds=data.get("rec_yds"),
            rec_tds=data.get("rec_tds"),
            fantasy_points_ppr=data.get("fantasy_points_ppr"),
            fantasy_points_half_ppr=data.get("fantasy_points_half_ppr"),
            fantasy_points_standard=data.get("fantasy_points_standard"),
            source=data.get("source", "fantasypros"),
            fetched_at=fetched_at,
        )


class ProjectionsCache:
    """File-based cache for projections."""
    
    def __init__(self, cache_dir: str = ".cache/projections"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _cache_key(self, week: int, position: Optional[str] = None) -> str:
        """Generate cache key."""
        key = f"week_{week}"
        if position:
            key += f"_pos_{position}"
        return hashlib.md5(key.encode()).hexdigest()
    
    def get(self, week: int, position: Optional[str] = None, max_age_hours: int = 24) -> Optional[List[PlayerProjection]]:
        """Get cached projections if fresh."""
        cache_file = self.cache_dir / f"{self._cache_key(week, position)}.json"
        if not cache_file.exists():
            return None
        
        try:
            data = json.loads(cache_file.read_text())
            cached_at = datetime.fromisoformat(data["cached_at"])
            if datetime.now(timezone.utc) - cached_at > timedelta(hours=max_age_hours):
                return None
            return [PlayerProjection.from_dict(item) for item in data["projections"]]
        except Exception:
            return None
    
    def set(self, week: int, projections: List[PlayerProjection], position: Optional[str] = None) -> None:
        """Cache projections."""
        cache_file = self.cache_dir / f"{self._cache_key(week, position)}.json"
        data = {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "week": week,
            "position": position,
            "projections": [p.to_dict() for p in projections],
        }
        cache_file.write_text(json.dumps(data, indent=2))


class ProjectionsAPI:
    """
    Pluggable projections API.
    
    To add your own projections source:
    1. Implement fetch_projections() to return List[PlayerProjection]
    2. Update get_projections() to use your implementation
    
    Common sources:
    - FantasyPros (requires paid API key)
    - Sleeper (free but requires parsing their app data)
    - Yahoo (already integrated via yahoo_client)
    - Manual CSV upload of projections from any source
    """
    
    def fetch_projections(self, season: int, week: int, position: Optional[str] = None) -> List[PlayerProjection]:
        """
        Fetch projections from your preferred source.
        
        For now, returns empty list. The app works great without projections -
        AI uses real-time news, player stats from Yahoo, and matchup data instead.
        """
        # TODO: Add your projections source here
        # Example integrations:
        # - ESPN API (if you have insider access)
        # - Sleeper app data
        # - FantasyPros (with paid API key)
        # - CSV file upload
        return []


def get_projections(
    week: int,
    position: Optional[str] = None,
    season: Optional[int] = None,
    use_cache: bool = True,
    max_age_hours: int = 24,
) -> List[PlayerProjection]:
    """
    Get weekly projections for players.
    
    Args:
        week: NFL week number (1-18)
        position: Filter by position (QB, RB, WR, TE, etc.)
        season: NFL season year (defaults to current year)
        use_cache: Whether to use cached data
        max_age_hours: Maximum age of cached data in hours
    
    Returns:
        List of PlayerProjection objects
    """
    if season is None:
        season = datetime.now().year
    
    cache = ProjectionsCache()
    
    # Try cache first
    if use_cache:
        cached = cache.get(week, position, max_age_hours)
        if cached:
            return cached
    
    # Fetch from projections API (pluggable)
    api = ProjectionsAPI()
    projections = api.fetch_projections(season, week, position)
    
    # Cache results
    if projections and use_cache:
        cache.set(week, projections, position)
    
    return projections


def get_player_projection(player_name: str, week: int, position: Optional[str] = None) -> Optional[PlayerProjection]:
    """Get projection for a specific player."""
    projections = get_projections(week, position)
    
    # Fuzzy match on player name
    player_lower = player_name.lower().strip()
    for proj in projections:
        if player_lower in proj.player_name.lower():
            return proj
    
    return None


__all__ = ["PlayerProjection", "get_projections", "get_player_projection"]

