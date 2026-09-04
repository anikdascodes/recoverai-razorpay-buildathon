import time

import httpx

from app.config import get_settings

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

MAX_RETRIES = 2


class LLMError(Exception):
    pass


def chat(
    messages: list[dict],
    json_mode: bool = False,
    thinking: bool = False,
    max_tokens: int = 600,
) -> tuple[str, dict]:
    s = get_settings()
    if not s.llm_api_key:
        raise LLMError("LLM_API_KEY not configured")
    body: dict = {
        "model": s.agent_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "reasoning_effort": "low" if thinking else "none",
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    last_error = ""
    for attempt in range(MAX_RETRIES + 1):
        r = httpx.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {s.llm_api_key}"},
            json=body,
            timeout=45.0,
        )
        if r.status_code == 200:
            d = r.json()
            content = d["choices"][0]["message"]["content"] or ""
            return content, d.get("usage", {})
        last_error = f"groq {r.status_code}: {r.text[:200]}"
        if r.status_code == 429 and attempt < MAX_RETRIES:
            retry_after = r.headers.get("retry-after")
            delay = float(retry_after) if retry_after else 2.0 * (attempt + 1)
            time.sleep(min(delay, 10.0))
            continue
        break
    raise LLMError(last_error)
