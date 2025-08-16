from app.models import LeagueSettings


def test_league_settings_from_yahoo_minimal_defaults():
    raw = {
        "settings": {
            "roster_positions": [
                {"position": "QB", "count": 1},
                {"position": "RB", "count": 2},
                {"position": "WR", "count": 2},
                {"position": "TE", "count": 1},
                {"position": "W/R/T", "count": 1},
                {"position": "BN", "count": 5},
            ],
            "scoring": {"ppr": "full"},
        }
    }

    s = LeagueSettings.from_yahoo(raw)
    assert s.bench_size == 5
    assert s.positional_limits.qb == 1
    assert s.positional_limits.rb == 2
    assert s.positional_limits.wr == 2
    assert s.positional_limits.te == 1
    assert s.positional_limits.flex == 1
    assert s.scoring.ppr == 1.0


def test_league_settings_half_ppr_and_faab_deadline():
    raw = {
        "settings": {
            "roster": {"positions": [{"name": "RB", "count": 2}, {"name": "BN", "count": 6}]},
            "scoring": {"ppr": "half", "pass_td": 6},
            "faab_budget": 200,
            "trade_deadline_week": 10,
        }
    }

    s = LeagueSettings.from_yahoo(raw)
    assert s.bench_size == 6
    assert s.positional_limits.rb == 2
    assert s.scoring.ppr == 0.5
    assert s.scoring.pass_td == 6
    assert s.faab_budget == 200
    assert s.trade_deadline_week == 10


