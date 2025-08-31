from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional

from .db import get_connection


def notify(kind: str, title: str, body: str, payload: Optional[Dict[str, Any]] = None) -> int:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO notifications(kind, title, body, payload) VALUES(?, ?, ?, ?)",
            (kind, title, body, json.dumps(payload or {})),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def list_notifications(kind: Optional[str] = None) -> List[Dict[str, Any]]:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        if kind:
            cursor.execute(
                "SELECT * FROM notifications WHERE kind = ? ORDER BY is_read ASC, created_at DESC",
                (kind,),
            )
        else:
            cursor.execute("SELECT * FROM notifications ORDER BY is_read ASC, created_at DESC")
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        connection.close()


def get_notification(notification_id: int) -> Optional[Dict[str, Any]]:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM notifications WHERE id = ?", (notification_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def mark_read(notification_id: int) -> None:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notification_id,))
        connection.commit()
    finally:
        connection.close()


def unread_count() -> int:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT COUNT(1) AS unread FROM notifications WHERE is_read = 0")
        row = cursor.fetchone()
        return int(row[0]) if row else 0
    finally:
        connection.close()


def latest_settings_payload() -> Optional[Dict[str, Any]]:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT payload FROM notifications WHERE title = ? ORDER BY created_at DESC LIMIT 1",
            ("Detected League Settings",),
        )
        row = cursor.fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0]) if row[0] else None
        except Exception:
            return None
    finally:
        connection.close()


__all__ = [
    "notify",
    "list_notifications",
    "get_notification",
    "mark_read",
    "unread_count",
    "latest_settings_payload",
]


