from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.identity import (
    compact_name,
    index_provider_item,
    index_provider_item_by_id,
    lookup_provider_entry,
    lookup_provider_entry_by_id,
    lookup_ros_entry,
    map_players,
    normalize_name,
    provider_player_id,
)
from app.normalize import normalize_snapshot, validate_projection_coverage

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "projection_coverage_snapshot.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text())


def test_compact_name_matches_apostrophe_and_spaced_variants() -> None:
    assert normalize_name("De'Von Achane") == "devon achane"
    assert normalize_name("De Von Achane") == "de von achane"
    assert compact_name("De'Von Achane") == compact_name("De Von Achane")


def test_first_last_name_key_matches_middle_initial_provider_name() -> None:
    yahoo = {"name": "Jonah Coleman", "nfl_team": "ARI", "position": "RB"}
    weekly = {
        ("jonah coleman", "ARI"): {
            "player_name": "Jonah T Coleman",
            "team": "ARI",
            "position": "RB",
            "stats": {"rush_yd": 42},
            "_has_stats": True,
        }
    }

    match = lookup_provider_entry(weekly, yahoo)

    assert match["stats"]["rush_yd"] == 42


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


def test_validate_projection_coverage_skips_weekly_when_player_on_bye() -> None:
    player = {
        "name": "De'Von Achane",
        "nfl_team": "MIA",
        "position": "RB",
        "bye_week": 6,
    }

    errors = validate_projection_coverage(player, {}, {}, game_week=6)

    assert errors == ["missing ROS ranking for De'Von Achane"]


def test_lookup_indexes_nested_consensus_ranking_player_payload() -> None:
    index: dict[tuple[str, str], dict] = {}
    index_provider_item(
        index,
        {
            "rank_ecr": 12,
            "player": {
                "player_name": "De'Von Achane",
                "player_team_id": "MIA",
                "player_position_id": "RB",
                "player_id": 23133,
            },
        },
    )
    yahoo = {"name": "De'Von Achane", "nfl_team": "MIA", "position": "RB"}

    match = lookup_provider_entry(index, yahoo)

    assert match["rank_ecr"] == 12


def test_normalize_uses_weekly_fpid_to_match_ros_rankings() -> None:
    fixture = json.loads(json.dumps(FIXTURE))
    fixture["fantasypros"]["ros"]["data"]["players"] = [
        {
            "player_id": 23133,
            "player_team_id": "MIA",
            "player_position_id": "RB",
            "rank_ecr": 12,
        },
        {
            "player_id": 8090,
            "player_team_id": "GB",
            "player_position_id": "DST",
            "rank_ecr": 9,
        },
        {
            "player_id": 24781,
            "player_team_id": "NE",
            "player_position_id": "CB",
            "rank_ecr": 142,
        },
    ]

    state = normalize_snapshot(
        fixture,
        league_key="461.l.196780",
        team_key="461.p.196780.t.1",
    )

    assert state["projection_errors"] == []


def test_lookup_ros_matches_when_weekly_and_ros_player_ids_differ() -> None:
    ros_index: dict[tuple[str, str], dict[str, Any]] = {}
    ros_by_id: dict[str, dict[str, Any]] = {}
    index_provider_item_by_id(
        ros_by_id,
        {
            "player_id": 23133,
            "player_name": "De Von Achane",
            "player_team_id": "MIA",
            "player_position_id": "RB",
            "rank_ecr": 12,
        },
    )
    yahoo = {"name": "De'Von Achane", "nfl_team": "MIA", "position": "RB"}
    weekly = {
        "player_name": "De Von Achane",
        "team": "MIA",
        "position": "RB",
        "fpid": "23136",
        "stats": {"rush_yd": 72},
        "_has_stats": True,
    }

    match = lookup_ros_entry(ros_index, ros_by_id, yahoo, weekly)

    assert match["rank_ecr"] == 12


def test_provider_player_id_survives_empty_fpid_in_stats() -> None:
    weekly_index: dict[tuple[str, str], dict] = {}
    index_provider_item(
        weekly_index,
        {
            "fpid": 23136,
            "name": "De Von Achane",
            "team_id": "MIA",
            "position_id": "RB",
            "stats": {"points_half": 18.17, "fpid": ""},
        },
    )
    yahoo = {"name": "De'Von Achane", "nfl_team": "MIA", "position": "RB"}
    weekly = lookup_provider_entry(weekly_index, yahoo)

    assert provider_player_id(weekly) == "23136"


def test_normalize_merges_split_weekly_rows_by_fpid() -> None:
    snapshot = {
        "source_updated_at": "2026-10-11T04:23:35+00:00",
        "week": 6,
        "yahoo": {
            "roster": {
                "team": [
                    {
                        "team_key": "461.p.196780.t.1",
                        "name": "Test Team",
                        "roster": {
                            "0": {
                                "players": {
                                    "0": {
                                        "player": [
                                            {"player_key": "461.p.99901"},
                                            {"name": {"full": "De'Von Achane"}},
                                            {"editorial_team_abbr": "MIA"},
                                            {"display_position": "RB"},
                                            {
                                                "eligible_positions": [
                                                    {"position": "RB"}
                                                ]
                                            },
                                            {
                                                "selected_position": [
                                                    {"position": "RB"}
                                                ]
                                            },
                                        ]
                                    }
                                }
                            }
                        },
                    }
                ]
            },
            "available_players": {},
            "teams": {},
            "transactions": {},
        },
        "fantasypros": {
            "weekly": {
                "data": {
                    "players": [
                        {
                            "fpid": 23136,
                            "name": "De Von Achane",
                            "team_id": "MIA",
                            "position_id": "RB",
                            "stats": {},
                        },
                        {
                            "stats": {
                                "points_half": 18.17,
                                "fpid": "",
                                "player_id": 23136,
                            }
                        },
                    ]
                },
                "fetched_at": "2026-10-11T04:23:35+00:00",
            },
            "ros": {
                "data": {
                    "players": [
                        {
                            "player_id": 23136,
                            "player_team_id": "MIA",
                            "player_position_id": "RB",
                            "rank_ecr": 12,
                        }
                    ]
                },
                "fetched_at": "2026-10-11T04:23:35+00:00",
            },
            "playoffs": {},
        },
    }

    state = normalize_snapshot(
        snapshot,
        league_key="461.l.196780",
        team_key="461.p.196780.t.1",
    )

    assert state["projection_errors"] == []


def test_normalize_matches_live_roster_with_coleman_and_split_weekly_rows() -> None:
    snapshot = {
        "source_updated_at": "2026-10-11T04:23:35+00:00",
        "week": 6,
        "yahoo": {
            "roster": {
                "team": [
                    {
                        "team_key": "461.p.196780.t.1",
                        "name": "Test Team",
                        "roster": {
                            "0": {
                                "players": {
                                    "0": {
                                        "player": [
                                            {"player_key": "461.p.33537"},
                                            {"name": {"full": "De'Von Achane"}},
                                            {"editorial_team_abbr": "MIA"},
                                            {"display_position": "RB"},
                                            {
                                                "eligible_positions": [
                                                    {"position": "RB"}
                                                ]
                                            },
                                            {
                                                "selected_position": [
                                                    {"position": "RB"}
                                                ]
                                            },
                                        ]
                                    },
                                    "1": {
                                        "player": [
                                            {"player_key": "461.p.40001"},
                                            {"name": {"full": "Jonah Coleman"}},
                                            {"editorial_team_abbr": "ARI"},
                                            {"display_position": "RB"},
                                            {
                                                "eligible_positions": [
                                                    {"position": "RB"}
                                                ]
                                            },
                                            {
                                                "selected_position": [
                                                    {"position": "BN"}
                                                ]
                                            },
                                        ]
                                    },
                                    "2": {
                                        "player": [
                                            {"player_key": "461.p.31264"},
                                            {"name": {"full": "Marcus Jones"}},
                                            {"editorial_team_abbr": "NE"},
                                            {"display_position": "CB"},
                                            {
                                                "eligible_positions": [
                                                    {"position": "CB"},
                                                    {"position": "DB"},
                                                ]
                                            },
                                            {
                                                "selected_position": [
                                                    {"position": "BN"}
                                                ]
                                            },
                                        ]
                                    },
                                }
                            }
                        },
                    }
                ]
            },
            "available_players": {},
            "teams": {},
            "transactions": {},
        },
        "fantasypros": {
            "weekly": {
                "data": {
                    "players": [
                        {
                            "fpid": 23136,
                            "name": "De Von Achane",
                            "team_id": "MIA",
                            "position_id": "RB",
                            "stats": {"points_half": 18.17, "fpid": ""},
                        },
                        {
                            "fpid": 26440,
                            "name": "Jonah T Coleman",
                            "team_id": "ARI",
                            "position_id": "RB",
                            "stats": {"rush_yd": 38.2},
                        },
                        {
                            "fpid": 23890,
                            "name": "Marcus Jones",
                            "team_id": "NE",
                            "position_id": "CB",
                            "stats": {"def_tackle": 3.4, "player_id": ""},
                        },
                    ]
                },
                "fetched_at": "2026-10-11T04:23:35+00:00",
            },
            "ros": {
                "data": {
                    "players": [
                        {
                            "player_id": 23136,
                            "player_team_id": "MIA",
                            "player_position_id": "RB",
                            "rank_ecr": 12,
                        },
                        {
                            "player_id": 26440,
                            "player_team_id": "ARI",
                            "player_position_id": "RB",
                            "rank_ecr": 88,
                        },
                        {
                            "player_id": 23890,
                            "player_team_id": "NE",
                            "player_position_id": "CB",
                            "rank_ecr": 142,
                        },
                    ]
                },
                "fetched_at": "2026-10-11T04:23:35+00:00",
            },
            "playoffs": {},
        },
    }

    state = normalize_snapshot(
        snapshot,
        league_key="461.l.196780",
        team_key="461.p.196780.t.1",
    )

    assert state["projection_errors"] == []


def test_normalize_matches_live_projections_to_id_only_ros_rows() -> None:
    snapshot = {
        "source_updated_at": "2026-10-11T04:23:35+00:00",
        "week": 1,
        "yahoo": FIXTURE["yahoo"],
        "fantasypros": {
            "weekly": {
                "data": {
                    "players": [
                        {
                            "fpid": 23136,
                            "name": "De Von Achane",
                            "team_id": "MIA",
                            "position_id": "RB",
                            "stats": {"points_half": 18.17, "fpid": ""},
                        },
                        {
                            "fpid": 8090,
                            "name": "Green Bay Packers",
                            "team_id": "GB",
                            "position_id": "DST",
                            "stats": {"points": 7.64},
                        },
                        {
                            "fpid": 23890,
                            "name": "Marcus Jones",
                            "team_id": "NE",
                            "position_id": "CB",
                            "stats": {"def_tackle": 3.4, "player_id": ""},
                        },
                    ]
                },
                "fetched_at": "2026-10-11T04:23:35+00:00",
            },
            "ros": {
                "data": {
                    "players": [
                        {
                            "player_id": 23136,
                            "player_team_id": "MIA",
                            "player_position_id": "RB",
                            "rank_ecr": 12,
                        },
                        {
                            "player_id": 8090,
                            "player_team_id": "GB",
                            "player_position_id": "DST",
                            "rank_ecr": 9,
                        },
                        {
                            "player_id": 23890,
                            "player_team_id": "NE",
                            "player_position_id": "CB",
                            "rank_ecr": 142,
                        },
                    ]
                },
                "fetched_at": "2026-10-11T04:23:35+00:00",
            },
            "playoffs": {},
        },
    }

    state = normalize_snapshot(
        snapshot,
        league_key="461.l.196780",
        team_key="461.p.196780.t.1",
    )

    assert state["projection_errors"] == []


def test_lookup_provider_entry_by_id_tries_all_provider_ids() -> None:
    ros_by_id: dict[str, dict] = {}
    index_provider_item_by_id(
        ros_by_id,
        {
            "player_id": 23890,
            "player_team_id": "NE",
            "player_position_id": "CB",
            "rank_ecr": 142,
        },
    )
    weekly = {"fpid": 23890, "player_id": 23891, "name": "Marcus Jones"}

    match = lookup_provider_entry_by_id(ros_by_id, weekly)

    assert match["rank_ecr"] == 142


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
