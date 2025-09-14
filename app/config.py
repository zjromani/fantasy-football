from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(".env"), env_file_encoding="utf-8", extra="ignore")

    # Yahoo API
    yahoo_client_id: Optional[str] = None
    yahoo_client_secret: Optional[str] = None
    yahoo_redirect_uri: Optional[str] = None

    # DB
    db_path: Optional[str] = None

    # League
    league_key: Optional[str] = None


@lru_cache()
def get_settings() -> Settings:
    return Settings()


