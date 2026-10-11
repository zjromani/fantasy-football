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

PROVIDER_IDENTITY_KEYS = ("fpid", "player_id", "id")
PROVIDER_RANK_KEYS = ("rank_ecr", "rank", "consensus_rank", "pos_rank", "tier")
PROVIDER_PRESERVE_KEYS = PROVIDER_IDENTITY_KEYS + PROVIDER_RANK_KEYS

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


def name_lookup_keys(name: str) -> list[str]:
    normalized = normalize_name(name)
    keys: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        if value and value not in seen:
            seen.add(value)
            keys.append(value)

    add(normalized)
    add(normalized.replace(" ", ""))
    parts = normalized.split()
    if len(parts) >= 2:
        first_last = f"{parts[0]} {parts[-1]}"
        add(first_last)
        add(first_last.replace(" ", ""))
    return keys


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
    if not merged.get("player_name") and merged.get("name"):
        merged["player_name"] = merged["name"]
    stats = merged.get("stats")
    if isinstance(stats, dict):
        for key in PROVIDER_IDENTITY_KEYS:
            if merged.get(key) in {None, ""} and stats.get(key) not in {None, ""}:
                merged[key] = stats[key]
    return merged


def _meaningful_stats(stats: dict[str, Any]) -> bool:
    for key, value in stats.items():
        if key in PROVIDER_IDENTITY_KEYS and value in {None, ""}:
            continue
        if value not in {None, ""}:
            return True
    return False


def is_provider_player_record(item: dict[str, Any]) -> bool:
    merged = normalize_fantasypros_item(item)
    if any(merged.get(key) not in {None, ""} for key in PROVIDER_IDENTITY_KEYS):
        return True
    if any(merged.get(key) not in {None, ""} for key in PROVIDER_RANK_KEYS):
        return True
    name = merged.get("player_name") or merged.get("name")
    if isinstance(name, str) and name.strip():
        stats = merged.get("stats")
        return isinstance(stats, dict) and _meaningful_stats(stats)
    stats = merged.get("stats")
    if isinstance(stats, dict) and _meaningful_stats(stats):
        return True
    return False


def _build_provider_entry(merged: dict[str, Any]) -> dict[str, Any]:
    stats = merged.get("stats", {})
    stats_dict = stats if isinstance(stats, dict) else {}
    entry = {
        **merged,
        **stats_dict,
        "_has_stats": _meaningful_stats(stats_dict),
    }
    for key in PROVIDER_PRESERVE_KEYS:
        value = merged.get(key)
        if value not in {None, ""}:
            entry[key] = value
    return entry


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

    for name_key in name_lookup_keys(name):
        add(name_key, team)
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

    for name_key in name_lookup_keys(name):
        add(name_key, team)
    if position == "DST" or is_team_defense(position):
        add(DEFENSE_LOOKUP_NAME, team)
    return keys


def merge_normalized_provider_items(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    id_order: list[str] = []
    by_name: dict[tuple[str, str], dict[str, Any]] = {}
    name_order: list[tuple[str, str]] = []
    orphans: list[dict[str, Any]] = []

    def normalized_ids(merged: dict[str, Any]) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()
        for key in PROVIDER_IDENTITY_KEYS:
            value = merged.get(key)
            if value not in {None, ""}:
                player_id = str(value)
                if player_id not in seen:
                    seen.add(player_id)
                    ids.append(player_id)
        return ids

    def name_team_key(merged: dict[str, Any]) -> tuple[str, str] | None:
        name = merged.get("player_name") or merged.get("name")
        if not isinstance(name, str) or not name.strip():
            return None
        team = normalize_team(
            str(
                merged.get("team")
                or merged.get("team_id")
                or merged.get("player_team_id")
                or ""
            )
        )
        if not team:
            team = infer_team_from_name(name)
        if not team:
            return None
        return (compact_name(name), team)

    def absorb(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        stats_a = (
            existing.get("stats") if isinstance(existing.get("stats"), dict) else {}
        )
        stats_b = (
            incoming.get("stats") if isinstance(incoming.get("stats"), dict) else {}
        )
        combined = {**existing, **incoming}
        if stats_a or stats_b:
            combined["stats"] = {**stats_a, **stats_b}
        for key in PROVIDER_PRESERVE_KEYS:
            for source in (existing, incoming):
                value = source.get(key)
                if value not in {None, ""}:
                    combined[key] = value
                    break
        for name_key in ("player_name", "name"):
            for source in (existing, incoming):
                value = source.get(name_key)
                if isinstance(value, str) and value.strip():
                    combined[name_key] = value
                    break
        return normalize_fantasypros_item(combined)

    for item in items:
        ids = normalized_ids(item)
        if ids:
            primary = ids[0]
            if primary in by_id:
                by_id[primary] = absorb(by_id[primary], item)
            else:
                by_id[primary] = dict(item)
                id_order.append(primary)
            continue
        name_key = name_team_key(item)
        if name_key:
            if name_key in by_name:
                by_name[name_key] = absorb(by_name[name_key], item)
            else:
                by_name[name_key] = dict(item)
                name_order.append(name_key)
            continue
        orphans.append(item)

    merged: list[dict[str, Any]] = [by_id[player_id] for player_id in id_order]
    merged.extend(by_name[key] for key in name_order)
    merged.extend(orphans)
    return merged


def index_provider_entry(
    result: dict[tuple[str, str], dict[str, Any]], entry: dict[str, Any]
) -> None:
    name = entry.get("player_name") or entry.get("name")
    if not isinstance(name, str):
        return
    for key in lookup_keys_for_provider_item(entry):
        result[key] = entry


def index_provider_entry_by_id(
    result: dict[str, dict[str, Any]], entry: dict[str, Any]
) -> None:
    for player_id in provider_player_ids(entry):
        result[player_id] = entry


def index_provider_item(
    result: dict[tuple[str, str], dict[str, Any]], item: dict[str, Any]
) -> None:
    if not is_provider_player_record(item):
        return
    merged = normalize_fantasypros_item(item)
    name = merged.get("player_name") or merged.get("name")
    if not isinstance(name, str):
        return
    index_provider_entry(result, _build_provider_entry(merged))


def provider_player_ids(item: dict[str, Any]) -> list[str]:
    merged = normalize_fantasypros_item(item)
    ids: list[str] = []
    seen: set[str] = set()
    for key in PROVIDER_IDENTITY_KEYS:
        value = merged.get(key)
        if value not in {None, ""}:
            player_id = str(value)
            if player_id not in seen:
                seen.add(player_id)
                ids.append(player_id)
    return ids


def provider_player_id(item: dict[str, Any]) -> str:
    ids = provider_player_ids(item)
    return ids[0] if ids else ""


def index_provider_item_by_id(
    result: dict[str, dict[str, Any]], item: dict[str, Any]
) -> None:
    player_ids = provider_player_ids(item)
    if not player_ids:
        return
    merged = normalize_fantasypros_item(item)
    if not (
        is_provider_player_record(item)
        or any(merged.get(key) not in {None, ""} for key in PROVIDER_RANK_KEYS)
    ):
        return
    index_provider_entry_by_id(result, _build_provider_entry(merged))


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
    for player_id in provider_player_ids(provider_data):
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


def lookup_by_compact_name_only(
    entries: Any, player: dict[str, Any]
) -> dict[str, Any]:
    name = str(player.get("name") or "")
    if not name:
        return {}
    target = compact_name(name)
    matches: list[dict[str, Any]] = []
    iterable = entries.values() if isinstance(entries, dict) else entries
    for entry in iterable:
        if not isinstance(entry, dict):
            continue
        entry_name = str(entry.get("player_name") or entry.get("name") or "")
        if compact_name(entry_name) == target:
            matches.append(entry)
    if len(matches) == 1:
        return matches[0]
    return {}


def lookup_by_compact_name_team(
    entries: Any, player: dict[str, Any]
) -> dict[str, Any]:
    if not entries:
        return {}
    if "player_name" in player or "fpid" in player or "player_id" in player:
        proxy = provider_as_yahoo_player(player)
    else:
        proxy = player
    name = str(proxy.get("name") or "")
    team = normalize_team(str(proxy.get("nfl_team") or ""))
    if not name or not team:
        return {}
    targets = set(name_lookup_keys(name))
    if isinstance(entries, dict):
        iterable = entries.values()
    else:
        iterable = entries
    for entry in iterable:
        if not isinstance(entry, dict):
            continue
        entry_name = str(entry.get("player_name") or entry.get("name") or "")
        entry_team = normalize_team(
            str(entry.get("team") or entry.get("player_team_id") or "")
        )
        if entry_team != team:
            continue
        entry_keys = set(name_lookup_keys(entry_name))
        if targets & entry_keys:
            return entry
    return {}


def lookup_ros_by_compact_name_team(
    ros_by_id: dict[str, dict[str, Any]], player: dict[str, Any]
) -> dict[str, Any]:
    return lookup_by_compact_name_team(ros_by_id, player)


def _provider_ids_for_yahoo_player(
    weekly_by_id: dict[str, dict[str, Any]], yahoo_player: dict[str, Any]
) -> list[str]:
    match = lookup_by_compact_name_team(weekly_by_id, yahoo_player)
    ids: list[str] = []
    seen: set[str] = set()
    for source in (match,):
        if not source:
            continue
        for key in PROVIDER_IDENTITY_KEYS:
            value = source.get(key)
            if value not in {None, ""}:
                player_id = str(value)
                if player_id not in seen:
                    seen.add(player_id)
                    ids.append(player_id)
    return ids


def lookup_weekly_entry(
    weekly_index: dict[tuple[str, str], dict[str, Any]],
    weekly_by_id: dict[str, dict[str, Any]],
    yahoo_player: dict[str, Any],
    ros_data: dict[str, Any],
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []

    def add(candidate: dict[str, Any]) -> None:
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    add(lookup_provider_entry(weekly_index, yahoo_player))
    add(lookup_provider_entry_by_id(weekly_by_id, ros_data))
    add(lookup_by_compact_name_team(weekly_index, yahoo_player))
    add(lookup_by_compact_name_team(weekly_by_id, yahoo_player))
    for player_id in _provider_ids_for_yahoo_player(weekly_by_id, yahoo_player):
        add(weekly_by_id.get(player_id, {}))
    for candidate in list(candidates):
        add(lookup_provider_entry_by_id(weekly_by_id, candidate))

    if not candidates:
        return {}

    def weekly_score(data: dict[str, Any]) -> int:
        score = 2 if data.get("_has_stats") else 0
        for key in (
            "fpts",
            "fantasy_points",
            "points",
            "points_half",
            "points_std",
            "points_ppr",
            "projected_points",
            "pass_att",
            "pass_yd",
            "rush_yd",
            "rec_yd",
            "def_pa",
            "def_sack",
            "def_tackle",
            "def_pd",
        ):
            if data.get(key) not in {None, ""}:
                score += 1
        return score

    return max(candidates, key=weekly_score)


def lookup_ros_entry(
    ros_index: dict[tuple[str, str], dict[str, Any]],
    ros_by_id: dict[str, dict[str, Any]],
    yahoo_player: dict[str, Any],
    weekly_data: dict[str, Any],
    *,
    weekly_by_id: dict[str, dict[str, Any]] | None = None,
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
    if weekly_by_id:
        for player_id in _provider_ids_for_yahoo_player(weekly_by_id, yahoo_player):
            match = ros_by_id.get(player_id)
            if match:
                return match
    if weekly_data:
        for player_id in provider_player_ids(weekly_data):
            match = ros_by_id.get(player_id)
            if match:
                return match
    subject = weekly_data or yahoo_player
    match = lookup_ros_by_compact_name_team(ros_by_id, subject)
    if match:
        return match
    match = lookup_by_compact_name_team(ros_index, subject)
    if match:
        return match
    return lookup_by_compact_name_only(ros_by_id, yahoo_player)


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
