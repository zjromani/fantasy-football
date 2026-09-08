from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from app.approvals import ApprovalService
from app.audit import AuditStore
from app.domain import Decision


def test_signed_approval_is_single_use_and_payload_bound(tmp_path: Path) -> None:
    store = AuditStore(tmp_path / "audit.sqlite")
    store.migrate()
    payload = {"kind": "fab", "bid": 7}
    decision_id = store.save_decision(
        Decision(
            kind="fab",
            score=10,
            summary="claim",
            payload=payload,
            source_updated_at=datetime.now(UTC),
            requires_approval=True,
        )
    )
    service = ApprovalService(
        store, base_url="https://approvals.example", signing_secret="secret"
    )
    link = service.create(decision_id, payload)
    query = {
        key: values[0] for key, values in parse_qs(urlparse(link.url).query).items()
    }

    consumed_id = service.verify_and_consume(
        query["id"], query["hash"], int(query["expires"]), query["signature"]
    )

    assert consumed_id == decision_id
    with pytest.raises(ValueError, match="already"):
        service.verify_and_consume(
            query["id"], query["hash"], int(query["expires"]), query["signature"]
        )


def test_duplicate_payload_reuses_pending_approval(tmp_path: Path) -> None:
    store = AuditStore(tmp_path / "audit.sqlite")
    store.migrate()
    decision = Decision(
        kind="fab",
        score=10,
        summary="claim",
        payload={"bid": 7},
        source_updated_at=datetime.now(UTC),
        requires_approval=True,
    )
    first_id = store.save_decision(decision)
    second_id = store.save_decision(decision)
    service = ApprovalService(
        store, base_url="https://approvals.example", signing_secret="secret"
    )

    first = service.create(first_id, decision.payload)
    second = service.create(second_id, decision.payload)

    assert first.is_new
    assert not second.is_new
    assert first.approval_id == second.approval_id


def test_approval_expires_at_yahoo_deadline(tmp_path: Path) -> None:
    store = AuditStore(tmp_path / "audit.sqlite")
    store.migrate()
    decision_id = store.save_decision(
        Decision(
            kind="trade_accept",
            score=1,
            summary="trade",
            payload={"transaction_key": "1"},
            source_updated_at=datetime.now(UTC),
            requires_approval=True,
        )
    )
    service = ApprovalService(
        store, base_url="https://approvals.example", signing_secret="secret"
    )
    deadline = datetime.now(UTC) + timedelta(minutes=5)

    link = service.create(
        decision_id, {"transaction_key": "1"}, yahoo_deadline=deadline
    )

    assert abs((link.expires_at - deadline).total_seconds()) < 1
