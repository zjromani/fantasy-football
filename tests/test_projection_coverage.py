from __future__ import annotations

import json
from pathlib import Path

from app.identity import (
    compact_name,
    lookup_provider_entry,
    map_players,
    normalize_name,
)
from app.normalize import normalize_snapshot, validate_projection_coverage

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "projection_coverage_snapshot.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text())


def test_compact_name_matches_apostrophe_and_spaced_variants() -> None:
    assert normalize_name("De'Von Achane") == "devon achane"
    assert normalize_name("De Von Achane") == "de von achane"
    assert compact_name("De'Von Achane") == compact_name("De Von Achane")


def test_lookup_matches_team_defense_by_nickname_and_team() -> None:
    weekly = {
        ("", "GB"): {
            "player_name": "Green Bay Packers",
            "team": "GB",
            "position": "DST",
            "fpts": 8.2,
            "_has_stats": True,
        }
    }
    yahoo_defense = {
        "name": "Packers",
        "nfl_team": "GB",
        "position": "DEF",
    }

    match = lookup_provider_entry(weekly, yahoo_defense)

    assert match["fpts"] == 8.2


def test_validate_projection_coverage_passes_for_fixture_roster() -> None:
    state = normalize_snapshot(
        FIXTURE,
        league_key="461.l.196780",
        team_key="461.p.196780.t.1",
    )

    assert state["projection_errors"] == []


def test_validate_projection_coverage_reports_missing_entries() -> None:
    player = {"name": "Mystery Player", "nfl_team": "NYJ", "position": "WR"}

    errors = validate_projection_coverage(player, {}, {})

    assert errors == [
        "missing weekly projection for Mystery Player",
        "missing ROS ranking for Mystery Player",
    ]


def test_map_players_uses_shared_lookup_rules() -> None:
    yahoo_players = [
        {
            "player_key": "461.p.33537",
            "name": "De'Von Achane",
            "nfl_team": "MIA",
            "position": "RB",
        }
    ]
    fantasypros_players = [
        {
            "player_name": "De Von Achane",
            "team": "MIA",
            "position": "RB",
            "id": "23133",
        }
    ]

    identities = map_players(yahoo_players, fantasypros_players)

    assert len(identities) == 1
    assert identities[0].fantasypros_id == "23133"
