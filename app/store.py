from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from typing import Any, Dict, Optional, Tuple

from .db import get_connection


def migrate() -> None:
    connection = get_connection()
    try:
        c = connection.cursor()
        # notifications (ensure exists as used by app)
        c.execute(
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

        # snapshots for persisted external requests
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT NOT NULL,
                params TEXT,
                content_hash TEXT NOT NULL,
                raw TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(content_hash)
            );
            """
        )

        # core entities
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS players (
                id TEXT PRIMARY KEY,
                name TEXT,
                position TEXT,
                team TEXT,
                bye_week INTEGER,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS teams (
                id TEXT PRIMARY KEY,
                name TEXT,
                manager TEXT,
                abbrev TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS rosters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id TEXT NOT NULL,
                player_id TEXT NOT NULL,
                week INTEGER NOT NULL,
                status TEXT,
                slot TEXT,
                UNIQUE(team_id, player_id, week)
            );
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS matchups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week INTEGER NOT NULL,
                team_id TEXT NOT NULL,
                opponent_id TEXT NOT NULL,
                is_playoffs INTEGER NOT NULL DEFAULT 0,
                projected REAL,
                actual REAL,
                result TEXT,
                UNIQUE(week, team_id)
            );
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions_raw (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT,
                team_id TEXT,
                raw TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                title TEXT,
                body TEXT,
                payload TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )

        # Telemetry tables
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task TEXT NOT NULL,
                started_at TEXT NOT NULL DEFAULT (datetime('now')),
                finished_at TEXT,
                status TEXT,
                tokens_in INTEGER,
                tokens_out INTEGER
            );
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                args TEXT,
                result TEXT,
                error TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(run_id) REFERENCES agent_runs(id)
            );
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                confidence REAL,
                payload TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(run_id) REFERENCES agent_runs(id)
            );
            """
        )

        connection.commit()
    finally:
        connection.close()


# --- Upsert helpers ---
def upsert_player(*, player_id: str, name: str, position: Optional[str] = None, team: Optional[str] = None, bye_week: Optional[int] = None) -> None:
    connection = get_connection()
    try:
        c = connection.cursor()
        c.execute(
            """
            INSERT INTO players(id, name, position, team, bye_week)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                position=excluded.position,
                team=excluded.team,
                bye_week=excluded.bye_week,
                updated_at=datetime('now')
            """,
            (player_id, name, position, team, bye_week),
        )
        connection.commit()
    finally:
        connection.close()


def upsert_team(*, team_id: str, name: str, manager: Optional[str] = None, abbrev: Optional[str] = None) -> None:
    connection = get_connection()
    try:
        c = connection.cursor()
        c.execute(
            """
            INSERT INTO teams(id, name, manager, abbrev)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                manager=excluded.manager,
                abbrev=excluded.abbrev,
                updated_at=datetime('now')
            """,
            (team_id, name, manager, abbrev),
        )
        connection.commit()
    finally:
        connection.close()


def upsert_roster(*, team_id: str, player_id: str, week: int, status: Optional[str] = None, slot: Optional[str] = None) -> None:
    connection = get_connection()
    try:
        c = connection.cursor()
        c.execute(
            """
            INSERT INTO rosters(team_id, player_id, week, status, slot)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(team_id, player_id, week) DO UPDATE SET
                status=excluded.status,
                slot=COALESCE(excluded.slot, slot)
            """,
            (team_id, player_id, week, status, slot),
        )
        connection.commit()
    finally:
        connection.close()


def upsert_matchup(*, week: int, team_id: str, opponent_id: str, is_playoffs: bool = False, projected: Optional[float] = None, actual: Optional[float] = None, result: Optional[str] = None) -> None:
    connection = get_connection()
    try:
        c = connection.cursor()
        c.execute(
            """
            INSERT INTO matchups(week, team_id, opponent_id, is_playoffs, projected, actual, result)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(week, team_id) DO UPDATE SET
                opponent_id=excluded.opponent_id,
                is_playoffs=excluded.is_playoffs,
                projected=excluded.projected,
                actual=excluded.actual,
                result=excluded.result
            """,
            (week, team_id, opponent_id, 1 if is_playoffs else 0, projected, actual, result),
        )
        connection.commit()
    finally:
        connection.close()


# --- Audit / snapshots ---
def record_snapshot(*, endpoint: str, params: Optional[Dict[str, Any]], raw: str) -> Tuple[str, bool]:
    payload = {
        "endpoint": endpoint,
        "params": params or {},
        "raw": raw,
    }
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    connection = get_connection()
    inserted = False
    try:
        c = connection.cursor()
        try:
            c.execute(
                "INSERT INTO snapshots(endpoint, params, content_hash, raw) VALUES(?, ?, ?, ?)",
                (endpoint, json.dumps(params or {}), digest, raw),
            )
            inserted = True
        except sqlite3.IntegrityError:
            # Duplicate content_hash; ignore
            inserted = False
        connection.commit()
    finally:
        connection.close()
    return digest, inserted


def insert_transaction_raw(*, kind: Optional[str], team_id: Optional[str], raw: str) -> None:
    connection = get_connection()
    try:
        c = connection.cursor()
        c.execute(
            "INSERT INTO transactions_raw(kind, team_id, raw) VALUES(?, ?, ?)",
            (kind, team_id, raw),
        )
        connection.commit()
    finally:
        connection.close()


def list_recommendations(status: str = "pending") -> list[dict]:
    connection = get_connection()
    try:
        c = connection.cursor()
        c.execute(
            "SELECT * FROM recommendations WHERE status = ? ORDER BY created_at DESC",
            (status,),
        )
        rows = [dict(r) for r in c.fetchall()]
        return rows
    finally:
        connection.close()


def set_recommendation_status(rec_id: int, status: str) -> None:
    connection = get_connection()
    try:
        c = connection.cursor()
        c.execute("UPDATE recommendations SET status = ? WHERE id = ?", (status, rec_id))
        connection.commit()
    finally:
        connection.close()


def count_pending_recommendations() -> int:
    connection = get_connection()
    try:
        c = connection.cursor()
        # Be resilient if migrations haven't created the table yet
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='recommendations'")
        if not c.fetchone():
            return 0
        c.execute("SELECT COUNT(1) FROM recommendations WHERE status = 'pending'")
        row = c.fetchone()
        return int(row[0]) if row else 0
    finally:
        connection.close()


def get_recommendation(rec_id: int) -> Optional[dict]:
    connection = get_connection()
    try:
        c = connection.cursor()
        c.execute("SELECT * FROM recommendations WHERE id = ?", (rec_id,))
        row = c.fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


# --- Agent telemetry helpers ---
def insert_agent_run(task: str) -> int:
    connection = get_connection()
    try:
        c = connection.cursor()
        c.execute("INSERT INTO agent_runs(task) VALUES(?)", (task,))
        connection.commit()
        return int(c.lastrowid)
    finally:
        connection.close()


def finish_agent_run(run_id: int, status: str, tokens_in: Optional[int] = None, tokens_out: Optional[int] = None) -> None:
    connection = get_connection()
    try:
        c = connection.cursor()
        c.execute(
            "UPDATE agent_runs SET finished_at=datetime('now'), status=?, tokens_in=?, tokens_out=? WHERE id=?",
            (status, tokens_in, tokens_out, run_id),
        )
        connection.commit()
    finally:
        connection.close()


def log_tool_call(run_id: int, name: str, args: str, result: Optional[str] = None, error: Optional[str] = None) -> None:
    connection = get_connection()
    try:
        c = connection.cursor()
        c.execute(
            "INSERT INTO tool_calls(run_id,name,args,result,error) VALUES(?,?,?,?,?)",
            (run_id, name, args, result, error),
        )
        connection.commit()
    finally:
        connection.close()


def insert_decision(run_id: int, kind: str, confidence: Optional[float], payload: str) -> None:
    connection = get_connection()
    try:
        c = connection.cursor()
        c.execute(
            "INSERT INTO decisions(run_id,kind,confidence,payload) VALUES(?,?,?,?)",
            (run_id, kind, confidence, payload),
        )
        connection.commit()
    finally:
        connection.close()


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: python -m app.store migrate", file=sys.stderr)
        return 2
    cmd = argv[0]
    if cmd == "migrate":
        migrate()
        print("migrated")
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


