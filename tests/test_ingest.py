import json
from pathlib import Path

import httpx

from app.ingest import fetch_league_bundle, ingest
from app.yahoo_client import YahooClient


class FixtureTransport(httpx.BaseTransport):
    def __init__(self, fixtures_dir: Path):
        self.fixtures_dir = fixtures_dir

    def handle_request(self, request: httpx.Request) -> httpx.Response:  # type: ignore[override]
        # Map path endings to fixture files
        mapping = {
            "league/": "league.json",
            "/teams": "teams.json",
            "/rosters": "rosters.json",
            "/players": "players.json",
            "/scoreboard": "matchups.json",
            "/standings": "standings.json",
            "/transactions": "transactions.json",
        }
        path = request.url.path
        fixture_name = None
        if "/league/" in path and path.endswith(tuple(mapping.keys())) is False:
            # league root
            fixture_name = "league.json"
        else:
            for suffix, fname in mapping.items():
                if path.endswith(suffix):
                    fixture_name = fname
                    break
        if fixture_name is None:
            return httpx.Response(404, json={"error": "not found"})
        data = json.loads((self.fixtures_dir / fixture_name).read_text())
        return httpx.Response(200, json=data)


def test_ingest_fetches_and_caches(tmp_path: Path, monkeypatch):
    fixtures = Path(__file__).parent / "fixtures"
    transport = FixtureTransport(fixtures)
    # Seed a fake token so YahooClient auth header is present but not used by transport
    token_path = tmp_path / "tokens.json"
    token_path.write_text(json.dumps({"access_token": "t", "refresh_token": "r", "expires_at": 9999999999}))
    monkeypatch.setenv("YAHOO_TOKEN_PATH", str(token_path))
    monkeypatch.setenv("YAHOO_CLIENT_ID", "id")
    monkeypatch.setenv("YAHOO_CLIENT_SECRET", "secret")
    monkeypatch.setenv("YAHOO_REDIRECT_URI", "http://localhost/callback")

    client = YahooClient(transport=transport)

    cache_dir = tmp_path / ".cache"
    bundle = fetch_league_bundle(client, "nfl.l.123", cache_dir=str(cache_dir))

    # basic shape
    assert "league" in bundle and "teams" in bundle and "standings" in bundle

    # cache files created
    files = list(cache_dir.glob("*.json"))
    assert len(files) >= 3

    # settings parse
    _, settings = ingest(client, "nfl.l.123", cache_dir=str(cache_dir))
    assert settings.positional_limits.qb == 1
    assert settings.positional_limits.flex == 1
    assert settings.bench_size == 5
    assert settings.faab_budget == 100
    assert settings.trade_deadline_week == 10


