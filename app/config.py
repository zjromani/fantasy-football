from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    yahoo_client_id: str | None = None
    yahoo_client_secret: str | None = None
    yahoo_redirect_uri: str = "http://localhost:8765/callback"
    yahoo_refresh_token: str | None = None
    yahoo_token_path: str = str(Path.home() / ".fantasy-bot" / "tokens.json")
    yahoo_api_base: str = "https://fantasysports.yahooapis.com/fantasy/v2"
    yahoo_auth_base: str = "https://api.login.yahoo.com"

    fantasypros_api_key: str | None = None
    fantasypros_api_base: str = "https://api.fantasypros.com/public/v2/json"
    fantasypros_monthly_request_limit: int = 800
    nfl_season: int = 2026

    league_key: str | None = None
    team_key: str | None = None
    league_config_path: str = "config/league.yml"
    db_path: str = "auto-gm.sqlite"
    cache_dir: str = ".cache"

    ntfy_base_url: str = "https://ntfy.sh"
    ntfy_topic: str | None = None
    approval_base_url: str | None = None
    approval_signing_secret: str | None = None
    approval_ingest_token: str | None = None
    github_repository: str = "zjromani/fantasy-football"

    dry_run: bool = True
    writes_enabled: bool = False
    lineup_writes_enabled: bool = False
    fab_writes_enabled: bool = False
    trade_writes_enabled: bool = False
    schedule_jitter_secret: str = "development-only"


@lru_cache
def get_settings() -> Settings:
    return Settings()
