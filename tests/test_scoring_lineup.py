from app.models import LeagueSettings
from app.scoring import compute_points
from app.lineup import optimize_lineup


def settings_full_ppr():
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
    return LeagueSettings.from_yahoo(raw)


def test_compute_points_offense_and_dst():
    s = settings_full_ppr()
    # WR line: 7 rec, 90 yds, 1 TD
    wr_stats = {"rec": 7, "rec_yd": 90, "rec_td": 1}
    pts = compute_points("WR", wr_stats, s)
    # 7 + 9 + 6 = 22
    assert abs(pts - 22.0) < 1e-6

    # DST: 3 sacks, 1 int, 1 fum_rec, 1 td, 10 PA -> bucket "7-13"=4
    dst_stats = {"sack": 3, "int": 1, "fum_rec": 1, "td": 1, "points_allowed": 10}
    pts_dst = compute_points("DST", dst_stats, s)
    assert abs(pts_dst - (3*1 + 1*2 + 1*2 + 1*6 + 4)) < 1e-6


def test_optimize_lineup_respects_limits_and_rules():
    s = settings_full_ppr()
    candidates = [
        {"id": "a", "position": "RB", "projected": 12.0, "injury": "", "is_bye": False, "tier": "tier-1"},
        {"id": "b", "position": "RB", "projected": 10.0, "injury": "Q", "is_bye": False},
        {"id": "c", "position": "RB", "projected": 16.0, "injury": "", "is_bye": False},
        {"id": "d", "position": "WR", "projected": 15.0, "injury": "", "is_bye": False},
        {"id": "e", "position": "WR", "projected": 14.0, "injury": "D", "is_bye": False},
        {"id": "f", "position": "TE", "projected": 8.0, "injury": "", "is_bye": False},
    ]
    current = {"RB": ["a", "b"], "WR": ["d", "e"], "TE": ["f"]}
    swaps = optimize_lineup(settings=s, candidates=candidates, current_starters=current, delta_threshold_for_tier1=3.0)
    # Expect replacing Q/D where appropriate and filling RB and WR with best
    assert any(sw.in_player_id == "c" and sw.out_player_id in {"a", "b"} for sw in swaps)
    assert all(sw.delta_points >= 0 for sw in swaps)


