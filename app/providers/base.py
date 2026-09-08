from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderResponse:
    data: dict[str, Any]
    fetched_at: datetime
    from_cache: bool


@dataclass(frozen=True)
class ProviderHealth:
    healthy: bool
    detail: str


class ProjectionProvider(Protocol):
    def projections(self, week: int) -> ProviderResponse: ...

    def weekly_projections(self, week: int) -> ProviderResponse: ...

    def rest_of_season_rankings(self) -> ProviderResponse: ...

    def news(self) -> ProviderResponse: ...

    def health(self) -> ProviderHealth: ...
