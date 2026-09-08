from __future__ import annotations

from pathlib import Path

import httpx

from app.audit import AuditStore
from app.config import Settings
from app.providers import FantasyProsClient


def test_provider_uses_http_contract_then_cache(tmp_path: Path) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["x-api-key"] == "test-key"
        return httpx.Response(200, json={"players": [{"name": "A"}]})

    settings = Settings(
        fantasypros_api_key="test-key",
        fantasypros_api_base="https://fantasypros.example",
        cache_dir=str(tmp_path / "cache"),
        db_path=str(tmp_path / "audit.sqlite"),
    )
    store = AuditStore(settings.db_path)
    store.migrate()
    client = FantasyProsClient(
        settings=settings,
        audit=store,
        transport=httpx.MockTransport(handler),
    )

    first = client.weekly_projections(1)
    second = client.weekly_projections(1)

    assert not first.from_cache
    assert second.from_cache
    assert first.data == second.data
    assert len(requests) == 1
