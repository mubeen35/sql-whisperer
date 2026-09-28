"""Async Ollama HTTP client using httpx."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from db_mcp.config import get_settings

log = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        s = get_settings()
        _client = httpx.AsyncClient(
            base_url=s.ollama_base_url,
            timeout=httpx.Timeout(s.ollama_timeout),
            headers={"Content-Type": "application/json"},
        )
    return _client


async def close_client() -> None:
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


async def chat(
    messages: list[dict[str, str]],
    model: str | None = None,
    system: str | None = None,
) -> str:
    """Send a chat request and return the assistant's reply as text."""
    s = get_settings()
    model = model or s.ollama_model

    all_messages = []
    if system:
        all_messages.append({"role": "system", "content": system})
    all_messages.extend(messages)

    payload: dict[str, Any] = {
        "model": model,
        "messages": all_messages,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 2048,
        },
    }

    log.debug("ollama chat request", extra={"model": model, "msgs": len(all_messages)})
    resp = await _get_client().post("/api/chat", json=payload)
    resp.raise_for_status()

    data = resp.json()
    content = data.get("message", {}).get("content", "")
    if not content:
        raise ValueError(f"Ollama returned empty content. Raw: {data}")

    log.debug("ollama response", extra={"length": len(content)})
    return content


async def generate(prompt: str, model: str | None = None) -> str:
    """One-shot completion (non-chat). Good for single SQL generation calls."""
    s = get_settings()
    model = model or s.ollama_model

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 1024},
    }

    resp = await _get_client().post("/api/generate", json=payload)
    resp.raise_for_status()
    return resp.json().get("response", "")


async def list_models() -> list[str]:
    """Get names of locally available Ollama models."""
    try:
        resp = await _get_client().get("/api/tags")
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]
    except Exception as e:
        log.warning(f"Could not list Ollama models: {e}")
        return []


async def check_ollama_health() -> dict[str, Any]:
    try:
        resp = await _get_client().get("/api/tags")
        resp.raise_for_status()
        models = await list_models()
        return {"status": "ok", "models": models}
    except Exception as e:
        return {"status": "error", "error": str(e)}
