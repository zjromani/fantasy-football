from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, ValidationError


class AISettings(BaseSettings):
    # Do not auto-load .env here to keep tests deterministic; rely on real env
    model_config = SettingsConfigDict(extra="ignore")

    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")
    ai_autopilot: bool = Field(False, alias="AI_AUTOPILOT")


def get_ai_settings() -> AISettings:
    return AISettings()


