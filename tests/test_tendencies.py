import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager

from app.store import migrate
from app.tendencies import profile_manager


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


def test_profile_manager_from_transactions():
    with temp_db() as path:
        con = sqlite3.connect(path)
        cur = con.cursor()
        # Seed different transaction kinds with payloads
        cur.execute(
            "INSERT INTO transactions_raw(kind, team_id, raw) VALUES(?,?,?)",
            ("add", "t1", json.dumps({"position": "RB", "faab": 12})),
        )
        cur.execute(
            "INSERT INTO transactions_raw(kind, team_id, raw) VALUES(?,?,?)",
            ("drop", "t1", json.dumps({"position": "WR"})),
        )
        cur.execute(
            "INSERT INTO transactions_raw(kind, team_id, raw) VALUES(?,?,?)",
            ("waiver", "t1", json.dumps({"pos": "WR", "bid": 5})),
        )
        cur.execute(
            "INSERT INTO transactions_raw(kind, team_id, raw) VALUES(?,?,?)",
            ("trade", "t1", json.dumps({"status": "accepted"})),
        )
        con.commit()
        con.close()

        prof = profile_manager("t1")
        assert prof["add_count"] == 2  # add + waiver
        assert prof["drop_count"] == 1
        assert prof["trade_count"] == 1 and prof["trade_acceptance_rate"] == 1.0
        assert prof["faab_spend_total"] == 17.0 and prof["faab_avg_bid"] > 0
        assert prof["position_bias"].get("RB", 0) >= 1
