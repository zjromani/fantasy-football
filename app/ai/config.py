from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, ValidationError


class AISettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")
    ai_autopilot: bool = Field(False, alias="AI_AUTOPILOT")


def get_ai_settings() -> AISettings:
    return AISettings()


