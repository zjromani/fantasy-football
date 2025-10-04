"""Tests for weather data integration."""
from datetime import datetime, timezone

from app.weather import WeatherAPI, WeatherCondition, NFL_STADIUMS


def test_dome_stadiums_return_perfect_conditions():
    """Dome stadiums should always return ideal weather."""
    api = WeatherAPI()
    game_time = datetime(2024, 10, 10, 13, 0, tzinfo=timezone.utc)

    # Test a dome stadium (Detroit)
    weather = api.get_game_weather("DET", "GB", game_time)

    assert weather.is_dome is True
    assert weather.temperature_f == 72.0
    assert weather.wind_speed_mph == 0.0
    assert weather.precipitation_chance == 0.0
    assert weather.weather_impact == "good"


def test_weather_cache_roundtrip():
    """Weather cache should store and retrieve data."""
    from app.weather import WeatherCache
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        cache = WeatherCache(cache_dir=tmpdir)

        items = [
            {
                "home_team": "GB",
                "away_team": "CHI",
                "game_time": "2024-10-10T13:00:00+00:00",
                "temperature_f": 45.0,
                "wind_speed_mph": 12.0,
                "precipitation_chance": 30.0,
                "is_dome": False,
                "weather_impact": "neutral"
            }
        ]

        cache.set(week=5, season=2024, items=items)
        retrieved = cache.get(week=5, season=2024)

        assert retrieved is not None
        assert len(retrieved) == 1
        assert retrieved[0]["home_team"] == "GB"
        assert retrieved[0]["temperature_f"] == 45.0


def test_nfl_stadiums_coverage():
    """Ensure all 32 NFL teams have stadium data."""
    # Should have 32 teams (note: LAR and LAC share SoFi)
    assert len(NFL_STADIUMS) >= 32

    # Check some key teams
    assert "GB" in NFL_STADIUMS
    assert "DET" in NFL_STADIUMS
    assert "DAL" in NFL_STADIUMS

    # Check structure
    det = NFL_STADIUMS["DET"]
    assert "name" in det
    assert "lat" in det
    assert "lon" in det
    assert "dome" in det
    assert det["dome"] is True  # Ford Field is a dome


def test_weather_impact_description():
    """Weather descriptions should be human-readable."""
    # Good conditions
    good_weather = WeatherCondition(
        home_team="MIA",
        away_team="BUF",
        game_time=datetime.now(timezone.utc),
        temperature_f=75.0,
        wind_speed_mph=5.0,
        precipitation_chance=10.0,
        weather_impact="good"
    )
    assert "Good conditions" in good_weather.get_impact_description()

    # Bad conditions
    bad_weather = WeatherCondition(
        home_team="BUF",
        away_team="MIA",
        game_time=datetime.now(timezone.utc),
        temperature_f=20.0,
        wind_speed_mph=20.0,
        precipitation_chance=80.0,
        weather_impact="bad"
    )
    desc = bad_weather.get_impact_description()
    assert "wind" in desc.lower() or "rain" in desc.lower() or "cold" in desc.lower()

    # Dome
    dome_weather = WeatherCondition(
        home_team="DET",
        away_team="GB",
        game_time=datetime.now(timezone.utc),
        is_dome=True,
        weather_impact="good"
    )
    assert "Dome" in dome_weather.get_impact_description()

