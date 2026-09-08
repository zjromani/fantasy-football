from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .domain import Decision


@dataclass(frozen=True)
class ApprovalRecord:
    id: str
    decision_id: int
    payload_hash: str
    status: str
    expires_at: str
    consumed_at: str | None


class AuditStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    def migrate(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    score REAL NOT NULL,
                    summary TEXT NOT NULL,
                    inputs TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    source_updated_at TEXT NOT NULL,
                    requires_approval INTEGER NOT NULL,
                    policy_reasons TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    decision_id INTEGER NOT NULL REFERENCES decisions(id),
                    payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    reminded_at TEXT,
                    consumed_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS capabilities (
                    action TEXT PRIMARY KEY,
                    available INTEGER NOT NULL,
                    status_code INTEGER NOT NULL,
                    detail TEXT NOT NULL,
                    checked_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS request_budget (
                    provider TEXT NOT NULL,
                    month TEXT NOT NULL,
                    requests INTEGER NOT NULL,
                    PRIMARY KEY(provider, month)
                );
                CREATE TABLE IF NOT EXISTS execution_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_id INTEGER,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS player_identities (
                    yahoo_key TEXT PRIMARY KEY,
                    fantasypros_id TEXT,
                    name TEXT NOT NULL,
                    nfl_team TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS projection_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    yahoo_key TEXT NOT NULL,
                    week_points REAL NOT NULL,
                    ros_points REAL NOT NULL,
                    source_updated_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS execution_guards (
                    payload_hash TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transaction_watches (
                    transaction_key TEXT PRIMARY KEY,
                    payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def save_decision(self, decision: Decision) -> int:
        payload = canonical_json(decision.payload)
        created_at = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO decisions(
                    kind, score, summary, inputs, payload, payload_hash,
                    source_updated_at, requires_approval, policy_reasons, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.kind,
                    decision.score,
                    decision.summary,
                    canonical_json(decision.inputs),
                    payload,
                    hash_payload(decision.payload),
                    decision.source_updated_at.isoformat(),
                    int(decision.requires_approval),
                    canonical_json(list(decision.policy_reasons)),
                    created_at,
                ),
            )
            return int(cursor.lastrowid)

    def decision(self, decision_id: int) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM decisions WHERE id = ?", (decision_id,)
            ).fetchone()
        if not row:
            raise KeyError(f"Unknown decision {decision_id}")
        result = dict(row)
        result["inputs"] = json.loads(result["inputs"])
        result["payload"] = json.loads(result["payload"])
        result["policy_reasons"] = json.loads(result["policy_reasons"])
        return result

    def create_approval(
        self,
        approval_id: str,
        decision_id: int,
        payload_hash: str,
        expires_at: str,
    ) -> ApprovalRecord:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO approvals(
                    id, decision_id, payload_hash, status, expires_at, created_at
                ) VALUES (?, ?, ?, 'pending', ?, ?)
                """,
                (approval_id, decision_id, payload_hash, expires_at, utc_now()),
            )
        return self.approval(approval_id)

    def pending_approval_for_payload(self, payload_hash: str) -> ApprovalRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id FROM approvals
                WHERE payload_hash = ?
                  AND status = 'pending'
                  AND datetime(expires_at) > datetime('now')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (payload_hash,),
            ).fetchone()
        return self.approval(row["id"]) if row else None

    def approval(self, approval_id: str) -> ApprovalRecord:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE id = ?", (approval_id,)
            ).fetchone()
        if not row:
            raise KeyError(f"Unknown approval {approval_id}")
        return ApprovalRecord(
            id=row["id"],
            decision_id=row["decision_id"],
            payload_hash=row["payload_hash"],
            status=row["status"],
            expires_at=row["expires_at"],
            consumed_at=row["consumed_at"],
        )

    def consume_approval(self, approval_id: str, payload_hash: str) -> ApprovalRecord:
        now = datetime.now(UTC)
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE id = ?", (approval_id,)
            ).fetchone()
            if not row:
                raise KeyError(f"Unknown approval {approval_id}")
            if row["payload_hash"] != payload_hash:
                raise ValueError("Approval payload hash mismatch")
            if row["status"] != "pending" or row["consumed_at"]:
                raise ValueError("Approval has already been consumed")
            if datetime.fromisoformat(row["expires_at"]) <= now:
                connection.execute(
                    "UPDATE approvals SET status = 'expired' WHERE id = ?",
                    (approval_id,),
                )
                raise ValueError("Approval expired")
            connection.execute(
                """
                UPDATE approvals
                SET status = 'approved', consumed_at = ?
                WHERE id = ?
                """,
                (now.isoformat(), approval_id),
            )
        return self.approval(approval_id)

    def save_capability(
        self, action: str, available: bool, status_code: int, detail: str
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO capabilities(
                    action, available, status_code, detail, checked_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(action) DO UPDATE SET
                    available=excluded.available,
                    status_code=excluded.status_code,
                    detail=excluded.detail,
                    checked_at=excluded.checked_at
                """,
                (action, int(available), status_code, detail, utc_now()),
            )

    def capability(self, action: str) -> bool | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT available FROM capabilities WHERE action = ?",
                (action,),
            ).fetchone()
        return bool(row["available"]) if row else None

    def consume_dispatched_approval(
        self,
        approval_id: str,
        decision_id: int,
        payload_hash: str,
    ) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE approvals
                SET status = 'approved', consumed_at = ?
                WHERE id = ?
                  AND decision_id = ?
                  AND payload_hash = ?
                  AND status = 'pending'
                  AND datetime(expires_at) > datetime('now')
                """,
                (utc_now(), approval_id, decision_id, payload_hash),
            )
            if cursor.rowcount != 1:
                raise ValueError("No matching pending approval")

    def save_execution(self, decision_id: int | None, status: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO execution_events(decision_id, status, created_at)
                VALUES (?, ?, ?)
                """,
                (decision_id, status, utc_now()),
            )

    def claim_execution(self, payload_hash: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO execution_guards(payload_hash, status, updated_at)
                VALUES (?, 'executing', ?)
                ON CONFLICT(payload_hash) DO UPDATE SET
                    status='executing',
                    updated_at=excluded.updated_at
                WHERE execution_guards.status = 'failed'
                """,
                (payload_hash, utc_now()),
            )
            return cursor.rowcount == 1

    def finish_execution(self, payload_hash: str, status: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE execution_guards
                SET status = ?, updated_at = ?
                WHERE payload_hash = ?
                """,
                (status, utc_now(), payload_hash),
            )

    def watch_transaction(
        self, transaction_key: str, payload_hash: str, status: str
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO transaction_watches(
                    transaction_key, payload_hash, status, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(transaction_key) DO UPDATE SET
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (transaction_key, payload_hash, status, utc_now()),
            )

    def pending_transactions(self) -> list[dict[str, str]]:
        with self.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT transaction_key, payload_hash, status
                    FROM transaction_watches
                    WHERE status NOT IN (
                        'successful', 'accepted', 'rejected', 'vetoed', 'failed'
                    )
                    """
                )
            ]

    def save_projection_inputs(self, projections: list[dict[str, Any]]) -> None:
        with self.connect() as connection:
            for projection in projections:
                connection.execute(
                    """
                    INSERT INTO player_identities(
                        yahoo_key, fantasypros_id, name, nfl_team, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(yahoo_key) DO UPDATE SET
                        fantasypros_id=excluded.fantasypros_id,
                        name=excluded.name,
                        nfl_team=excluded.nfl_team,
                        updated_at=excluded.updated_at
                    """,
                    (
                        projection["player_key"],
                        projection.get("fantasypros_id"),
                        projection["name"],
                        projection.get("nfl_team", ""),
                        projection["source_updated_at"],
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO projection_snapshots(
                        yahoo_key, week_points, ros_points,
                        source_updated_at, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        projection["player_key"],
                        projection.get("week_points", 0),
                        projection.get("ros_points", 0),
                        projection["source_updated_at"],
                        utc_now(),
                    ),
                )

    def increment_budget(self, provider: str, limit: int) -> int:
        month = datetime.now(UTC).strftime("%Y-%m")
        with self.connect() as connection:
            row = connection.execute(
                "SELECT requests FROM request_budget WHERE provider = ? AND month = ?",
                (provider, month),
            ).fetchone()
            current = int(row["requests"]) if row else 0
            if current >= limit:
                raise RuntimeError(f"{provider} monthly request budget exhausted")
            connection.execute(
                """
                INSERT INTO request_budget(provider, month, requests)
                VALUES (?, ?, 1)
                ON CONFLICT(provider, month)
                DO UPDATE SET requests = requests + 1
                """,
                (provider, month),
            )
        return current + 1

    def export_redacted(self) -> dict[str, list[dict[str, Any]]]:
        tables = (
            "decisions",
            "approvals",
            "capabilities",
            "execution_events",
            "player_identities",
            "projection_snapshots",
            "execution_guards",
            "transaction_watches",
        )
        result = {}
        with self.connect() as connection:
            for table in tables:
                rows = [
                    dict(row) for row in connection.execute(f"SELECT * FROM {table}")
                ]
                for row in rows:
                    row.pop("payload", None)
                result[table] = rows
        return result

    def weekly_counts(self) -> dict[str, int]:
        with self.connect() as connection:
            decisions = connection.execute(
                """
                SELECT COUNT(*) FROM decisions
                WHERE datetime(created_at) >= datetime('now', '-7 days')
                """
            ).fetchone()[0]
            approvals = connection.execute(
                """
                SELECT COUNT(*) FROM approvals
                WHERE datetime(created_at) >= datetime('now', '-7 days')
                """
            ).fetchone()[0]
            executions = connection.execute(
                """
                SELECT COUNT(*) FROM execution_events
                WHERE datetime(created_at) >= datetime('now', '-7 days')
                """
            ).fetchone()[0]
        return {
            "decisions": int(decisions),
            "approvals": int(approvals),
            "executions": int(executions),
        }

    def executions_this_week(self, kind: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*)
                FROM execution_events events
                JOIN decisions ON decisions.id = events.decision_id
                WHERE decisions.kind = ?
                  AND events.status LIKE 'executed%'
                  AND strftime('%Y-%W', datetime(events.created_at)) =
                      strftime('%Y-%W', 'now')
                """,
                (kind,),
            ).fetchone()
        return int(row[0])


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def hash_payload(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def utc_now() -> str:
    return datetime.now(UTC).isoformat()
