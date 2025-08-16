import os
import sqlite3
from typing import Iterator


def get_db_path() -> str:
    return os.getenv("DB_PATH", os.path.join(os.getcwd(), "app.db"))


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(get_db_path())
    connection.row_factory = sqlite3.Row
    return connection


def migrate() -> None:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL DEFAULT 'info',
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                payload TEXT,
                is_read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        connection.commit()
    finally:
        connection.close()


def seed_example_data_if_empty() -> None:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT COUNT(1) as cnt FROM notifications")
        count = cursor.fetchone()[0]
        if count == 0:
            cursor.execute(
                "INSERT INTO notifications(kind, title, body, payload) VALUES(?, ?, ?, ?)",
                (
                    "info",
                    "Welcome to Fantasy Bot",
                    "Your Inbox is ready. This is a sample notification.",
                    "{}",
                ),
            )
            cursor.execute(
                "INSERT INTO notifications(kind, title, body, payload) VALUES(?, ?, ?, ?)",
                (
                    "lineup",
                    "Lineup Check Scheduled",
                    "We'll run a lineup sanity check on Thu morning.",
                    "{}",
                ),
            )
            connection.commit()
    finally:
        connection.close()

