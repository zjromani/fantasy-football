import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager

from app import db as dbmod
from app.store import migrate, upsert_player, upsert_team, upsert_roster, upsert_matchup, record_snapshot, main


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


def test_migrate_and_upserts_and_snapshot():
    with temp_db() as path:
        upsert_player(player_id="p1", name="A Player", position="RB", team="NYJ", bye_week=7)
        upsert_team(team_id="t1", name="Team One", manager="Alice", abbrev="ONE")
        upsert_roster(team_id="t1", player_id="p1", week=1, status="START", slot="RB")
        upsert_matchup(week=1, team_id="t1", opponent_id="t2", projected=100.5, actual=None, result=None)

        digest, inserted = record_snapshot(endpoint="league/123", params={"a": 1}, raw=json.dumps({"ok": True}))
        assert inserted is True
        digest2, inserted2 = record_snapshot(endpoint="league/123", params={"a": 1}, raw=json.dumps({"ok": True}))
        assert digest2 == digest and inserted2 is False

        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute("SELECT id,name,position,team,bye_week FROM players WHERE id='p1'")
        row = cur.fetchone()
        assert row[1] == "A Player" and row[2] == "RB" and row[3] == "NYJ" and row[4] == 7
        conn.close()


def test_cli_migrate():
    with temp_db():
        assert main(["migrate"]) == 0


