import os
import tempfile
import sqlite3
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import db as dbmod


@contextmanager
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        os.environ["DB_PATH"] = path
        dbmod.migrate()
        yield path
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        os.environ.pop("DB_PATH", None)


def insert_notification(path: str, kind: str, title: str, body: str) -> int:
    connection = sqlite3.connect(path)
    try:
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO notifications(kind, title, body, payload) VALUES(?, ?, ?, '{}')",
            (kind, title, body),
        )
        connection.commit()
        return cursor.lastrowid
    finally:
        connection.close()


def test_list_and_detail_and_mark_read():
    with temp_db() as db_path:
        client = TestClient(app)

        n1 = insert_notification(db_path, "info", "Hello", "World")
        n2 = insert_notification(db_path, "lineup", "Lineup", "Set your lineup")

        r = client.get("/")
        assert r.status_code == 200
        assert "Hello" in r.text and "Lineup" in r.text

        r = client.get(f"/notifications/{n1}")
        assert r.status_code == 200
        assert "World" in r.text

        r = client.post(f"/notifications/{n2}/read", follow_redirects=False)
        assert r.status_code in (302, 303)

        # Ensure it is marked as read in DB
        connection = sqlite3.connect(db_path)
        cur = connection.cursor()
        cur.execute("SELECT is_read FROM notifications WHERE id = ?", (n2,))
        is_read = cur.fetchone()[0]
        connection.close()
        assert is_read == 1


