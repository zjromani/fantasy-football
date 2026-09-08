from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx

from .audit import AuditStore, hash_payload


@dataclass(frozen=True)
class ApprovalLink:
    approval_id: str
    url: str
    ignore_url: str
    expires_at: datetime
    is_new: bool


class ApprovalService:
    def __init__(
        self, store: AuditStore, *, base_url: str, signing_secret: str
    ) -> None:
        self.store = store
        self.base_url = base_url.rstrip("/")
        self.secret = signing_secret.encode()

    def create(
        self,
        decision_id: int,
        payload: dict,
        *,
        yahoo_deadline: datetime | None = None,
    ) -> ApprovalLink:
        requested_expiry = min(
            datetime.now(UTC) + timedelta(hours=24),
            yahoo_deadline or datetime.max.replace(tzinfo=UTC),
        )
        payload_digest = hash_payload(payload)
        existing = self.store.pending_approval_for_payload(payload_digest)
        approval_id = existing.id if existing else secrets.token_urlsafe(18)
        expires_at = (
            datetime.fromisoformat(existing.expires_at)
            if existing
            else requested_expiry
        )
        expires = int(expires_at.timestamp())
        signature = self._sign(approval_id, payload_digest, expires)
        if not existing:
            self.store.create_approval(
                approval_id, decision_id, payload_digest, expires_at.isoformat()
            )
        query = urlencode(
            {
                "id": approval_id,
                "hash": payload_digest,
                "expires": expires,
                "signature": signature,
            }
        )
        return ApprovalLink(
            approval_id,
            f"{self.base_url}/approve?{query}",
            f"{self.base_url}/ignore?{query}",
            expires_at,
            not existing,
        )

    def verify_and_consume(
        self, approval_id: str, payload_digest: str, expires: int, signature: str
    ) -> int:
        expected = self._sign(approval_id, payload_digest, expires)
        if not hmac.compare_digest(expected, signature):
            raise ValueError("Invalid approval signature")
        if datetime.now(UTC).timestamp() >= expires:
            raise ValueError("Approval link expired")
        approval = self.store.consume_approval(approval_id, payload_digest)
        return approval.decision_id

    def _sign(self, approval_id: str, payload_digest: str, expires: int) -> str:
        message = f"{approval_id}.{payload_digest}.{expires}".encode()
        return hmac.new(self.secret, message, hashlib.sha256).hexdigest()


class ApprovalGateway:
    def __init__(
        self,
        *,
        base_url: str,
        ingest_token: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.ingest_token = ingest_token
        self.client = httpx.Client(transport=transport, timeout=15)

    def prepare(self, link: ApprovalLink, payload_hash: str, decision: dict) -> None:
        response = self.client.post(
            f"{self.base_url}/prepare",
            headers={
                "Authorization": f"Bearer {self.ingest_token}",
                "Content-Type": "application/json",
            },
            content=json.dumps(
                {
                    "id": link.approval_id,
                    "hash": payload_hash,
                    "expires": int(link.expires_at.timestamp()),
                    "decision": decision,
                }
            ),
        )
        response.raise_for_status()
