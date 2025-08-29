import json
import os
import tempfile
from pathlib import Path

import httpx
import pytest

from app.yahoo_client import YahooClient, OAuthTokens


class DummyTransport(httpx.BaseTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:  # type: ignore[override]
        if request.url.host == "api.login.yahoo.com":
            # Simulate token refresh
            if request.url.path.endswith("/get_token") and request.method == "POST":
                data = dict([p.split("=") for p in request.read().decode().split("&")])
                grant_type = data.get("grant_type")
                if grant_type == "refresh_token":
                    payload = {
                        "access_token": "new_access",
                        "refresh_token": data.get("refresh_token", "r1"),
                        "expires_in": 3600,
                    }
                    return httpx.Response(200, json=payload)
                if grant_type == "authorization_code":
                    payload = {
                        "access_token": "first_access",
                        "refresh_token": "r1",
                        "expires_in": 3600,
                    }
                    return httpx.Response(200, json=payload)
        # Default fantasy API
        return httpx.Response(200, json={"ok": True})


def test_token_persistence_and_refresh(tmp_path: Path, monkeypatch):
    token_path = tmp_path / "tokens.json"
    # Seed expired token
    token_data = {"access_token": "expired", "refresh_token": "r1", "expires_at": 0}
    token_path.write_text(json.dumps(token_data))
    monkeypatch.setenv("YAHOO_TOKEN_PATH", str(token_path))
    monkeypatch.setenv("YAHOO_CLIENT_ID", "id")
    monkeypatch.setenv("YAHOO_CLIENT_SECRET", "secret")
    monkeypatch.setenv("YAHOO_REDIRECT_URI", "http://localhost/callback")

    client = YahooClient(transport=DummyTransport())
    # First call should auto-refresh
    r = client.get("league/123")
    assert r.status_code == 200
    saved = json.loads(token_path.read_text())
    assert saved["access_token"] == "new_access"


def test_exchange_code_for_tokens(tmp_path: Path, monkeypatch):
    token_path = tmp_path / "tokens.json"
    monkeypatch.setenv("YAHOO_TOKEN_PATH", str(token_path))
    monkeypatch.setenv("YAHOO_CLIENT_ID", "id")
    monkeypatch.setenv("YAHOO_CLIENT_SECRET", "secret")
    monkeypatch.setenv("YAHOO_REDIRECT_URI", "http://localhost/callback")

    client = YahooClient(transport=DummyTransport())
    tokens = client.exchange_code_for_tokens("code123")
    assert tokens.access_token == "first_access"
    assert token_path.exists()


