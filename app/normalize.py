from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from .identity import normalize_name
from .value import score_projected_stats

YAHOO_STAT_IDS = {
    "4": "pass_yd",
    "5": "pass_td",
    "6": "pass_int",
    "9": "rush_yd",
    "10": "rush_td",
    "11": "reception",
    "12": "rec_yd",
    "13": "rec_td",
    "18": "return_yd",
    "31": "fumble_lost",
}

YAHOO_STAT_NAMES = {
    "completions": "completion",
    "incomplete passes": "incomplete",
    "passing yards": "pass_yd",
    "passing touchdowns": "pass_td",
    "interceptions": "pass_int",
    "rushing yards": "rush_yd",
    "rushing touchdowns": "rush_td",
    "receptions": "reception",
    "receiving yards": "rec_yd",
    "receiving touchdowns": "rec_td",
    "return yards": "return_yd",
    "return touchdowns": "return_td",
    "2-point conversions": "two_point",
    "fumbles lost": "fumble_lost",
    "offensive fumble return td": "offensive_fumble_return_td",
    "tackle solo": "solo_tackle",
    "tackle assist": "assist_tackle",
    "fumble force": "forced_fumble",
    "pass defended": "pass_defended",
    "tackles for loss": "tackle_for_loss",
    "turnover return yards": "turnover_return_yd",
}


def normalize_snapshot(
    snapshot: dict[str, Any],
    *,
    league_key: str,
    team_key: str,
    scoring: dict[str, float] | None = None,
    roster_slots: dict[str, int] | None = None,
) -> dict[str, Any]:
    roster_players = _yahoo_players(snapshot["yahoo"]["roster"])
    available_players = _yahoo_players(snapshot["yahoo"]["available_players"])
    team_rosters = _yahoo_team_rosters(snapshot["yahoo"].get("teams", {}))
    weekly_source = snapshot["fantasypros"]["weekly"]
    ros_source = snapshot["fantasypros"]["ros"]
    weekly = _provider_players(weekly_source.get("data", weekly_source))
    ros = _provider_players(ros_source.get("data", ros_source))
    playoff_sources = snapshot["fantasypros"].get("playoffs", {})
    playoff_projections = [
        _provider_players(source.get("data", source))
        for source in playoff_sources.values()
    ]
    source_updated_at = min(
        [
            snapshot["source_updated_at"],
            weekly_source.get("fetched_at", snapshot["source_updated_at"]),
            ros_source.get("fetched_at", snapshot["source_updated_at"]),
            *[
                source.get("fetched_at", snapshot["source_updated_at"])
                for source in playoff_sources.values()
            ],
        ]
    )

    projections = []
    projection_errors = []
    roster_keys = {player["player_key"] for player in roster_players}
    all_players_by_key = {
        player["player_key"]: player
        for player in (
            roster_players
            + available_players
            + [player for players in team_rosters.values() for player in players]
        )
    }
    all_players = list(all_players_by_key.values())
    for player in all_players:
        identity = (
            normalize_name(player["name"]),
            player.get("nfl_team", "").upper(),
        )
        weekly_data = weekly.get(identity, {})
        ros_data = ros.get(identity, {})
        playoff_data = [week.get(identity, {}) for week in playoff_projections]
        if player["player_key"] in roster_keys:
            if not weekly_data or not weekly_data.get("_has_stats"):
                projection_errors.append(
                    f"missing weekly projection for {player['name']}"
                )
            if not ros_data:
                projection_errors.append(f"missing ROS ranking for {player['name']}")
        week_points = (
            score_projected_stats(
                _projected_stats(weekly_data, player["position"]), scoring
            )
            if scoring
            else _number(
                weekly_data,
                "fpts",
                "fantasy_points",
                "points",
                "projected_points",
            )
        )
        rank = _number(ros_data, "rank", "rank_ecr", "consensus_rank", default=500)
        ros_points = _number(
            ros_data,
            "fpts",
            "fantasy_points",
            "points",
            default=max(0, 500 - rank),
        )
        playoff_points = (
            sum(
                score_projected_stats(
                    _projected_stats(data, player["position"]), scoring or {}
                )
                for data in playoff_data
            )
            if playoff_data and all(data.get("_has_stats") for data in playoff_data)
            else 0
        )
        projections.append(
            {
                "player_key": player["player_key"],
                "fantasypros_id": str(
                    weekly_data.get("fpid")
                    or ros_data.get("fpid")
                    or ros_data.get("player_id")
                    or ""
                ),
                "name": player["name"],
                "position": player["position"],
                "nfl_team": player.get("nfl_team", ""),
                "week_points": week_points,
                "ros_points": ros_points,
                "playoff_points": playoff_points,
                "volatility": (
                    5
                    if player.get("injury_status", "") in {"Q", "D", "OUT", "IR", "PUP"}
                    else 0
                ),
                "injury_status": player.get("injury_status", ""),
                "is_active": player.get("injury_status", "") not in {"IR", "PUP"},
                "bye_week": (
                    player.get("bye_week")
                    if player.get("bye_week") == snapshot["week"]
                    else None
                ),
                "waiver_deadline": player.get("waiver_deadline"),
                "source_updated_at": source_updated_at,
            }
        )

    trade_player_keys = {
        player["player_key"] for players in team_rosters.values() for player in players
    }
    projection_by_key = {
        projection["player_key"]: projection for projection in projections
    }
    trade_analysis_ready = bool(playoff_projections) and all(
        projection_by_key.get(player_key, {}).get("playoff_points", 0) > 0
        for player_key in trade_player_keys
    )
    return {
        "source_updated_at": source_updated_at,
        "week": snapshot["week"],
        "league_key": league_key,
        "team_key": team_key,
        "fab_remaining": _find_first_number(
            snapshot["yahoo"].get("team", {}), "faab_balance", default=-1
        ),
        "weekly_fab_claims": _weekly_fab_claims(
            snapshot["yahoo"]["transactions"], team_key
        ),
        "waiver_deadlines": {
            player["player_key"]: player["waiver_deadline"]
            for player in available_players
            if player.get("waiver_deadline")
        },
        "roster": [
            {
                "player_key": player["player_key"],
                "eligible_positions": player["eligible_positions"],
                "selected_position": player["selected_position"],
                "locked": player.get("locked", False),
            }
            for player in roster_players
        ],
        "projections": projections,
        "projection_errors": projection_errors,
        "free_agent_keys": [
            player["player_key"]
            for player in available_players
            if player["player_key"] not in roster_keys
        ],
        "ros_ranks": {
            player["player_key"]: int(
                _number(
                    ros.get(
                        (
                            normalize_name(player["name"]),
                            player.get("nfl_team", "").upper(),
                        ),
                        {},
                    ),
                    "rank",
                    "rank_ecr",
                    "consensus_rank",
                    default=500,
                )
            )
            for player in all_players
        },
        "protected_player_keys": [],
        "starter_vacancies": [],
        "roster_need": _roster_need(
            roster_players, projection_by_key, roster_slots or {}
        ),
        "trade_analysis_ready": trade_analysis_ready,
        "incoming_trades": _incoming_trades(
            snapshot["yahoo"]["transactions"], team_key
        ),
        "opponents": {
            opponent_team_key: [player["player_key"] for player in opponent_players]
            for opponent_team_key, opponent_players in team_rosters.items()
            if opponent_team_key != team_key
        },
    }


def extract_yahoo_settings(payload: Any) -> dict[str, dict[str, float | int]]:
    roster: dict[str, int] = {}
    scoring: dict[str, float] = {}
    names_by_id = {}
    values_by_id = {}
    bonuses_by_id: dict[str, list[tuple[int, float]]] = {}
    for item in _walk(payload):
        roster_position = item.get("roster_position")
        if isinstance(roster_position, dict):
            position = roster_position.get("position")
            count = roster_position.get("count")
            if position and count is not None:
                roster[str(position)] = int(count)
        stat = item.get("stat")
        if isinstance(stat, dict) and "stat_id" in stat:
            stat_id = str(stat["stat_id"])
            stat_name = stat.get("display_name") or stat.get("name")
            if stat_name:
                names_by_id[stat_id] = (
                    str(stat_name).strip().lower(),
                    str(stat.get("position_type", "")).upper(),
                )
            if "value" in stat:
                values_by_id[stat_id] = float(stat["value"])
            bonus_payload = stat.get("bonuses") or item.get("bonuses")
            if bonus_payload:
                for bonus in _walk(bonus_payload):
                    target = bonus.get("target") or bonus.get("threshold")
                    points = bonus.get("points") or bonus.get("value")
                    if target is not None and points is not None:
                        bonuses_by_id.setdefault(stat_id, []).append(
                            (int(float(target)), float(points))
                        )
    for stat_id, value in values_by_id.items():
        scoring_name = _yahoo_scoring_name(
            *names_by_id.get(stat_id, ("", ""))
        ) or YAHOO_STAT_IDS.get(stat_id)
        if scoring_name:
            scoring[scoring_name] = value
            for threshold, points in bonuses_by_id.get(stat_id, []):
                scoring[f"{scoring_name}_bonus_{threshold}"] = points
    return {"roster": roster, "scoring": scoring}


def _yahoo_scoring_name(name: str, position_type: str) -> str | None:
    if position_type == "K":
        return {
            "field goals 0-19 yards": "fg_0_19",
            "field goals 20-29 yards": "fg_20_29",
            "field goals 30-39 yards": "fg_30_39",
            "field goals 40-49 yards": "fg_40_49",
            "field goals 50+ yards": "fg_50_plus",
            "field goals missed 0-19 yards": "fg_miss_0_19",
            "field goals missed 20-29 yards": "fg_miss_20_29",
            "field goals missed 30-39 yards": "fg_miss_30_39",
            "field goals missed 40-49 yards": "fg_miss_40_49",
            "field goals missed 50+ yards": "fg_miss_50_plus",
            "point after attempt made": "xp_made",
            "point after attempt missed": "xp_missed",
        }.get(name)
    if position_type in {"DT", "DEF"}:
        return {
            "sack": "dst_sack",
            "interception": "dst_interception",
            "fumble recovery": "dst_fumble_recovery",
            "touchdown": "dst_td",
            "safety": "dst_safety",
            "block kick": "dst_block_kick",
            "kickoff and punt return touchdowns": "dst_return_td",
            "4th down stops": "dst_fourth_down_stop",
            "extra point returned": "dst_extra_point_returned",
            "points allowed 0 points": "dst_pa_0",
            "points allowed 1-6 points": "dst_pa_1_6",
            "points allowed 7-13 points": "dst_pa_7_13",
            "points allowed 14-20 points": "dst_pa_14_20",
            "points allowed 21-27 points": "dst_pa_21_27",
            "points allowed 28-34 points": "dst_pa_28_34",
            "points allowed 35+ points": "dst_pa_35_plus",
        }.get(name)
    if position_type in {"DP", "IDP"}:
        return {
            "sack": "idp_sack",
            "interception": "idp_interception",
            "fumble recovery": "idp_fumble_recovery",
            "defensive touchdown": "idp_td",
            "safety": "idp_safety",
            "block kick": "idp_block_kick",
            "extra point returned": "idp_extra_point_returned",
        }.get(name) or YAHOO_STAT_NAMES.get(name)
    return YAHOO_STAT_NAMES.get(name)


def _yahoo_players(payload: Any) -> list[dict[str, Any]]:
    result = {}
    for item in _walk(payload):
        player_payload = item.get("player")
        if not isinstance(player_payload, list):
            continue
        flattened = _collapse(player_payload)
        player_key = flattened.get("player_key")
        if not player_key:
            continue
        name = flattened.get("name", {})
        if isinstance(name, dict):
            name = name.get("full", player_key)
        eligible = flattened.get("eligible_positions", [])
        if isinstance(eligible, dict):
            eligible = [eligible]
        eligible_positions = []
        for position in eligible:
            if isinstance(position, dict):
                eligible_positions.append(str(position.get("position", "")))
            elif position:
                eligible_positions.append(str(position))
        selected = flattened.get("selected_position", {})
        if isinstance(selected, list):
            selected = _collapse(selected)
        if isinstance(selected, dict):
            selected = selected.get("position", "BN")
        display_position = str(
            flattened.get("display_position")
            or flattened.get("primary_position")
            or (eligible_positions[0] if eligible_positions else "BN")
        ).split(",")[0]
        bye_weeks = flattened.get("bye_weeks", {})
        if isinstance(bye_weeks, list):
            bye_weeks = _collapse(bye_weeks)
        bye_week = (
            int(bye_weeks["week"])
            if isinstance(bye_weeks, dict) and bye_weeks.get("week")
            else None
        )
        waiver_deadline = _normalize_deadline(
            flattened.get("waiver_date") or flattened.get("waiver_deadline")
        )
        result[str(player_key)] = {
            "player_key": str(player_key),
            "name": str(name),
            "position": display_position,
            "nfl_team": str(flattened.get("editorial_team_abbr", "")),
            "eligible_positions": eligible_positions or [display_position],
            "selected_position": str(selected or "BN"),
            "injury_status": str(flattened.get("status", "")),
            "bye_week": bye_week,
            "waiver_deadline": waiver_deadline,
            "locked": bool(flattened.get("is_editable") == 0),
        }
    return list(result.values())


def _provider_players(payload: Any) -> dict[tuple[str, str], dict[str, Any]]:
    result = {}
    for item in _walk(payload):
        name = item.get("player_name") or item.get("name")
        if not isinstance(name, str):
            continue
        team = str(
            item.get("team") or item.get("team_id") or item.get("player_team_id") or ""
        ).upper()
        stats = item.get("stats", {})
        result[(normalize_name(name), team)] = {
            **item,
            **(stats if isinstance(stats, dict) else {}),
            "_has_stats": isinstance(stats, dict) and bool(stats),
        }
    return result


def _yahoo_team_rosters(payload: Any) -> dict[str, list[dict[str, Any]]]:
    result = {}
    for item in _walk(payload):
        team_payload = item.get("team")
        if not isinstance(team_payload, list):
            continue
        flattened = _collapse(team_payload)
        team_key = flattened.get("team_key")
        players = _yahoo_players(item)
        if team_key and players:
            result[str(team_key)] = players
    return result


def _incoming_trades(payload: Any, team_key: str) -> list[dict[str, Any]]:
    trades = []
    for item in _walk(payload):
        transaction_payload = item.get("transaction")
        if not isinstance(transaction_payload, list):
            continue
        flattened = _collapse(transaction_payload)
        transaction_type = str(flattened.get("type", ""))
        if (
            "trade" not in transaction_type
            or str(flattened.get("tradee_team_key", "")) != team_key
        ):
            continue
        send_player_keys = []
        receive_player_keys = []
        for player_item in _walk(transaction_payload):
            player_payload = player_item.get("player")
            if not isinstance(player_payload, list):
                continue
            player = _collapse(player_payload)
            player_key = player.get("player_key")
            transaction = player.get("transaction_data", {})
            if isinstance(transaction, list):
                transaction = _collapse(transaction)
            if not player_key or not isinstance(transaction, dict):
                continue
            if transaction.get("source_team_key") == team_key:
                send_player_keys.append(str(player_key))
            if transaction.get("destination_team_key") == team_key:
                receive_player_keys.append(str(player_key))
        if send_player_keys or receive_player_keys:
            trades.append(
                {
                    "transaction_key": str(flattened["transaction_key"]),
                    "send_player_keys": list(dict.fromkeys(send_player_keys)),
                    "receive_player_keys": list(dict.fromkeys(receive_player_keys)),
                    "deadline": _normalize_deadline(
                        flattened.get("trade_reject_time")
                        or flattened.get("trade_review_end_time")
                        or flattened.get("deadline")
                    ),
                }
            )
    return trades


def _weekly_fab_claims(payload: Any, team_key: str) -> int:
    transaction_keys = set()
    for item in _walk(payload):
        transaction_payload = item.get("transaction")
        if not isinstance(transaction_payload, list):
            continue
        flattened = _collapse(transaction_payload)
        transaction_time = _transaction_datetime(flattened)
        if (
            flattened.get("transaction_key")
            and "waiver" in str(flattened).lower()
            and str(flattened.get("status", "")).lower() in {"pending", "successful"}
            and team_key in str(flattened)
            and (
                str(flattened.get("status", "")).lower() == "pending"
                or (
                    transaction_time is not None
                    and transaction_time.isocalendar()[:2]
                    == datetime.now(UTC).isocalendar()[:2]
                )
            )
        ):
            transaction_keys.add(str(flattened["transaction_key"]))
    return len(transaction_keys)


def _roster_need(
    roster: list[dict[str, Any]],
    projections: dict[str, dict[str, Any]],
    roster_slots: dict[str, int],
) -> dict[str, float]:
    needs = {}
    defensive_positions = {"D", "IDP", "DL", "LB", "DB", "CB", "S", "DE", "DT"}
    for position, required in roster_slots.items():
        if position in {"BN", "IR", "W/R/T"}:
            continue
        eligible_count = sum(
            position in player["eligible_positions"]
            or (
                position == "D"
                and bool(defensive_positions & set(player["eligible_positions"]))
            )
            for player in roster
        )
        values = [
            projections.get(player["player_key"], {}).get("ros_points", 0)
            for player in roster
            if player["position"] == position
            or (position == "D" and player["position"] in defensive_positions)
        ]
        quality_penalty = 1 / max(sum(values) / len(values), 1) if values else 1
        needs[position] = max(0, required - eligible_count) + quality_penalty
    return needs


def _transaction_datetime(payload: dict[str, Any]) -> datetime | None:
    value = (
        payload.get("timestamp")
        or payload.get("transaction_time")
        or payload.get("process_time")
    )
    normalized = _normalize_deadline(value)
    return datetime.fromisoformat(normalized) if normalized else None


def _walk(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _collapse(value: Any) -> dict[str, Any]:
    result = {}
    if isinstance(value, dict):
        result.update(value)
    elif isinstance(value, list):
        for child in value:
            result.update(_collapse(child))
    return result


def _number(payload: dict[str, Any], *keys: str, default: float = 0) -> float:
    for key in keys:
        value = payload.get(key)
        if value not in {None, ""}:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    return float(default)


def _find_first_number(payload: Any, key: str, default: float) -> float:
    for item in _walk(payload):
        if key in item:
            return _number(item, key, default=default)
    return default


def _normalize_deadline(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    try:
        if str(value).isdigit():
            return datetime.fromtimestamp(int(value), UTC).isoformat()
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def _projected_stats(payload: dict[str, Any], position: str) -> dict[str, float]:
    aliases = {
        "completion": ("completion", "completions", "pass_cmp"),
        "pass_yd": ("pass_yd", "pass_yds"),
        "pass_td": ("pass_td", "pass_tds"),
        "pass_int": ("pass_int", "pass_ints"),
        "rush_yd": ("rush_yd", "rush_yds"),
        "rush_td": ("rush_td", "rush_tds"),
        "reception": ("reception", "rec", "rec_rec"),
        "rec_yd": ("rec_yd", "rec_yds"),
        "rec_td": ("rec_td", "rec_tds"),
        "return_yd": ("return_yd", "return_yds", "ret_yds"),
        "return_td": ("return_td", "return_tds", "ret_tds"),
        "two_point": ("two_point", "two_pt", "2pt_tds"),
        "fumble_lost": ("fumble_lost", "fumbles_lost"),
        "turnover_return_yd": ("turnover_return_yd", "turnover_return_yds"),
        "fg_0_19": ("fg_0_19", "fg"),
        "fg_20_29": ("fg_20_29",),
        "fg_30_39": ("fg_30_39",),
        "fg_40_49": ("fg_40_49",),
        "fg_50_plus": ("fg_50_plus",),
        "xp_made": ("xp_made", "xpt"),
        "xp_missed": ("xp_missed",),
    }
    stats = {
        normalized: _number(payload, *provider_names)
        for normalized, provider_names in aliases.items()
    }
    stats["incomplete"] = max(0, _number(payload, "pass_att") - stats["completion"])
    if position in {"DEF", "DST"}:
        stats.update(
            {
                "dst_sack": _number(payload, "def_sack"),
                "dst_interception": _number(payload, "def_int"),
                "dst_fumble_recovery": _number(payload, "def_fr"),
                "dst_td": _number(payload, "def_td"),
                "dst_safety": _number(payload, "def_safety"),
                "dst_return_td": _number(payload, "def_retd"),
                "dst_points_allowed": _number(payload, "def_pa"),
            }
        )
    elif position in {"D", "IDP", "DL", "LB", "DB", "CB", "S", "DE", "DT"}:
        stats.update(
            {
                "solo_tackle": _number(payload, "def_tackle"),
                "assist_tackle": _number(payload, "def_assist"),
                "idp_sack": _number(payload, "def_sack"),
                "idp_interception": _number(payload, "def_int"),
                "forced_fumble": _number(payload, "def_ff"),
                "idp_fumble_recovery": _number(payload, "def_fr"),
                "idp_td": _number(payload, "def_td"),
                "idp_safety": _number(payload, "def_safety"),
                "pass_defended": _number(payload, "def_pd"),
                "tackle_for_loss": _number(payload, "def_tlost"),
            }
        )
    return stats
