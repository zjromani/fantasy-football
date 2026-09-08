from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PlayerIdentity:
    yahoo_key: str
    fantasypros_id: str
    name: str
    nfl_team: str


def normalize_name(name: str) -> str:
    value = re.sub(r"[^a-z0-9 ]", "", name.lower())
    value = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", value)
    return " ".join(value.split())


def map_players(
    yahoo_players: list[dict], fantasypros_players: list[dict]
) -> list[PlayerIdentity]:
    by_exact = {
        (normalize_name(player["name"]), player.get("team", "").upper()): player
        for player in fantasypros_players
    }
    identities = []
    for yahoo in yahoo_players:
        key = (normalize_name(yahoo["name"]), yahoo.get("team", "").upper())
        fantasypros = by_exact.get(key)
        if fantasypros:
            identities.append(
                PlayerIdentity(
                    yahoo_key=str(yahoo["player_key"]),
                    fantasypros_id=str(fantasypros["id"]),
                    name=str(yahoo["name"]),
                    nfl_team=key[1],
                )
            )
    return identities
