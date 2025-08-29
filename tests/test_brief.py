import os
import sqlite3
import tempfile
from contextlib import contextmanager

from app.brief import build_gm_brief, post_gm_brief
from app.models import LeagueSettings
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


def test_build_and_post_gm_brief():
    s = LeagueSettings.from_yahoo({"settings": {"roster_positions": [{"position": "QB", "count": 1}, {"position": "RB", "count": 2}, {"position": "WR", "count": 2}, {"position": "TE", "count": 1}, {"position": "W/R/T", "count": 1}, {"position": "BN", "count": 5}], "scoring": {"ppr": "full"}}})
    title, body, payload = build_gm_brief(s)
    assert "Tuesday GM Brief" in title
    assert "Actions:" in body and "Waivers:" in body and "Trades:" in body
    assert payload["settings"]["scoring"]["ppr"] == 1.0

    with temp_db() as path:
        msg_id = post_gm_brief(s)
        assert msg_id > 0
        con = sqlite3.connect(path)
        cur = con.cursor()
        cur.execute("SELECT COUNT(1) FROM notifications WHERE kind='brief'")
        cnt = cur.fetchone()[0]
        con.close()
        assert cnt == 1


