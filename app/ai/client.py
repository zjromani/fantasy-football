import time
from typing import Any

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import get_ai_settings


def _client() -> OpenAI:
    s = get_ai_settings()
    return OpenAI(api_key=s.openai_api_key)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=4))
def ask(
    messages: list[dict[str, str]] | None = None,
    prompt: str | None = None,
    model: str = "gpt-4o-mini",
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Call OpenAI with messages or a simple prompt. Returns dict with 'content' key."""
    client = _client()
    
    # Support both old prompt-style and new messages-style
    if messages is None:
        if prompt is None:
            raise ValueError("Either 'messages' or 'prompt' must be provided")
        messages = [{"role": "user", "content": prompt}]
    
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    
    resp = client.chat.completions.create(**kwargs)
    content = (resp.choices[0].message.content or "").strip()
    
    return {
        "content": content,
        "model": model,
        "usage": resp.usage.model_dump() if resp.usage else {},
    }


