import os
import pytest


def test_missing_openai_key_monkeypatch(monkeypatch):
    # Ensure OPENAI_API_KEY is missing
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from app.ai.config import AISettings
    with pytest.raises(Exception):
        AISettings()


