from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parents[1]


def run_cli(*args: str, env: dict[str, str] | None = None) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", *args],
        cwd=ROOT,
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def write_league(path: Path) -> None:
    path.write_text(
        """
name: Test League
league_id: "1"
league_key: "449.l.1"
team_key: "449.l.1.t.1"
roster:
  QB: 1
  RB: 1
  W/R/T: 1
  BN: 2
scoring:
  rush_yd: 0.125
""".strip()
    )


def write_state(path: Path) -> None:
    now = datetime.now(UTC).isoformat()
    players = [
        ("qb", "Quarterback", "QB", 18, 180),
        ("rb1", "Starter Back", "RB", 8, 100),
        ("rb2", "Bench Back", "RB", 14, 130),
        ("wr", "Wide Receiver", "WR", 12, 120),
        ("fa", "Free Agent", "RB", 16, 170),
    ]
    path.write_text(
        json.dumps(
            {
                "source_updated_at": now,
                "week": 1,
                "league_key": "449.l.1",
                "team_key": "449.l.1.t.1",
                "fab_remaining": 100,
                "roster": [
                    {
                        "player_key": "qb",
                        "eligible_positions": ["QB"],
                        "selected_position": "QB",
                    },
                    {
                        "player_key": "rb1",
                        "eligible_positions": ["RB"],
                        "selected_position": "RB",
                    },
                    {
                        "player_key": "rb2",
                        "eligible_positions": ["RB"],
                        "selected_position": "BN",
                    },
                    {
                        "player_key": "wr",
                        "eligible_positions": ["WR"],
                        "selected_position": "W/R/T",
                    },
                ],
                "projections": [
                    {
                        "player_key": key,
                        "name": name,
                        "position": position,
                        "week_points": week,
                        "ros_points": ros,
                        "source_updated_at": now,
                    }
                    for key, name, position, week, ros in players
                ],
                "free_agent_keys": ["fa"],
                "waiver_deadlines": {
                    "fa": (datetime.now(UTC) + timedelta(days=1)).isoformat()
                },
                "ros_ranks": {"qb": 10, "rb1": 80, "rb2": 60, "wr": 20, "fa": 40},
                "protected_player_keys": [],
                "starter_vacancies": [],
                "roster_need": {},
                "incoming_trades": [],
                "opponents": {},
            }
        )
    )


def test_public_cli_runs_two_clean_dry_run_cycles(tmp_path: Path) -> None:
    database = tmp_path / "audit.sqlite"
    league = tmp_path / "league.yml"
    state = tmp_path / "state.json"
    write_league(league)
    write_state(state)
    arguments = (
        "--db",
        str(database),
        "--league-config",
        str(league),
        "run-all",
        "--state",
        str(state),
    )

    first = run_cli(*arguments, env={"DRY_RUN": "true", "WRITES_ENABLED": "false"})
    second = run_cli(*arguments, env={"DRY_RUN": "true", "WRITES_ENABLED": "false"})

    assert first["status"] == second["status"] == "ok"
    assert len(first["decision_ids"]) == len(second["decision_ids"]) == 2
    with sqlite3.connect(database) as connection:
        decisions = connection.execute(
            "SELECT kind, payload_hash FROM decisions ORDER BY id"
        ).fetchall()
    assert [row[0] for row in decisions] == ["lineup", "fab", "lineup", "fab"]
    assert decisions[0][1] == decisions[2][1]
    assert decisions[1][1] == decisions[3][1]

    direct_fab = run_cli(
        "--db",
        str(database),
        "--league-config",
        str(league),
        "execute",
        "--decision-id",
        "2",
        env={"DRY_RUN": "false", "WRITES_ENABLED": "true"},
    )
    assert direct_fab["status"] == "blocked: approval required"


def test_cli_exports_redacted_audit(tmp_path: Path) -> None:
    database = tmp_path / "audit.sqlite"
    output = tmp_path / "audit.json"
    league = tmp_path / "league.yml"
    write_league(league)

    result = run_cli(
        "--db",
        str(database),
        "--league-config",
        str(league),
        "export-audit",
        "--output",
        str(output),
    )

    assert result["status"] == "ok"
    assert "payload" not in output.read_text()
