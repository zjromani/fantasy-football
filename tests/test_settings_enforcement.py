import pytest

from app.models import LeagueSettings
from app.scoring import compute_points
from app.lineup import optimize_lineup


def test_lineup_requires_settings():
    with pytest.raises(Exception):
        # Expect failure if we pass an obviously invalid settings object
        optimize_lineup(settings=None, candidates=[], current_starters={})  # type: ignore[arg-type]


def test_scoring_requires_settings():
    with pytest.raises(Exception):
        compute_points("WR", {"rec": 1}, None)  # type: ignore[arg-type]




