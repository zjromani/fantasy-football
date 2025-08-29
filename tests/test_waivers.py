import os
import sqlite3
import tempfile
from contextlib import contextmanager

from app.store import migrate
from app.waivers import rank_free_agents, recommend_waivers
from app.models import LeagueSettings


@contextmanager
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        os.environ["DB_PATH"] = path
        migrate()
        yield path
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        os.environ.pop("DB_PATH", None)


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


def test_rank_and_persist_waivers():
    with temp_db() as path:
        s = settings_full_ppr()
        current = {"RB": 1, "WR": 2, "QB": 1, "TE": 1}
        free_agents = [
            {"id": "p1", "name": "RB A", "position": "RB", "proj_base": 10, "trend_last2": 2, "schedule_next4": 1},
            {"id": "p2", "name": "WR B", "position": "WR", "proj_base": 11, "trend_last2": -1, "schedule_next4": 0},
            {"id": "p3", "name": "RB C", "position": "RB", "proj_base": 8, "trend_last2": 1, "schedule_next4": 2},
        ]
        recs = rank_free_agents(settings=s, current_starters_count=current, free_agents=free_agents, faab_remaining=50, waiver_type="faab", top_n=3)
        assert recs[0].name in {"RB A", "WR B"}
        assert recs[0].faab_max >= recs[0].faab_min >= 0

        recs2, msg_id = recommend_waivers(settings=s, current_starters_count=current, free_agents=free_agents, faab_remaining=50, waiver_type="faab", top_n=3)
        assert msg_id > 0 and len(recs2) == 3

        con = sqlite3.connect(path)
        cur = con.cursor()
        cur.execute("SELECT COUNT(1) FROM recommendations WHERE kind='waivers'")
        cnt = cur.fetchone()[0]
        con.close()
        assert cnt == 3
