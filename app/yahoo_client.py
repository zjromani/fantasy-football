from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from .config import get_settings


# Yahoo Fantasy Sports API docs:
# Auth: https://developer.yahoo.com/oauth2/guide/
# Fantasy endpoints: https://developer.yahoo.com/fantasysports/guide/


DEFAULT_TOKEN_PATH = os.path.join(Path.home(), ".fantasy-bot", "tokens.json")
YAHOO_AUTH_BASE = "https://api.login.yahoo.com"
YAHOO_API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"


@dataclass
class OAuthTokens:
    access_token: str
    refresh_token: str
    expires_at: float

    @property
    def is_expired(self) -> bool:
        # Refresh slightly early (60s) to avoid race
        return time.time() >= (self.expires_at - 60)


class YahooClient:
    def __init__(
        self,
        *,
        token_path: Optional[str] = None,
        transport: Optional[httpx.BaseTransport] = None,
        api_base_url: str = YAHOO_API_BASE,
    ) -> None:
        self.settings = get_settings()
        self.api_base_url = api_base_url.rstrip("/")
        self.token_path = token_path or os.environ.get("YAHOO_TOKEN_PATH", DEFAULT_TOKEN_PATH)
        self._client = httpx.Client(transport=transport, timeout=30)
        self._tokens: Optional[OAuthTokens] = None

        # Ensure token directory exists
        token_dir = os.path.dirname(self.token_path)
        if token_dir:
            Path(token_dir).mkdir(parents=True, exist_ok=True)

        # Try load tokens at init for convenience
        self._tokens = self._load_tokens()

    # --- Token storage ---
    def _load_tokens(self) -> Optional[OAuthTokens]:
        try:
            if not os.path.exists(self.token_path):
                return None
            with open(self.token_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return OAuthTokens(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                expires_at=float(data["expires_at"]),
            )
        except Exception:
            return None

    def _save_tokens(self, tokens: OAuthTokens) -> None:
        data = {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "expires_at": tokens.expires_at,
        }
        with open(self.token_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        self._tokens = tokens

    # --- OAuth flows ---
    def get_authorization_url(self, state: str = "state", scope: str = "fspt-r") -> str:
        client_id = self.settings.yahoo_client_id
        redirect_uri = self.settings.yahoo_redirect_uri
        if not client_id or not redirect_uri:
            raise RuntimeError("Yahoo client_id and redirect_uri must be configured")
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scope,
            "state": state,
        }
        return httpx.URL(f"{YAHOO_AUTH_BASE}/oauth2/request_auth").copy_add_params(params).human_repr()

    def exchange_code_for_tokens(self, code: str) -> OAuthTokens:
        client_id = self.settings.yahoo_client_id
        client_secret = self.settings.yahoo_client_secret
        redirect_uri = self.settings.yahoo_redirect_uri
        if not client_id or not client_secret or not redirect_uri:
            raise RuntimeError("Yahoo client_id, client_secret, and redirect_uri must be configured")

        response = self._client.post(
            f"{YAHOO_AUTH_BASE}/oauth2/get_token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "code": code,
                "grant_type": "authorization_code",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        payload = response.json()
        tokens = OAuthTokens(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token", self._tokens.refresh_token if self._tokens else ""),
            expires_at=time.time() + float(payload.get("expires_in", 3600)),
        )
        self._save_tokens(tokens)
        return tokens

    def refresh_access_token(self) -> OAuthTokens:
        if not self._tokens or not self._tokens.refresh_token:
            raise RuntimeError("No refresh_token present; complete authorization first")

        client_id = self.settings.yahoo_client_id
        client_secret = self.settings.yahoo_client_secret
        if not client_id or not client_secret:
            raise RuntimeError("Yahoo client_id and client_secret must be configured")

        response = self._client.post(
            f"{YAHOO_AUTH_BASE}/oauth2/get_token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": self._tokens.refresh_token,
                "grant_type": "refresh_token",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        payload = response.json()
        tokens = OAuthTokens(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token", self._tokens.refresh_token),
            expires_at=time.time() + float(payload.get("expires_in", 3600)),
        )
        self._save_tokens(tokens)
        return tokens

    # --- Request helpers ---
    def _ensure_valid_access_token(self) -> str:
        # Try to load from disk if memory empty
        if self._tokens is None:
            self._tokens = self._load_tokens()
        # Refresh if missing or expired
        if self._tokens is None:
            raise RuntimeError("No OAuth tokens found. Authorize first.")
        if self._tokens.is_expired:
            self.refresh_access_token()
        assert self._tokens is not None
        return self._tokens.access_token

    def _auth_headers(self) -> Dict[str, str]:
        token = self._ensure_valid_access_token()
        return {"Authorization": f"Bearer {token}"}

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
        url = self._build_url(path)
        headers = self._auth_headers()
        return self._client.get(url, params=params, headers=headers)

    def post_xml(self, path: str, xml_body: str) -> httpx.Response:
        url = self._build_url(path)
        headers = self._auth_headers()
        headers.update({"Content-Type": "application/xml"})
        return self._client.post(url, content=xml_body.encode("utf-8"), headers=headers)

    def _build_url(self, path: str) -> str:
        path_clean = path.lstrip("/")
        return f"{self.api_base_url}/{path_clean}"


__all__ = ["YahooClient", "OAuthTokens", "DEFAULT_TOKEN_PATH"]


