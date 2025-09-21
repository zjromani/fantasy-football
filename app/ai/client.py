import time
from typing import Any

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import get_ai_settings


def _client() -> OpenAI:
    s = get_ai_settings()
    return OpenAI(api_key=s.openai_api_key)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=4))
def ask(prompt: str) -> str:
    """Minimal wrapper that returns a string from a trivial prompt."""
    client = _client()
    # Use Responses API style via chat.completions for broad compatibility
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return (resp.choices[0].message.content or "").strip()


