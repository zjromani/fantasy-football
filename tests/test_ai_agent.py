import os
import sqlite3
import tempfile
from contextlib import contextmanager

from app.store import migrate
from app.inbox import notify
from app.ai.agent import run_agent


@contextmanager
def temp_db():
    import os, tempfile
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


def test_run_agent_posts_message(monkeypatch):
    with temp_db() as _p:
        # Seed fake settings into Inbox for banner
        notify("info", "Detected League Settings", "Loaded.", {"scoring": {"ppr": 1.0}})
        msg_id = run_agent("weekly_brief", {"offline": True})
        assert isinstance(msg_id, int) and msg_id > 0


