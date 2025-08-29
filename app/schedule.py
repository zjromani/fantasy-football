from __future__ import annotations

import sys
from typing import Optional

from .models import LeagueSettings
from .brief import post_gm_brief


def gm_brief() -> int:
    # For now, use a default settings object; in real use, this would follow ingest
    settings = LeagueSettings.from_yahoo({"settings": {"roster_positions": [{"position": "QB", "count": 1}, {"position": "RB", "count": 2}, {"position": "WR", "count": 2}, {"position": "TE", "count": 1}, {"position": "W/R/T", "count": 1}, {"position": "BN", "count": 5}], "scoring": {"ppr": "full"}}})
    post_gm_brief(settings)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: python -m app.schedule gm_brief")
        return 2
    if argv[0] == "gm_brief":
        return gm_brief()
    print(f"unknown command: {argv[0]}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
