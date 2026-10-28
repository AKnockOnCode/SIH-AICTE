"""Optional Anthropic Messages API client (standard library only).

Used only when ANTHROPIC_API_KEY is set on the server. The key is never sent to the browser,
never logged, and every feature has a deterministic offline fallback. Any error returns None.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from ..core.config import get_settings

log = logging.getLogger("agnidrishti.llm")
API_URL = "https://api.anthropic.com/v1/messages"


def available() -> bool:
    return get_settings().llm_enabled


def complete(system: str, prompt: str, max_tokens: int = 700) -> str | None:
    s = get_settings()
    if not s.anthropic_api_key:
        return None
    body = json.dumps({
        "model": s.anthropic_model, "max_tokens": max_tokens, "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "x-api-key": s.anthropic_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=s.llm_timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        return "".join(parts).strip() or None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        log.warning("LLM call failed (%s); falling back to offline behaviour", type(exc).__name__)
        return None


def suggest_category(text: str, categories: dict[str, str]) -> dict[str, str] | None:
    options = "\n".join(f"{code}: {label}" for code, label in categories.items())
    out = complete(
        "You classify AICTE complaint texts. Answer with JSON only: {\"category\": CODE, \"rationale\": short reason}. "
        "Use exactly one CODE from the list. Do not invent facts.",
        f"Categories:\n{options}\n\nComplaint text:\n{text[:3000]}", max_tokens=200)
    if not out:
        return None
    try:
        start, end = out.find("{"), out.rfind("}")
        parsed = json.loads(out[start:end + 1])
    except ValueError:
        return None
    if parsed.get("category") not in categories:
        return None
    return {"category": parsed["category"], "rationale": str(parsed.get("rationale", ""))[:300]}
