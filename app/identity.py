from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

TEAM_DEFENSE_POSITIONS = frozenset({"DEF", "DST", "D"})
DEFENSE_LOOKUP_NAME = ""

TEAM_ABBR_ALIASES = {
    "JAC": "JAX",
    "WSH": "WAS",
    "WFT": "WAS",
}

NFL_TEAM_NICKNAMES = {
    "cardinals": "ARI",
    "falcons": "ATL",
    "ravens": "BAL",
    "bills": "BUF",
    "panthers": "CAR",
    "bears": "CHI",
    "bengals": "CIN",
    "browns": "CLE",
    "cowboys": "DAL",
    "broncos": "DEN",
    "lions": "DET",
    "packers": "GB",
    "texans": "HOU",
    "colts": "IND",
    "jaguars": "JAX",
    "chiefs": "KC",
    "raiders": "LV",
    "chargers": "LAC",
    "rams": "LAR",
    "dolphins": "MIA",
    "vikings": "MIN",
    "patriots": "NE",
    "saints": "NO",
    "giants": "NYG",
    "jets": "NYJ",
    "eagles": "PHI",
    "steelers": "PIT",
    "49ers": "SF",
    "niners": "SF",
    "seahawks": "SEA",
    "buccaneers": "TB",
    "bucs": "TB",
    "titans": "TEN",
    "commanders": "WAS",
}


@dataclass(frozen=True)
class PlayerIdentity:
    yahoo_key: str
    fantasypros_id: str
    name: str
    nfl_team: str


def normalize_name(name: str) -> str:
    value = unicodedata.normalize("NFKD", name)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.lower()
    value = re.sub(r"[^a-z0-9 ]", "", value)
    value = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", value)
    return " ".join(value.split())


def compact_name(name: str) -> str:
    return normalize_name(name).replace(" ", "")


def normalize_team(team: str) -> str:
    value = str(team or "").upper().strip()
    return TEAM_ABBR_ALIASES.get(value, value)


def infer_team_from_name(name: str) -> str:
    normalized = normalize_name(name)
    if normalized in NFL_TEAM_NICKNAMES:
        return NFL_TEAM_NICKNAMES[normalized]
    for token in normalized.split():
        if token in NFL_TEAM_NICKNAMES:
            return NFL_TEAM_NICKNAMES[token]
    return ""


def provider_position(item: dict[str, Any]) -> str:
    return str(
        item.get("position")
        or item.get("player_position")
        or item.get("position_id")
        or ""
    ).upper()


def is_team_defense(position: str) -> bool:
    return position in TEAM_DEFENSE_POSITIONS


def lookup_keys_for_yahoo_player(player: dict[str, Any]) -> list[tuple[str, str]]:
    name = str(player.get("name", ""))
    team = normalize_team(str(player.get("nfl_team", "")))
    if not team:
        team = infer_team_from_name(name)
    position = str(player.get("position", "")).upper()
    keys: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(name_key: str, team_key: str) -> None:
        if not team_key:
            return
        key = (name_key, team_key)
        if key not in seen:
            seen.add(key)
            keys.append(key)

    add(normalize_name(name), team)
    compact = compact_name(name)
    if compact:
        add(compact, team)
    if is_team_defense(position):
        add(DEFENSE_LOOKUP_NAME, team)
    return keys


def lookup_keys_for_provider_item(item: dict[str, Any]) -> list[tuple[str, str]]:
    name = str(item.get("player_name") or item.get("name") or "")
    team = normalize_team(
        str(item.get("team") or item.get("team_id") or item.get("player_team_id") or "")
    )
    if not team:
        team = infer_team_from_name(name)
    position = provider_position(item)
    keys: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(name_key: str, team_key: str) -> None:
        if not team_key and name_key != DEFENSE_LOOKUP_NAME:
            return
        key = (name_key, team_key)
        if key not in seen:
            seen.add(key)
            keys.append(key)

    add(normalize_name(name), team)
    compact = compact_name(name)
    if compact:
        add(compact, team)
    if position == "DST" or is_team_defense(position):
        add(DEFENSE_LOOKUP_NAME, team)
    return keys


def index_provider_item(
    result: dict[tuple[str, str], dict[str, Any]], item: dict[str, Any]
) -> None:
    name = item.get("player_name") or item.get("name")
    if not isinstance(name, str):
        return
    stats = item.get("stats", {})
    entry = {
        **item,
        **(stats if isinstance(stats, dict) else {}),
        "_has_stats": isinstance(stats, dict) and bool(stats),
    }
    for key in lookup_keys_for_provider_item(item):
        result[key] = entry


def lookup_provider_entry(
    index: dict[tuple[str, str], dict[str, Any]], player: dict[str, Any]
) -> dict[str, Any]:
    for key in lookup_keys_for_yahoo_player(player):
        match = index.get(key)
        if match:
            return match
    return {}


def map_players(
    yahoo_players: list[dict], fantasypros_players: list[dict]
) -> list[PlayerIdentity]:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for item in fantasypros_players:
        if isinstance(item, dict):
            index_provider_item(index, item)
    identities = []
    for yahoo in yahoo_players:
        fantasypros = lookup_provider_entry(index, yahoo)
        if fantasypros:
            identities.append(
                PlayerIdentity(
                    yahoo_key=str(yahoo["player_key"]),
                    fantasypros_id=str(
                        fantasypros.get("id") or fantasypros.get("fpid") or ""
                    ),
                    name=str(yahoo["name"]),
                    nfl_team=normalize_team(
                        str(yahoo.get("team", yahoo.get("nfl_team", "")))
                    ),
                )
            )
    return identities
