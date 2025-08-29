import os
import sqlite3
import tempfile
from contextlib import contextmanager

from app.models import LeagueSettings
from app.trades import Player, TeamState, propose_trades, propose_and_notify
from app.store import migrate


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


def test_trade_proposals_and_notify():
    with temp_db():
        s = settings_full_ppr()
        a = TeamState(
            team_id="A",
            starters_by_slot={"RB": 2, "WR": 2, "TE": 1},
            bench_redundancy={"RB": 0, "WR": 1, "TE": 0},
            bye_exposure=1,
            injuries=0,
            schedule_difficulty=1.0,
            manager_profile={},
            roster=[
                Player("a1", "RB1", "RB", proj_next3=45, playoff_proj=30, bye_next3=0, injury=""),
                Player("a2", "WR1", "WR", proj_next3=40, playoff_proj=28, bye_next3=0, injury=""),
            ],
        )
        b = TeamState(
            team_id="B",
            starters_by_slot={"RB": 2, "WR": 2, "TE": 1},
            bench_redundancy={"RB": 2, "WR": 0, "TE": 0},
            bye_exposure=0,
            injuries=0,
            schedule_difficulty=1.5,
            manager_profile={},
            roster=[
                Player("b1", "WR2", "WR", proj_next3=42, playoff_proj=25, bye_next3=0, injury=""),
                Player("b2", "RB2", "RB", proj_next3=38, playoff_proj=27, bye_next3=0, injury=""),
            ],
        )

        props = propose_trades(s, a, b, top_k=3)
        assert len(props) >= 1

        props2, msg_id = propose_and_notify(s, a, b, top_k=2)
        assert msg_id > 0 and len(props2) >= 1
