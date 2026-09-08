from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import httpx

from .config import Settings, get_settings


class YahooWriteUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class OAuthTokens:
    access_token: str
    refresh_token: str
    expires_at: float

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at - 60


@dataclass(frozen=True)
class YahooCapability:
    action: str
    available: bool
    status_code: int
    detail: str


class YahooClient:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        token_path: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.api_base_url = self.settings.yahoo_api_base.rstrip("/")
        self.auth_base_url = self.settings.yahoo_auth_base.rstrip("/")
        self.token_path = Path(token_path or self.settings.yahoo_token_path)
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_dir = Path(self.settings.cache_dir) / "yahoo"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.Client(transport=transport, timeout=30)
        self._tokens = self._load_tokens()
        if not self._tokens and self.settings.yahoo_refresh_token:
            self._tokens = OAuthTokens("", self.settings.yahoo_refresh_token, 0)

    @staticmethod
    def new_oauth_state() -> str:
        return secrets.token_urlsafe(32)

    def get_authorization_url(self, state: str, scope: str = "fspt-rw") -> str:
        self._require_credentials(secret=False)
        params = {
            "client_id": self.settings.yahoo_client_id,
            "redirect_uri": self.settings.yahoo_redirect_uri,
            "response_type": "code",
            "state": state,
            "scope": scope,
        }
        return str(
            httpx.URL(f"{self.auth_base_url}/oauth2/request_auth").copy_with(
                params=params
            )
        )

    @staticmethod
    def validate_oauth_state(expected: str, received: str) -> None:
        if not expected or not secrets.compare_digest(expected, received):
            raise ValueError("Yahoo OAuth state mismatch")

    def exchange_code_for_tokens(
        self, code: str, *, expected_state: str, received_state: str
    ) -> OAuthTokens:
        self.validate_oauth_state(expected_state, received_state)
        return self._token_request(
            {
                "grant_type": "authorization_code",
                "redirect_uri": self.settings.yahoo_redirect_uri,
                "code": code,
            }
        )

    def refresh_access_token(self) -> OAuthTokens:
        if not self._tokens or not self._tokens.refresh_token:
            raise RuntimeError("No Yahoo refresh token is configured")
        return self._token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": self._tokens.refresh_token,
            }
        )

    def get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        return self._request("GET", path, params=params)

    def post_xml(self, path: str, xml_body: str) -> httpx.Response:
        return self._request("POST", path, xml_body=xml_body)

    def put_xml(self, path: str, xml_body: str) -> httpx.Response:
        return self._request("PUT", path, xml_body=xml_body)

    def delete(self, path: str) -> httpx.Response:
        return self._request("DELETE", path)

    def get_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        cache_ttl_seconds: int = 0,
    ) -> dict:
        cache_path = self._cache_path(path, params or {})
        if cache_ttl_seconds and cache_path.exists():
            cached = json.loads(cache_path.read_text())
            fetched_at = datetime.fromisoformat(cached["fetched_at"])
            if datetime.now(UTC) - fetched_at <= timedelta(seconds=cache_ttl_seconds):
                return cached["data"]
        response = self.get(path, params={"format": "json", **(params or {})})
        payload = response.json()
        if cache_ttl_seconds:
            cache_path.write_text(
                json.dumps(
                    {
                        "fetched_at": datetime.now(UTC).isoformat(),
                        "data": payload,
                    }
                )
            )
        return payload

    def get_team_roster(self, team_key: str, week: int) -> dict:
        return self.get_json(f"team/{team_key}/roster;week={week}")

    def get_available_players(
        self, league_key: str, *, page_size: int = 25, maximum: int = 1000
    ) -> dict[str, list[dict]]:
        pages = []
        for start in range(0, maximum, page_size):
            page = self.get_json(
                f"league/{league_key}/players;status=A;start={start};count={page_size}",
                cache_ttl_seconds=900,
            )
            pages.append(page)
            player_count = sum(
                1
                for item in self._walk_dicts(page)
                if isinstance(item.get("player"), list)
            )
            if player_count < page_size:
                break
        return {"pages": pages}

    def roster_contains(self, team_key: str, week: int, player_key: str) -> bool:
        return player_key in json.dumps(self.get_team_roster(team_key, week))

    def fab_balance(self, team_key: str) -> int:
        payload = self.get_json(f"team/{team_key}")
        for item in self._walk_dicts(payload):
            if "faab_balance" in item:
                return int(item["faab_balance"])
        raise RuntimeError("Yahoo FAB balance is unavailable")

    def player_is_available(self, league_key: str, player_key: str) -> bool:
        payload = self.get_json(f"league/{league_key}/players;player_keys={player_key}")
        serialized = json.dumps(payload).lower()
        return player_key.lower() in serialized and any(
            marker in serialized
            for marker in (
                '"ownership_type": "waivers"',
                '"ownership_type": "freeagents"',
                '"ownership_type":"waivers"',
                '"ownership_type":"freeagents"',
            )
        )

    def weekly_fab_claims(self, league_key: str, team_key: str) -> int:
        payload = self.get_json(
            f"league/{league_key}/transactions;team_key={team_key};types=add,drop"
        )
        current_week = datetime.now(UTC).isocalendar()[:2]
        transaction_keys = set()
        for item in self._walk_dicts(payload):
            transaction = item.get("transaction")
            if not isinstance(transaction, list):
                continue
            flattened = self._collapse(transaction)
            serialized = json.dumps(flattened).lower()
            status = str(flattened.get("status", "")).lower()
            timestamp = flattened.get("timestamp") or flattened.get("process_time")
            processed_this_week = False
            if timestamp and str(timestamp).isdigit():
                processed_this_week = (
                    datetime.fromtimestamp(int(timestamp), UTC).isocalendar()[:2]
                    == current_week
                )
            if (
                flattened.get("transaction_key")
                and "waiver" in serialized
                and (status == "pending" or processed_this_week)
            ):
                transaction_keys.add(str(flattened["transaction_key"]))
        return len(transaction_keys)

    def set_roster(self, team_key: str, week: int, positions: dict[str, str]) -> None:
        players = "".join(
            "<player><player_key>"
            f"{self._xml(player_key)}</player_key><position>{self._xml(position)}"
            "</position></player>"
            for player_key, position in sorted(positions.items())
        )
        body = (
            '<fantasy_content xmlns="http://fantasysports.yahooapis.com/fantasy/v2/base.rng">'
            f"<roster><coverage_type>week</coverage_type><week>{week}</week>"
            f"<players>{players}</players></roster></fantasy_content>"
        )
        self.put_xml(f"team/{team_key}/roster", body)

    def submit_fab_claim(
        self,
        league_key: str,
        team_key: str,
        *,
        add_player_key: str,
        bid: int,
        drop_player_key: str | None = None,
    ) -> str | None:
        drop = ""
        transaction_type = "add"
        if drop_player_key:
            transaction_type = "add/drop"
            drop = (
                "<player><player_key>"
                f"{self._xml(drop_player_key)}</player_key><transaction_data>"
                "<type>drop</type><source_type>team</source_type>"
                f"<source_team_key>{self._xml(team_key)}</source_team_key>"
                "<destination_type>waivers</destination_type>"
                "</transaction_data></player>"
            )
        body = (
            '<fantasy_content xmlns="http://fantasysports.yahooapis.com/fantasy/v2/base.rng">'
            f"<transaction><type>{transaction_type}</type><faab_bid>{int(bid)}</faab_bid>"
            "<players><player>"
            f"<player_key>{self._xml(add_player_key)}</player_key><transaction_data>"
            "<type>add</type><source_type>waivers</source_type>"
            "<destination_type>team</destination_type>"
            f"<destination_team_key>{self._xml(team_key)}</destination_team_key>"
            f"</transaction_data></player>{drop}</players></transaction></fantasy_content>"
        )
        response = self.post_xml(f"league/{league_key}/transactions", body)
        return self._transaction_key(response)

    def act_on_trade(self, transaction_key: str, action: str) -> str:
        if action not in {"accept", "reject", "allow", "disallow"}:
            raise ValueError(f"Unsupported trade action: {action}")
        body = (
            '<fantasy_content xmlns="http://fantasysports.yahooapis.com/fantasy/v2/base.rng">'
            f"<transaction><transaction_key>{self._xml(transaction_key)}</transaction_key>"
            f"<action>{action}</action></transaction></fantasy_content>"
        )
        self.put_xml(f"transaction/{transaction_key}", body)
        return transaction_key

    def propose_trade(
        self,
        league_key: str,
        trader_team_key: str,
        tradee_team_key: str,
        *,
        send_player_keys: list[str],
        receive_player_keys: list[str],
    ) -> str | None:
        players = []
        for player_key in send_player_keys:
            players.append(
                self._trade_player_xml(player_key, trader_team_key, tradee_team_key)
            )
        for player_key in receive_player_keys:
            players.append(
                self._trade_player_xml(player_key, tradee_team_key, trader_team_key)
            )
        body = (
            '<fantasy_content xmlns="http://fantasysports.yahooapis.com/fantasy/v2/base.rng">'
            "<transaction><type>pending_trade</type>"
            f"<trader_team_key>{self._xml(trader_team_key)}</trader_team_key>"
            f"<tradee_team_key>{self._xml(tradee_team_key)}</tradee_team_key>"
            f"<players>{''.join(players)}</players></transaction></fantasy_content>"
        )
        response = self.post_xml(f"league/{league_key}/transactions", body)
        return self._transaction_key(response)

    def cancel_transaction(self, transaction_key: str) -> None:
        self.delete(f"transaction/{transaction_key}")

    def transaction(self, transaction_key: str) -> dict:
        return self.get_json(f"transaction/{transaction_key}")

    def transaction_status(self, transaction_key: str) -> str | None:
        payload = self.transaction(transaction_key)
        for item in self._walk_dicts(payload):
            if "status" in item:
                return str(item["status"]).lower()
        return None

    def probe_identical_roster(
        self, team_key: str, week: int, positions: dict[str, str]
    ) -> YahooCapability:
        try:
            self.set_roster(team_key, week, positions)
        except YahooWriteUnavailable as exc:
            return YahooCapability("lineup", False, 403, str(exc))
        except httpx.HTTPStatusError as exc:
            return YahooCapability(
                "lineup",
                False,
                exc.response.status_code,
                exc.response.text[:300],
            )
        return YahooCapability("lineup", True, 200, "Identical roster PUT accepted")

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        xml_body: str | None = None,
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        content = None
        if xml_body is not None:
            ElementTree.fromstring(xml_body)
            headers["Content-Type"] = "application/xml"
            content = xml_body.encode()
        response = self._client.request(
            method,
            f"{self.api_base_url}/{path.lstrip('/')}",
            params=params,
            content=content,
            headers=headers,
        )
        if method != "GET" and response.status_code in {401, 403, 405}:
            raise YahooWriteUnavailable(
                f"Yahoo rejected {method} write with HTTP {response.status_code}"
            )
        response.raise_for_status()
        return response

    def _token_request(self, data: dict[str, str | None]) -> OAuthTokens:
        self._require_credentials(secret=True)
        encoded = base64.b64encode(
            f"{self.settings.yahoo_client_id}:{self.settings.yahoo_client_secret}".encode()
        ).decode()
        response = self._client.post(
            f"{self.auth_base_url}/oauth2/get_token",
            headers={
                "Authorization": f"Basic {encoded}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=data,
        )
        response.raise_for_status()
        payload = response.json()
        old_refresh = self._tokens.refresh_token if self._tokens else ""
        tokens = OAuthTokens(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token") or old_refresh,
            expires_at=time.time() + float(payload.get("expires_in", 3600)),
        )
        self._save_tokens(tokens)
        return tokens

    def _access_token(self) -> str:
        if not self._tokens:
            raise RuntimeError("Yahoo OAuth tokens are not configured")
        if self._tokens.is_expired:
            self.refresh_access_token()
        if not self._tokens or not self._tokens.access_token:
            raise RuntimeError("Yahoo access token refresh failed")
        return self._tokens.access_token

    def _load_tokens(self) -> OAuthTokens | None:
        if not self.token_path.exists():
            return None
        payload = json.loads(self.token_path.read_text())
        return OAuthTokens(
            payload["access_token"],
            payload["refresh_token"],
            float(payload["expires_at"]),
        )

    def _cache_path(self, path: str, params: dict[str, Any]) -> Path:
        cache_key = json.dumps([path, params], sort_keys=True).encode()
        return self.cache_dir / f"{hashlib.sha256(cache_key).hexdigest()}.json"

    def _save_tokens(self, tokens: OAuthTokens) -> None:
        descriptor = os.open(
            self.token_path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as token_file:
            json.dump(tokens.__dict__, token_file)
        os.chmod(self.token_path, 0o600)
        self._tokens = tokens

    def _require_credentials(self, *, secret: bool) -> None:
        missing = []
        if not self.settings.yahoo_client_id:
            missing.append("YAHOO_CLIENT_ID")
        if secret and not self.settings.yahoo_client_secret:
            missing.append("YAHOO_CLIENT_SECRET")
        if missing:
            raise RuntimeError(f"Missing Yahoo settings: {', '.join(missing)}")

    @staticmethod
    def _xml(value: str) -> str:
        return (
            value.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

    @classmethod
    def _trade_player_xml(
        cls, player_key: str, source_team_key: str, destination_team_key: str
    ) -> str:
        return (
            f"<player><player_key>{cls._xml(player_key)}</player_key>"
            "<transaction_data><type>trade</type>"
            f"<source_team_key>{cls._xml(source_team_key)}</source_team_key>"
            f"<destination_team_key>{cls._xml(destination_team_key)}</destination_team_key>"
            "</transaction_data></player>"
        )

    @staticmethod
    def _transaction_key(response: httpx.Response) -> str | None:
        location = response.headers.get("location", "")
        if "/transaction/" in location:
            return location.rsplit("/transaction/", 1)[1].split("?", 1)[0]
        if not response.content:
            return None
        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError:
            return None
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] == "transaction_key":
                return element.text
        return None

    @classmethod
    def _walk_dicts(cls, value: Any):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from cls._walk_dicts(child)
        elif isinstance(value, list):
            for child in value:
                yield from cls._walk_dicts(child)

    @classmethod
    def _collapse(cls, value: Any) -> dict[str, Any]:
        result = {}
        if isinstance(value, dict):
            result.update(value)
        elif isinstance(value, list):
            for child in value:
                result.update(cls._collapse(child))
        return result


__all__ = [
    "OAuthTokens",
    "YahooCapability",
    "YahooClient",
    "YahooWriteUnavailable",
]
