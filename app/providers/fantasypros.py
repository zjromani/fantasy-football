from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from ..audit import AuditStore
from ..config import Settings, get_settings
from .base import ProviderHealth, ProviderResponse


class FantasyProsClient:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        audit: AuditStore | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.audit = audit or AuditStore(self.settings.db_path)
        self.cache_dir = Path(self.settings.cache_dir) / "fantasypros"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = httpx.Client(transport=transport, timeout=30)

    def weekly_projections(self, week: int) -> ProviderResponse:
        return self.projections(week)

    def projections(self, week: int) -> ProviderResponse:
        return self._fetch(
            f"nfl/{self.settings.nfl_season}/projections",
            {
                "week": week,
                "positions": "QB:RB:WR:TE:K:DST:IDP:DL:LB:DB",
                "scoring": "HALF",
            },
            ttl=timedelta(hours=12),
        )

    def rest_of_season_rankings(self) -> ProviderResponse:
        return self._fetch(
            f"nfl/{self.settings.nfl_season}/consensus-rankings",
            {"position": "ALL", "type": "ROS", "scoring": "HALF"},
            ttl=timedelta(hours=48),
        )

    def news(self) -> ProviderResponse:
        return self._fetch("nfl/news", {}, ttl=timedelta(minutes=30))

    def health(self) -> ProviderHealth:
        if self.settings.fantasypros_api_key:
            return ProviderHealth(healthy=True, detail="API credentials configured")
        return ProviderHealth(
            healthy=False,
            detail="API credentials missing; only cached advisory data is available",
        )

    def _fetch(
        self, path: str, params: dict[str, Any], *, ttl: timedelta
    ) -> ProviderResponse:
        cache_path = self._cache_path(path, params)
        cached = self._read_cache(cache_path)
        now = datetime.now(UTC)
        if cached and now - cached.fetched_at <= ttl:
            return cached
        if not self.settings.fantasypros_api_key:
            if cached:
                return cached
            raise RuntimeError("FANTASYPROS_API_KEY is required")
        self.audit.increment_budget(
            "fantasypros", self.settings.fantasypros_monthly_request_limit
        )
        try:
            response = self.client.get(
                f"{self.settings.fantasypros_api_base.rstrip('/')}/{path.lstrip('/')}",
                params=params,
                headers={
                    "x-api-key": self.settings.fantasypros_api_key,
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
        except httpx.HTTPError:
            if cached:
                return cached
            raise
        payload = {"fetched_at": now.isoformat(), "data": response.json()}
        cache_path.write_text(json.dumps(payload))
        return ProviderResponse(payload["data"], now, False)

    def _read_cache(self, path: Path) -> ProviderResponse | None:
        if not path.exists():
            return None
        payload = json.loads(path.read_text())
        return ProviderResponse(
            data=payload["data"],
            fetched_at=datetime.fromisoformat(payload["fetched_at"]),
            from_cache=True,
        )

    def _cache_path(self, path: str, params: dict[str, Any]) -> Path:
        key = json.dumps([path, params], sort_keys=True).encode()
        return self.cache_dir / f"{hashlib.sha256(key).hexdigest()}.json"
