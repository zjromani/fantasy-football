import os
import sqlite3
import tempfile
from contextlib import contextmanager

from app.inbox import notify, list_notifications, get_notification, mark_read, unread_count
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


def test_inbox_api_crud():
    with temp_db():
        n_id = notify("waivers", "Target RB", "Bid 11-15 FAAB", {"player_id": "p1"})
        assert isinstance(n_id, int)
        assert unread_count() == 1

        items = list_notifications()
        assert len(items) == 1 and items[0]["id"] == n_id

        item = get_notification(n_id)
        assert item is not None and item["title"] == "Target RB"

        mark_read(n_id)
        assert unread_count() == 0


