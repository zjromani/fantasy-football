from __future__ import annotations

import json
from pathlib import Path

from app.league import LeagueConfig
from app.normalize import extract_yahoo_settings

ROOT = Path(__file__).parents[1]
FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "yahoo_league_settings.json").read_text()
)
LEAGUE = LeagueConfig.load(ROOT / "config" / "league.yml")


def test_extract_yahoo_settings_matches_league_config() -> None:
    extracted = extract_yahoo_settings(FIXTURE)

    assert extracted["roster"]["QB"] == 1
    assert extracted["roster"]["D"] == 1
    assert extracted["scoring"]["completion"] == 0.2
    assert extracted["scoring"]["return_yd"] == 0.04
    assert extracted["scoring"]["fumble_lost"] == -2
    assert extracted["scoring"]["pass_yd_bonus_200"] == 1
    assert extracted["scoring"]["dst_pa_0"] == 15
    assert extracted["scoring"]["solo_tackle"] == 0.5
    assert extracted["scoring"]["idp_sack"] == 2

    drift = LEAGUE.validate_yahoo_settings(extracted)
    assert drift == []


def test_extract_yahoo_settings_uses_stat_categories_not_fallback_ids() -> None:
    payload = {
        "stat_modifiers": {
            "stats": [{"stat": {"stat_id": "18", "value": "-2"}}]
        }
    }

    without_categories = extract_yahoo_settings(payload)
    assert without_categories["scoring"]["fumble_lost"] == -2

    with_categories = extract_yahoo_settings(
        {
            **payload,
            "stat_categories": [
                {
                    "stat_id": 18,
                    "name": "Fumbles Lost",
                    "display_name": "Fum Lost",
                    "position_type": "O",
                }
            ],
        }
    )
    assert with_categories["scoring"]["fumble_lost"] == -2
    assert "return_yd" not in with_categories["scoring"]


def test_extract_yahoo_settings_handles_list_shaped_stat_entries() -> None:
    payload = {
        "stat_categories": [
            {
                "stat": [
                    {"stat_id": "2"},
                    {"name": "Completions"},
                    {"display_name": "Comp"},
                    {"position_type": "O"},
                ]
            }
        ],
        "stat_modifiers": {
            "stats": [
                {
                    "stat": [
                        {"stat_id": "2"},
                        {"value": "0.2"},
                    ]
                }
            ]
        },
    }

    extracted = extract_yahoo_settings(payload)

    assert extracted["scoring"]["completion"] == 0.2
