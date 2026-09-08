from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from .approvals import ApprovalGateway, ApprovalService
from .audit import AuditStore, canonical_json, hash_payload
from .config import Settings
from .domain import Decision, Projection, RosterPlayer
from .league import LeagueConfig
from .lineup import optimize_lineup
from .notifications import Notification, NtfyClient
from .policy import PolicyEngine
from .trades import evaluate_trade, rank_outbound_trades
from .waivers import rank_fab_moves
from .yahoo_client import YahooClient, YahooWriteUnavailable


class AutoGM:
    def __init__(
        self,
        *,
        settings: Settings,
        league: LeagueConfig,
        store: AuditStore,
        yahoo: YahooClient | None = None,
        ntfy: NtfyClient | None = None,
    ) -> None:
        self.settings = settings
        self.league = league
        self.store = store
        self.yahoo = yahoo
        self.ntfy = ntfy
        self.policy = PolicyEngine(league)

    def recommend_all(
        self, state: dict[str, Any], *, only: set[str] | None = None
    ) -> list[int]:
        self.store.save_projection_inputs(state["projections"])
        decisions = self.build_decisions(state, only=only)
        decision_ids = []
        for decision in decisions:
            decision_id = self.store.save_decision(decision)
            decision_ids.append(decision_id)
            if decision.requires_approval:
                self._request_approval(decision_id, decision)
            elif self._can_execute(decision):
                status = self.execute(decision.to_dict())
                self.store.save_execution(decision_id, status)
                if not status.startswith(("executed", "submitted")):
                    if self.ntfy:
                        self.ntfy.publish(
                            Notification(
                                title="Fantasy automatic write failed",
                                message=f"{decision.summary}: {status}",
                                priority="urgent",
                            )
                        )
                    raise RuntimeError(status)
        return decision_ids

    def build_decisions(
        self, state: dict[str, Any], *, only: set[str] | None = None
    ) -> list[Decision]:
        if state.get("settings_drift"):
            raise RuntimeError(
                "Yahoo league settings drift: " + "; ".join(state["settings_drift"])
            )
        if state.get("projection_errors"):
            raise RuntimeError(
                "Projection coverage failed: " + "; ".join(state["projection_errors"])
            )
        projections = {
            item["player_key"]: projection_from_dict(item)
            for item in state["projections"]
        }
        roster = [
            RosterPlayer(
                player_key=item["player_key"],
                eligible_positions=tuple(item["eligible_positions"]),
                selected_position=item["selected_position"],
                locked=bool(item.get("locked", False)),
            )
            for item in state["roster"]
        ]
        source_updated_at = datetime.fromisoformat(state["source_updated_at"])
        decisions = []
        selected = set(only or {"lineup", "fab", "trades"})
        if "trades" in selected and not state.get("trade_analysis_ready", False):
            selected.remove("trades")
        if "fab" in selected and int(state.get("fab_remaining", -1)) < 0:
            raise RuntimeError("Authoritative Yahoo FAB balance is unavailable")

        if "lineup" in selected:
            lineup = optimize_lineup(self.league, roster, projections)
            ir_moves = 0
            ir_capacity = self.league.roster.get("IR", 0)
            ir_occupied = sum(player.selected_position == "IR" for player in roster)
            for player in roster:
                projection = projections.get(player.player_key)
                if (
                    projection
                    and projection.injury_status.upper() in {"OUT", "IR", "PUP", "NA"}
                    and player.selected_position != "IR"
                    and not player.locked
                    and ir_occupied < ir_capacity
                ):
                    lineup.positions[player.player_key] = "IR"
                    ir_occupied += 1
                    ir_moves += 1
            changed_positions = {
                key: position
                for key, position in lineup.positions.items()
                if next(
                    player.selected_position
                    for player in roster
                    if player.player_key == key
                )
                != position
            }
            if changed_positions:
                safe_correction = all(
                    not (
                        player.selected_position not in {"BN", "IR"}
                        and changed_positions.get(player.player_key) in {"BN", "IR"}
                        and projections[player.player_key].injury_status.upper()
                        not in {"OUT", "IR", "PUP", "NA"}
                        and projections[player.player_key].bye_week is None
                    )
                    for player in roster
                    if player.player_key in changed_positions
                )
                decisions.append(
                    Decision(
                        kind="ir" if ir_moves else "lineup",
                        score=lineup.delta,
                        summary=(
                            f"Optimize lineup for +{lineup.delta:.2f} projected points"
                        ),
                        payload={
                            "team_key": state["team_key"],
                            "week": int(state["week"]),
                            "positions": changed_positions,
                            "safe_correction": safe_correction,
                        },
                        source_updated_at=source_updated_at,
                        requires_approval=False,
                        inputs=state,
                    )
                )

        roster_projections = [
            projections[item.player_key]
            for item in roster
            if item.player_key in projections
        ]
        free_agents = [
            projections[key]
            for key in state.get("free_agent_keys", [])
            if key in projections
        ]
        if "fab" in selected:
            waiver_deadlines = state.get("waiver_deadlines", {})
            free_agents = [
                player
                for player in free_agents
                if player.player_key in waiver_deadlines
            ]
            fab_moves = rank_fab_moves(
                free_agents=free_agents,
                roster=roster_projections,
                budget_remaining=int(state.get("fab_remaining", 0)),
                policy=self.policy,
                ros_ranks={
                    key: int(value) for key, value in state.get("ros_ranks", {}).items()
                },
                manually_protected=set(state.get("protected_player_keys", [])),
                starter_vacancies=set(state.get("starter_vacancies", [])),
                limit=max(
                    0,
                    self.league.fab.weekly_claim_limit
                    - int(state.get("weekly_fab_claims", 0)),
                ),
            )
            for move in fab_moves:
                decisions.append(
                    Decision(
                        kind="fab",
                        score=move.net_ros_gain,
                        summary=move.summary,
                        payload={
                            "league_key": state["league_key"],
                            "team_key": state["team_key"],
                            "week": int(state["week"]),
                            "add_player_key": move.add_player_key,
                            "drop_player_key": move.drop_player_key,
                            "bid": move.bid,
                            "deadline": waiver_deadlines[move.add_player_key],
                        },
                        source_updated_at=source_updated_at,
                        requires_approval=True,
                        inputs=state,
                    )
                )

        for trade in state.get("incoming_trades", []) if "trades" in selected else []:
            package = evaluate_trade(
                send=[projections[key] for key in trade["send_player_keys"]],
                receive=[projections[key] for key in trade["receive_player_keys"]],
                roster_need=state.get("roster_need", {}),
            )
            if package.eligible and trade.get("deadline"):
                sent_names = ", ".join(
                    projections[key].name for key in trade["send_player_keys"]
                )
                received_names = ", ".join(
                    projections[key].name for key in trade["receive_player_keys"]
                )
                decisions.append(
                    Decision(
                        kind="trade_accept",
                        score=package.score,
                        summary=(
                            f"Accept trade: send {sent_names}; receive "
                            f"{received_names}; ROS {package.ros_delta:+.1f}, "
                            f"playoffs {package.playoff_delta:+.1f}, "
                            f"structure {package.structural_delta:+.1f}, "
                            f"risk {package.risk_delta:+.1f}"
                        ),
                        payload={
                            "transaction_key": trade["transaction_key"],
                            "deadline": trade["deadline"],
                        },
                        source_updated_at=source_updated_at,
                        requires_approval=True,
                        inputs=state,
                    )
                )

        opponents = {
            team_key: [projections[key] for key in player_keys]
            for team_key, player_keys in (
                state.get("opponents", {}).items() if "trades" in selected else []
            )
        }
        for opponent_team_key, package in rank_outbound_trades(
            roster=roster_projections,
            opponents=opponents,
            roster_need=state.get("roster_need", {}),
        ):
            if not state.get("trade_deadline"):
                continue
            sent_names = ", ".join(
                projections[key].name for key in package.send_player_keys
            )
            received_names = ", ".join(
                projections[key].name for key in package.receive_player_keys
            )
            decisions.append(
                Decision(
                    kind="trade_propose",
                    score=package.score,
                    summary=(
                        f"Propose to {opponent_team_key}: send {sent_names}; "
                        f"receive {received_names}; ROS {package.ros_delta:+.1f}, "
                        f"playoffs {package.playoff_delta:+.1f}, "
                        f"structure {package.structural_delta:+.1f}, "
                        f"risk {package.risk_delta:+.1f}"
                    ),
                    payload={
                        "league_key": state["league_key"],
                        "trader_team_key": state["team_key"],
                        "tradee_team_key": opponent_team_key,
                        "week": int(state["week"]),
                        "send_player_keys": list(package.send_player_keys),
                        "receive_player_keys": list(package.receive_player_keys),
                        "deadline": state["trade_deadline"],
                    },
                    source_updated_at=source_updated_at,
                    requires_approval=True,
                    inputs=state,
                )
            )
        audited_decisions = []
        for decision in decisions:
            category_enabled = (
                self.settings.lineup_writes_enabled
                if decision.kind in {"lineup", "ir"}
                else self.settings.trade_writes_enabled
                if "trade" in decision.kind
                else self.settings.fab_writes_enabled
            )
            policy = self.policy.evaluate(
                decision.kind,
                source_updated_at=decision.source_updated_at,
                writes_enabled=self.settings.writes_enabled and category_enabled,
                dry_run=self.settings.dry_run,
                safe_correction=bool(decision.payload.get("safe_correction", False)),
            )
            audited_decisions.append(
                replace(
                    decision,
                    requires_approval=policy.requires_approval,
                    policy_reasons=policy.reasons,
                )
            )
        return audited_decisions

    def execute(self, decision: dict[str, Any], *, approved: bool = False) -> str:
        kind = decision["kind"]
        source_updated_at = datetime.fromisoformat(decision["source_updated_at"])
        safe_correction = kind in {"lineup", "ir"} and decision["payload"].get(
            "safe_correction", False
        )
        category_enabled = (
            self.settings.lineup_writes_enabled
            if kind in {"lineup", "ir"}
            else self.settings.trade_writes_enabled
            if "trade" in kind
            else self.settings.fab_writes_enabled
        )
        policy = self.policy.evaluate(
            kind,
            source_updated_at=source_updated_at,
            writes_enabled=self.settings.writes_enabled and category_enabled,
            dry_run=self.settings.dry_run,
            safe_correction=safe_correction,
        )
        if policy.requires_approval and not approved:
            return "blocked: approval required"
        if not policy.allowed:
            return f"blocked: {', '.join(policy.reasons)}"
        if (
            kind == "fab"
            and self.store.executions_this_week("fab")
            >= self.league.fab.weekly_claim_limit
        ):
            return "blocked: weekly FAB claim limit reached"
        if not self.yahoo:
            raise RuntimeError("Yahoo client is required for execution")
        payload = decision["payload"]
        capability_action = (
            "lineup"
            if kind in {"lineup", "ir"}
            else "trade"
            if "trade" in kind
            else kind
        )
        if self.store.capability(capability_action) is False:
            return self._manual_fallback(kind, payload)
        payload_digest = hash_payload(payload)
        if not self.store.claim_execution(payload_digest):
            return "blocked: payload is already executing or executed"
        transaction_key = None
        try:
            self._revalidate(kind, payload)
            if kind in {"lineup", "ir"}:
                self.yahoo.set_roster(
                    payload["team_key"], payload["week"], payload["positions"]
                )
            elif kind == "fab":
                transaction_key = self.yahoo.submit_fab_claim(
                    payload["league_key"],
                    payload["team_key"],
                    add_player_key=payload["add_player_key"],
                    drop_player_key=payload.get("drop_player_key"),
                    bid=payload["bid"],
                )
            elif kind == "trade_accept":
                transaction_key = self.yahoo.act_on_trade(
                    payload["transaction_key"], "accept"
                )
            elif kind == "trade_propose":
                transaction_key = self.yahoo.propose_trade(
                    payload["league_key"],
                    payload["trader_team_key"],
                    payload["tradee_team_key"],
                    send_player_keys=payload["send_player_keys"],
                    receive_player_keys=payload["receive_player_keys"],
                )
        except YahooWriteUnavailable as exc:
            self.store.finish_execution(payload_digest, "failed")
            self.store.save_capability(capability_action, False, 403, str(exc))
            return self._manual_fallback(kind, payload)
        except Exception:
            self.store.finish_execution(payload_digest, "failed")
            raise
        self.store.save_capability(capability_action, True, 200, "Yahoo write accepted")
        if transaction_key:
            terminal_statuses = {
                "successful",
                "accepted",
                "rejected",
                "vetoed",
                "failed",
            }
            status = self.yahoo.transaction_status(transaction_key) or "pending"
            self.store.watch_transaction(transaction_key, payload_digest, status)
            if status not in terminal_statuses:
                self.store.finish_execution(payload_digest, "submitted")
                return f"submitted: transaction {transaction_key} {status}"
            if status not in {"successful", "accepted"}:
                self.store.finish_execution(payload_digest, "failed")
                raise RuntimeError(
                    f"Yahoo transaction {transaction_key} ended as {status}"
                )
            self.store.finish_execution(payload_digest, "executed")
            return f"executed: transaction {transaction_key} {status}"
        if kind in {"fab", "trade_accept", "trade_propose"}:
            self.store.finish_execution(payload_digest, "failed")
            raise RuntimeError("Yahoo accepted the write without a transaction key")
        self.store.finish_execution(payload_digest, "executed")
        return "executed"

    def poll_transactions(self) -> list[dict[str, str]]:
        if not self.yahoo:
            raise RuntimeError("Yahoo client is required for polling")
        results = []
        for watch in self.store.pending_transactions():
            status = (
                self.yahoo.transaction_status(watch["transaction_key"])
                or watch["status"]
            )
            self.store.watch_transaction(
                watch["transaction_key"], watch["payload_hash"], status
            )
            if status in {"successful", "accepted"}:
                self.store.finish_execution(watch["payload_hash"], "executed")
            elif status in {"rejected", "vetoed", "failed"}:
                self.store.finish_execution(watch["payload_hash"], "failed")
            if (
                self.ntfy
                and watch["status"]
                not in {
                    "successful",
                    "accepted",
                    "rejected",
                    "vetoed",
                    "failed",
                }
                and status
                in {
                    "successful",
                    "accepted",
                    "rejected",
                    "vetoed",
                    "failed",
                }
            ):
                successful = status in {"successful", "accepted"}
                self.ntfy.publish(
                    Notification(
                        title=(
                            "Fantasy transaction completed"
                            if successful
                            else "Fantasy transaction failed"
                        ),
                        message=(
                            f"Yahoo transaction {watch['transaction_key']}: {status}"
                        ),
                        priority="default" if successful else "urgent",
                    )
                )
            results.append(
                {"transaction_key": watch["transaction_key"], "status": status}
            )
        return results

    def _can_execute(self, decision: Decision) -> bool:
        if decision.requires_approval or self.settings.dry_run:
            return False
        if not self.settings.writes_enabled:
            return False
        return (
            self.settings.lineup_writes_enabled
            if decision.kind in {"lineup", "ir"}
            else False
        )

    def _revalidate(self, kind: str, payload: dict[str, Any]) -> None:
        if not self.yahoo:
            raise RuntimeError("Yahoo client is required for revalidation")
        if kind in {"fab", "trade_accept", "trade_propose"}:
            deadline = payload.get("deadline")
            if not deadline:
                raise RuntimeError(
                    "Transactional approval is missing its Yahoo deadline"
                )
            if datetime.fromisoformat(deadline) <= datetime.now(UTC):
                raise RuntimeError("Approved action is past its Yahoo deadline")
        if kind in {"lineup", "ir"}:
            for player_key in payload["positions"]:
                if not self.yahoo.roster_contains(
                    payload["team_key"], payload["week"], player_key
                ):
                    raise RuntimeError(
                        f"Player {player_key} is no longer on the Yahoo roster"
                    )
        elif kind == "fab":
            if (
                self.yahoo.weekly_fab_claims(payload["league_key"], payload["team_key"])
                >= self.league.fab.weekly_claim_limit
            ):
                raise RuntimeError("Yahoo weekly FAB claim limit is already reached")
            if self.yahoo.fab_balance(payload["team_key"]) < int(payload["bid"]):
                raise RuntimeError("Yahoo FAB balance changed below the approved bid")
            if not self.yahoo.player_is_available(
                payload["league_key"], payload["add_player_key"]
            ):
                raise RuntimeError("Approved add player is no longer available")
            drop_player_key = payload.get("drop_player_key")
            if drop_player_key and not self.yahoo.roster_contains(
                payload["team_key"], int(payload["week"]), drop_player_key
            ):
                raise RuntimeError("Approved drop player is no longer rostered")
        elif kind == "trade_accept":
            status = self.yahoo.transaction_status(payload["transaction_key"])
            if status not in {"pending", "proposed"}:
                raise RuntimeError(f"Incoming trade is no longer pending: {status}")
        elif kind == "trade_propose":
            for player_key in payload["send_player_keys"]:
                if not self.yahoo.roster_contains(
                    payload["trader_team_key"], int(payload["week"]), player_key
                ):
                    raise RuntimeError(
                        f"Trade player {player_key} is no longer rostered"
                    )

    def _manual_fallback(self, kind: str, payload: dict[str, Any]) -> str:
        base = f"https://football.fantasysports.yahoo.com/f1/{self.league.league_id}"
        path = ""
        if kind == "fab":
            path = "/players"
        elif "trade" in kind:
            path = "/proposetrade"
        return f"advisory-only: open {base}{path} and apply {canonical_json(payload)}"

    def _request_approval(self, decision_id: int, decision: Decision) -> None:
        if (
            not self.ntfy
            or not self.settings.approval_base_url
            or not self.settings.approval_signing_secret
            or not self.settings.approval_ingest_token
        ):
            return
        service = ApprovalService(
            self.store,
            base_url=self.settings.approval_base_url,
            signing_secret=self.settings.approval_signing_secret,
        )
        deadline = decision.payload.get("deadline")
        link = service.create(
            decision_id,
            decision.payload,
            yahoo_deadline=datetime.fromisoformat(deadline) if deadline else None,
        )
        if not link.is_new:
            return
        dispatched_decision = decision.to_dict()
        dispatched_decision.pop("inputs", None)
        ApprovalGateway(
            base_url=self.settings.approval_base_url,
            ingest_token=self.settings.approval_ingest_token,
        ).prepare(
            link,
            hash_payload(decision.payload),
            {"id": decision_id, **dispatched_decision},
        )
        self.ntfy.publish(
            Notification(
                title=f"Fantasy approval: {decision.kind}",
                message=(
                    f"{decision.summary}\nPayload: "
                    f"{hash_payload(decision.payload)[:12]}"
                ),
                approve_url=link.url,
                ignore_url=link.ignore_url,
            )
        )


def projection_from_dict(payload: dict[str, Any]) -> Projection:
    return Projection(
        player_key=payload["player_key"],
        name=payload["name"],
        position=payload["position"],
        nfl_team=payload.get("nfl_team", ""),
        week_points=float(payload.get("week_points", 0)),
        ros_points=float(payload.get("ros_points", 0)),
        playoff_points=float(payload.get("playoff_points", 0)),
        injury_status=payload.get("injury_status", ""),
        is_active=bool(payload.get("is_active", True)),
        bye_week=payload.get("bye_week"),
        volatility=float(payload.get("volatility", 0)),
        source_updated_at=datetime.fromisoformat(
            payload.get("source_updated_at") or datetime.now(UTC).isoformat()
        ),
    )
