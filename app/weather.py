"""
Weather data integration for fantasy football.

Fetches game-day weather conditions that impact fantasy performance:
- Wind speed (affects passing/kicking accuracy)
- Precipitation (favors running game)
- Temperature (affects ball handling, player performance)
- Dome/outdoor venue tracking

Uses Open-Meteo API (free, no API key required).
"""
from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


@dataclass
class WeatherCondition:
    """Weather conditions for an NFL game."""
    home_team: str
    away_team: str
    game_time: datetime

    # Weather data
    temperature_f: Optional[float] = None
    wind_speed_mph: Optional[float] = None
    precipitation_chance: Optional[float] = None  # 0-100
    is_dome: bool = False

    # Derived
    weather_impact: str = "neutral"  # good, neutral, bad, severe

    def to_dict(self) -> dict:
        return {
            "home_team": self.home_team,
            "away_team": self.away_team,
            "game_time": self.game_time.isoformat(),
            "temperature_f": self.temperature_f,
            "wind_speed_mph": self.wind_speed_mph,
            "precipitation_chance": self.precipitation_chance,
            "is_dome": self.is_dome,
            "weather_impact": self.weather_impact,
        }

    def get_impact_description(self) -> str:
        """Human-readable weather impact."""
        if self.is_dome:
            return "Dome (perfect conditions)"

        issues = []
        if self.wind_speed_mph and self.wind_speed_mph > 15:
            issues.append(f"High winds ({self.wind_speed_mph:.0f} mph)")
        if self.precipitation_chance and self.precipitation_chance > 50:
            issues.append(f"Rain likely ({self.precipitation_chance:.0f}%)")
        if self.temperature_f and self.temperature_f < 25:
            issues.append(f"Very cold ({self.temperature_f:.0f}°F)")

        if not issues:
            return "Good conditions"
        return ", ".join(issues)


class WeatherCache:
    """Simple file-based cache for weather data."""

    def __init__(self, cache_dir: str = ".cache/weather"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_key(self, week: int, season: int) -> str:
        return f"week{week}_{season}"

    def get(self, week: int, season: int, max_age_hours: int = 6) -> Optional[List[dict]]:
        """Get cached weather if not expired."""
        cache_file = self.cache_dir / f"{self._cache_key(week, season)}.json"
        if not cache_file.exists():
            return None

        try:
            data = json.loads(cache_file.read_text())
            cached_at = datetime.fromisoformat(data["cached_at"])
            if datetime.now(timezone.utc) - cached_at > timedelta(hours=max_age_hours):
                return None
            return data["items"]
        except Exception:
            return None

    def set(self, week: int, season: int, items: List[dict]) -> None:
        """Cache weather data."""
        cache_file = self.cache_dir / f"{self._cache_key(week, season)}.json"
        data = {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "items": items,
        }
        cache_file.write_text(json.dumps(data, indent=2))


# NFL stadiums with coordinates and dome status
NFL_STADIUMS = {
    "ARI": {"name": "State Farm Stadium", "lat": 33.5276, "lon": -112.2626, "dome": True},
    "ATL": {"name": "Mercedes-Benz Stadium", "lat": 33.7553, "lon": -84.4006, "dome": True},
    "BAL": {"name": "M&T Bank Stadium", "lat": 39.2780, "lon": -76.6227, "dome": False},
    "BUF": {"name": "Highmark Stadium", "lat": 42.7738, "lon": -78.7870, "dome": False},
    "CAR": {"name": "Bank of America Stadium", "lat": 35.2258, "lon": -80.8530, "dome": False},
    "CHI": {"name": "Soldier Field", "lat": 41.8623, "lon": -87.6167, "dome": False},
    "CIN": {"name": "Paycor Stadium", "lat": 39.0954, "lon": -84.5160, "dome": False},
    "CLE": {"name": "Cleveland Browns Stadium", "lat": 41.5061, "lon": -81.6995, "dome": False},
    "DAL": {"name": "AT&T Stadium", "lat": 32.7473, "lon": -97.0945, "dome": True},
    "DEN": {"name": "Empower Field", "lat": 39.7439, "lon": -105.0201, "dome": False},
    "DET": {"name": "Ford Field", "lat": 42.3400, "lon": -83.0456, "dome": True},
    "GB": {"name": "Lambeau Field", "lat": 44.5013, "lon": -88.0622, "dome": False},
    "HOU": {"name": "NRG Stadium", "lat": 29.6847, "lon": -95.4107, "dome": True},
    "IND": {"name": "Lucas Oil Stadium", "lat": 39.7601, "lon": -86.1639, "dome": True},
    "JAX": {"name": "TIAA Bank Field", "lat": 30.3239, "lon": -81.6373, "dome": False},
    "KC": {"name": "Arrowhead Stadium", "lat": 39.0489, "lon": -94.4839, "dome": False},
    "LV": {"name": "Allegiant Stadium", "lat": 36.0909, "lon": -115.1833, "dome": True},
    "LAC": {"name": "SoFi Stadium", "lat": 33.9535, "lon": -118.3392, "dome": True},
    "LAR": {"name": "SoFi Stadium", "lat": 33.9535, "lon": -118.3392, "dome": True},
    "MIA": {"name": "Hard Rock Stadium", "lat": 25.9580, "lon": -80.2389, "dome": False},
    "MIN": {"name": "U.S. Bank Stadium", "lat": 44.9738, "lon": -93.2575, "dome": True},
    "NE": {"name": "Gillette Stadium", "lat": 42.0909, "lon": -71.2643, "dome": False},
    "NO": {"name": "Caesars Superdome", "lat": 29.9511, "lon": -90.0812, "dome": True},
    "NYG": {"name": "MetLife Stadium", "lat": 40.8128, "lon": -74.0742, "dome": False},
    "NYJ": {"name": "MetLife Stadium", "lat": 40.8128, "lon": -74.0742, "dome": False},
    "PHI": {"name": "Lincoln Financial Field", "lat": 39.9008, "lon": -75.1675, "dome": False},
    "PIT": {"name": "Acrisure Stadium", "lat": 40.4468, "lon": -80.0158, "dome": False},
    "SF": {"name": "Levi's Stadium", "lat": 37.4032, "lon": -121.9700, "dome": False},
    "SEA": {"name": "Lumen Field", "lat": 47.5952, "lon": -122.3316, "dome": False},
    "TB": {"name": "Raymond James Stadium", "lat": 27.9759, "lon": -82.5033, "dome": False},
    "TEN": {"name": "Nissan Stadium", "lat": 36.1665, "lon": -86.7713, "dome": False},
    "WAS": {"name": "FedExField", "lat": 38.9076, "lon": -76.8645, "dome": False},
}


class WeatherAPI:
    """Fetch weather data from Open-Meteo API."""

    def __init__(self, cache: Optional[WeatherCache] = None):
        self.cache = cache or WeatherCache()
        self.client = httpx.Client(timeout=30.0)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def _fetch_forecast(self, lat: float, lon: float, date: datetime) -> dict:
        """Fetch weather forecast for a specific location and date."""
        # Open-Meteo API - free, no key required
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "temperature_2m,precipitation_probability,wind_speed_10m",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "timezone": "America/New_York",
            "forecast_days": 7,
        }

        response = self.client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def get_game_weather(self, home_team: str, away_team: str, game_time: datetime) -> WeatherCondition:
        """Get weather conditions for a specific game."""
        stadium = NFL_STADIUMS.get(home_team)

        if not stadium:
            # Unknown team, return neutral
            return WeatherCondition(
                home_team=home_team,
                away_team=away_team,
                game_time=game_time,
                weather_impact="neutral"
            )

        # Domes have perfect conditions
        if stadium["dome"]:
            return WeatherCondition(
                home_team=home_team,
                away_team=away_team,
                game_time=game_time,
                is_dome=True,
                temperature_f=72.0,
                wind_speed_mph=0.0,
                precipitation_chance=0.0,
                weather_impact="good"
            )

        try:
            # Fetch forecast
            data = self._fetch_forecast(stadium["lat"], stadium["lon"], game_time)

            # Find the closest hour to game time
            times = data.get("hourly", {}).get("time", [])
            temps = data.get("hourly", {}).get("temperature_2m", [])
            precip = data.get("hourly", {}).get("precipitation_probability", [])
            winds = data.get("hourly", {}).get("wind_speed_10m", [])

            # Find index closest to game time
            game_hour = game_time.strftime("%Y-%m-%dT%H:00")
            idx = times.index(game_hour) if game_hour in times else 0

            temperature = temps[idx] if idx < len(temps) else None
            precipitation = precip[idx] if idx < len(precip) else None
            wind = winds[idx] if idx < len(winds) else None

            # Determine impact
            impact = "neutral"
            if wind and wind > 20:
                impact = "severe"
            elif wind and wind > 15 or (precipitation and precipitation > 70):
                impact = "bad"
            elif temperature and temperature < 20:
                impact = "bad"
            else:
                impact = "good"

            return WeatherCondition(
                home_team=home_team,
                away_team=away_team,
                game_time=game_time,
                temperature_f=temperature,
                wind_speed_mph=wind,
                precipitation_chance=precipitation,
                is_dome=False,
                weather_impact=impact
            )

        except Exception as e:
            print(f"[WEATHER] Error fetching weather for {home_team}: {e}")
            # Return neutral on error
            return WeatherCondition(
                home_team=home_team,
                away_team=away_team,
                game_time=game_time,
                weather_impact="neutral"
            )

    def get_week_weather(self, week: int, season: int = 2024) -> List[WeatherCondition]:
        """Get weather for all games in a specific week."""
        # Check cache first
        cached = self.cache.get(week, season)
        if cached:
            return [WeatherCondition(**item) for item in cached]

        # For now, return empty list - would need NFL schedule API
        # In production, integrate with NFL API or manual schedule
        return []


def get_player_weather_impact(player_team: str, week: int) -> Optional[WeatherCondition]:
    """Get weather impact for a specific player's game this week."""
    api = WeatherAPI()
    # This would need the actual game schedule to determine opponent and game time
    # For now, return None - would integrate with schedule in production
    return None


__all__ = ["WeatherCondition", "WeatherAPI", "get_player_weather_impact", "NFL_STADIUMS"]

