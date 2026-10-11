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
        or item.get("player_position_id")
        or item.get("position_id")
        or ""
    ).upper()


def normalize_fantasypros_item(item: dict[str, Any]) -> dict[str, Any]:
    merged = dict(item)
    nested = item.get("player")
    if isinstance(nested, dict):
        top_level = {key: value for key, value in item.items() if key != "player"}
        merged = {**nested, **top_level}
    if merged.get("player_team_id") and not merged.get("team"):
        merged["team"] = merged["player_team_id"]
    if merged.get("team_id") and not merged.get("team"):
        merged["team"] = merged["team_id"]
    if merged.get("player_position_id") and not merged.get("position"):
        merged["position"] = merged["player_position_id"]
    if merged.get("position_id") and not merged.get("position"):
        merged["position"] = merged["position_id"]
    return merged


def is_provider_player_record(item: dict[str, Any]) -> bool:
    merged = normalize_fantasypros_item(item)
    name = merged.get("player_name") or merged.get("name")
    if not isinstance(name, str) or not name.strip():
        return False
    if any(merged.get(key) not in {None, ""} for key in ("fpid", "player_id", "id")):
        return True
    if any(
        merged.get(key) not in {None, ""}
        for key in ("rank_ecr", "rank", "consensus_rank")
    ):
        return True
    stats = merged.get("stats")
    return isinstance(stats, dict) and bool(stats)


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
    if not is_provider_player_record(item):
        return
    merged = normalize_fantasypros_item(item)
    name = merged.get("player_name") or merged.get("name")
    if not isinstance(name, str):
        return
    stats = merged.get("stats", {})
    stats_overlay = (
        {
            key: value
            for key, value in stats.items()
            if key
            not in {
                "fpid",
                "player_id",
                "id",
                "player_name",
                "name",
                "team",
                "player_team_id",
                "team_id",
                "position",
                "player_position_id",
                "position_id",
            }
        }
        if isinstance(stats, dict)
        else {}
    )
    entry = {
        **merged,
        **stats_overlay,
        "_has_stats": isinstance(stats, dict) and bool(stats),
    }
    for key in lookup_keys_for_provider_item(merged):
        result[key] = entry


def provider_player_id(item: dict[str, Any]) -> str:
    merged = normalize_fantasypros_item(item)
    for key in ("fpid", "player_id", "id"):
        value = merged.get(key)
        if value not in {None, ""}:
            return str(value)
    return ""


def index_provider_item_by_id(
    result: dict[str, dict[str, Any]], item: dict[str, Any]
) -> None:
    player_id = provider_player_id(item)
    if not player_id:
        return
    merged = normalize_fantasypros_item(item)
    if not (
        is_provider_player_record(item)
        or any(
            merged.get(key) not in {None, ""}
            for key in ("rank_ecr", "rank", "consensus_rank")
        )
    ):
        return
    merged = normalize_fantasypros_item(item)
    stats = merged.get("stats", {})
    stats_overlay = (
        {
            key: value
            for key, value in stats.items()
            if key
            not in {
                "fpid",
                "player_id",
                "id",
                "player_name",
                "name",
                "team",
                "player_team_id",
                "team_id",
                "position",
                "player_position_id",
                "position_id",
            }
        }
        if isinstance(stats, dict)
        else {}
    )
    result[player_id] = {
        **merged,
        **stats_overlay,
        "_has_stats": isinstance(stats, dict) and bool(stats),
    }


def lookup_provider_entry(
    index: dict[tuple[str, str], dict[str, Any]], player: dict[str, Any]
) -> dict[str, Any]:
    for key in lookup_keys_for_yahoo_player(player):
        match = index.get(key)
        if match:
            return match
    return {}


def lookup_provider_entry_by_id(
    index: dict[str, dict[str, Any]], provider_data: dict[str, Any]
) -> dict[str, Any]:
    player_id = provider_player_id(provider_data)
    if player_id:
        match = index.get(player_id)
        if match:
            return match
    return {}


def provider_as_yahoo_player(provider_data: dict[str, Any]) -> dict[str, Any]:
    merged = normalize_fantasypros_item(provider_data)
    return {
        "name": str(merged.get("player_name") or merged.get("name") or ""),
        "nfl_team": str(
            merged.get("team")
            or merged.get("player_team_id")
            or merged.get("team_id")
            or ""
        ),
        "position": str(
            merged.get("position")
            or merged.get("player_position_id")
            or merged.get("position_id")
            or ""
        ),
    }


def lookup_ros_by_compact_name_team(
    ros_by_id: dict[str, dict[str, Any]], player: dict[str, Any]
) -> dict[str, Any]:
    if not ros_by_id:
        return {}
    if "player_name" in player or "fpid" in player or "player_id" in player:
        proxy = provider_as_yahoo_player(player)
    else:
        proxy = player
    name = str(proxy.get("name") or "")
    team = normalize_team(str(proxy.get("nfl_team") or ""))
    if not name or not team:
        return {}
    target = compact_name(name)
    for entry in ros_by_id.values():
        entry_name = str(entry.get("player_name") or entry.get("name") or "")
        entry_team = normalize_team(
            str(entry.get("team") or entry.get("player_team_id") or "")
        )
        if entry_team == team and compact_name(entry_name) == target:
            return entry
    return {}


def lookup_ros_entry(
    ros_index: dict[tuple[str, str], dict[str, Any]],
    ros_by_id: dict[str, dict[str, Any]],
    yahoo_player: dict[str, Any],
    weekly_data: dict[str, Any],
) -> dict[str, Any]:
    ros_data = lookup_provider_entry(ros_index, yahoo_player)
    if ros_data:
        return ros_data
    if weekly_data:
        ros_data = lookup_provider_entry_by_id(ros_by_id, weekly_data)
        if ros_data:
            return ros_data
        ros_data = lookup_provider_entry(
            ros_index, provider_as_yahoo_player(weekly_data)
        )
        if ros_data:
            return ros_data
    return lookup_ros_by_compact_name_team(ros_by_id, weekly_data or yahoo_player)


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
