from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .approvals import ApprovalService
from .audit import AuditStore, hash_payload
from .config import Settings
from .league import LeagueConfig
from .normalize import extract_yahoo_settings, normalize_snapshot
from .notifications import Notification, NtfyClient
from .providers import FantasyProsClient
from .service import AutoGM
from .sync import sync_raw_state
from .yahoo_client import YahooClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fantasy-auto-gm")
    parser.add_argument("--db", default=None)
    parser.add_argument("--league-config", default=None)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("migrate")

    oauth = commands.add_parser("oauth-url")
    oauth.add_argument("--state-file", required=True)

    exchange = commands.add_parser("oauth-exchange")
    exchange.add_argument("--code", required=True)
    exchange.add_argument("--state", required=True)
    exchange.add_argument("--state-file", required=True)

    sync = commands.add_parser("sync")
    sync.add_argument("--week", type=int, required=True)
    sync.add_argument("--output", default="artifacts/raw-state.json")

    recommend = commands.add_parser("recommend")
    recommend.add_argument("--state", required=True)

    run_all = commands.add_parser("run-all")
    run_all.add_argument("--state", required=True)

    run_live = commands.add_parser("run-live")
    run_live.add_argument("--week", type=int, required=True)
    run_live.add_argument("--raw-output", default="artifacts/raw-state.json")
    run_live.add_argument(
        "--only", choices=["all", "lineup", "fab", "trades"], default="all"
    )

    execute = commands.add_parser("execute")
    execute.add_argument("--decision-id", type=int, required=True)

    execute_payload = commands.add_parser("execute-payload")
    execute_payload.add_argument("--payload", required=True)
    execute_payload.add_argument("--hash", required=True)
    execute_payload.add_argument("--approval-id", required=True)
    execute_payload.add_argument("--expires", type=int, required=True)
    execute_payload.add_argument("--signature", required=True)

    approve = commands.add_parser("approve")
    approve.add_argument("--id", required=True)
    approve.add_argument("--hash", required=True)
    approve.add_argument("--expires", type=int, required=True)
    approve.add_argument("--signature", required=True)

    probe = commands.add_parser("probe-write")
    probe.add_argument("--week", type=int, required=True)
    probe.add_argument("--positions", required=True)

    commands.add_parser("poll-transactions")

    digest = commands.add_parser("digest")
    digest.add_argument("--output")

    export = commands.add_parser("export-audit")
    export.add_argument("--output", default="artifacts/audit.json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings(
        db_path=args.db or Settings().db_path,
        league_config_path=args.league_config or Settings().league_config_path,
    )
    store = AuditStore(settings.db_path)
    store.migrate()

    if args.command == "migrate":
        return emit({"status": "ok", "database": settings.db_path})

    league = LeagueConfig.load(settings.league_config_path)
    league = league.model_copy(
        update={
            "league_key": settings.league_key or league.league_key,
            "team_key": settings.team_key or league.team_key,
        }
    )

    if args.command in {"oauth-url", "oauth-exchange"}:
        yahoo = YahooClient(settings=settings)
    if args.command == "oauth-url":
        state = yahoo.new_oauth_state()
        state_path = Path(args.state_file)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(state)
        state_path.chmod(0o600)
        return emit({"authorization_url": yahoo.get_authorization_url(state)})

    if args.command == "oauth-exchange":
        expected_state = Path(args.state_file).read_text().strip()
        tokens = yahoo.exchange_code_for_tokens(
            args.code,
            expected_state=expected_state,
            received_state=args.state,
        )
        return emit(
            {
                "status": "authorized",
                "expires_at": tokens.expires_at,
                "token_path": str(yahoo.token_path),
            }
        )

    if args.command == "sync":
        yahoo = YahooClient(settings=settings)
        provider = FantasyProsClient(settings=settings, audit=store)
        path = sync_raw_state(
            yahoo=yahoo,
            fantasypros=provider,
            league=league,
            week=args.week,
            output=args.output,
        )
        return emit({"status": "synced", "output": str(path)})

    gm = AutoGM(
        settings=settings,
        league=league,
        store=store,
        yahoo=YahooClient(settings=settings)
        if args.command
        in {
            "execute",
            "execute-payload",
            "approve",
            "probe-write",
            "poll-transactions",
            "run-live",
        }
        else None,
        ntfy=_optional_ntfy(settings),
    )

    if args.command in {"recommend", "run-all"}:
        state = json.loads(Path(args.state).read_text())
        decision_ids = gm.recommend_all(state)
        return emit({"status": "ok", "decision_ids": decision_ids})

    if args.command == "run-live":
        if not league.league_key or not league.team_key:
            raise RuntimeError("league_key and team_key are required in league config")
        raw_path = sync_raw_state(
            yahoo=gm.yahoo,
            fantasypros=FantasyProsClient(settings=settings, audit=store),
            league=league,
            week=args.week,
            output=args.raw_output,
            include_playoffs=args.only in {"all", "trades"},
        )
        raw_snapshot = json.loads(raw_path.read_text())
        state = normalize_snapshot(
            raw_snapshot,
            league_key=league.league_key,
            team_key=league.team_key,
            scoring=league.scoring,
            roster_slots=league.roster,
        )
        state["settings_drift"] = league.validate_yahoo_settings(
            extract_yahoo_settings(raw_snapshot["yahoo"]["league"])
        )
        state["trade_deadline"] = league.trade_deadline
        selected = None if args.only == "all" else {args.only}
        decision_ids = gm.recommend_all(state, only=selected)
        return emit({"status": "ok", "decision_ids": decision_ids})

    if args.command == "execute":
        decision = store.decision(args.decision_id)
        status = gm.execute(decision)
        store.save_execution(args.decision_id, status)
        return emit({"status": status, "decision_id": args.decision_id})

    if args.command == "execute-payload":
        if not settings.approval_signing_secret:
            raise RuntimeError("APPROVAL_SIGNING_SECRET is required")
        signed_message = (
            f"{args.approval_id}.{args.hash}.{args.expires}.{args.payload}"
        ).encode()
        expected_signature = hmac.new(
            settings.approval_signing_secret.encode(),
            signed_message,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_signature, args.signature):
            raise ValueError("Invalid dispatched approval signature")
        decision = json.loads(base64.b64decode(args.payload).decode())
        if hash_payload(decision["payload"]) != args.hash:
            raise ValueError("Dispatched payload hash mismatch")
        store.consume_dispatched_approval(args.approval_id, decision["id"], args.hash)
        status = gm.execute(decision, approved=True)
        store.save_execution(decision["id"], status)
        return emit({"status": status, "decision_id": decision["id"]})

    if args.command == "approve":
        if not settings.approval_base_url or not settings.approval_signing_secret:
            raise RuntimeError("Approval URL and signing secret are required")
        approval = ApprovalService(
            store,
            base_url=settings.approval_base_url,
            signing_secret=settings.approval_signing_secret,
        )
        decision_id = approval.verify_and_consume(
            args.id, args.hash, args.expires, args.signature
        )
        status = gm.execute(store.decision(decision_id), approved=True)
        store.save_execution(decision_id, status)
        return emit({"status": status, "decision_id": decision_id})

    if args.command == "probe-write":
        if not league.team_key:
            raise RuntimeError("team_key is required in league config")
        capability = gm.yahoo.probe_identical_roster(
            league.team_key,
            args.week,
            json.loads(Path(args.positions).read_text()),
        )
        store.save_capability(
            capability.action,
            capability.available,
            capability.status_code,
            capability.detail,
        )
        return emit(capability.__dict__)

    if args.command == "poll-transactions":
        return emit({"status": "ok", "transactions": gm.poll_transactions()})

    if args.command in {"digest", "export-audit"}:
        output = store.export_redacted()
        weekly = store.weekly_counts()
        if args.command == "digest" and settings.ntfy_topic and weekly["decisions"]:
            NtfyClient(settings=settings).publish(
                Notification(
                    title="Fantasy Auto-GM weekly digest",
                    message=(
                        f"{weekly['decisions']} decisions; "
                        f"{weekly['approvals']} approvals; "
                        f"{weekly['executions']} executions"
                    ),
                )
            )
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(output, indent=2, sort_keys=True))
            return emit({"status": "ok", "output": str(path)})
        return emit(output)
    return 2


def _optional_ntfy(settings: Settings) -> NtfyClient | None:
    return NtfyClient(settings=settings) if settings.ntfy_topic else None


def emit(payload: object) -> int:
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        raise SystemExit(1) from exc
