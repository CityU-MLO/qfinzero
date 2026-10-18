"""Model provider protocols used by the chat agent.

A provider group has one API type:

* ``openai``      OpenAI-compatible: ``{base}/chat/completions``, ``{base}/models``
                  (base usually ends in ``/v1``)
* ``anthropic``   Claude Messages API: ``{base}/v1/messages``, ``{base}/v1/models``
* ``antigravity`` Gemini (and Claude) served through an Antigravity gateway, which
                  speaks the Anthropic Messages API

For the Anthropic protocol the base URL is the one Claude Code calls
``ANTHROPIC_BASE_URL``, i.e. without ``/v1``; a trailing ``/v1`` is tolerated.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

import httpx

ApiType = Literal["openai", "anthropic", "antigravity"]
API_TYPES: tuple[str, ...] = ("openai", "anthropic", "antigravity")
ANTHROPIC_VERSION = "2023-06-01"


def protocol(api: str) -> str:
    """Wire protocol of an API type: ``openai`` or ``anthropic``."""
    if api not in API_TYPES:
        raise ValueError(f"unknown api type {api!r}; expected one of {', '.join(API_TYPES)}")
    return "openai" if api == "openai" else "anthropic"


def anthropic_root(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base[: -len("/v1")] if base.endswith("/v1") else base


def models_url(api: str, base_url: str) -> str:
    if protocol(api) == "openai":
        return base_url.rstrip("/") + "/models"
    return anthropic_root(base_url) + "/v1/models"


def auth_headers(api: str, api_key: str) -> dict[str, str]:
    """Request headers; no credentials when the key is blank (keyless local servers)."""
    if protocol(api) == "openai":
        return {"Authorization": f"Bearer {api_key}"} if api_key else {}
    headers = {"anthropic-version": ANTHROPIC_VERSION}
    if api_key:
        # x-api-key for api.anthropic.com; Bearer for gateways that read ANTHROPIC_AUTH_TOKEN
        headers |= {"x-api-key": api_key, "Authorization": f"Bearer {api_key}"}
    return headers


def _parse(payload: Any) -> tuple[list[dict], Optional[str]]:
    rows = payload.get("data", []) if isinstance(payload, dict) else payload
    models = []
    for m in rows or []:
        if isinstance(m, dict) and m.get("id"):
            models.append({"id": m["id"], "name": m.get("display_name") or m.get("name") or m["id"]})
        elif isinstance(m, str):
            models.append({"id": m, "name": m})
    nxt = payload.get("last_id") if isinstance(payload, dict) and payload.get("has_more") else None
    return models, nxt


async def list_models(api: str, base_url: str, api_key: str, proxy: Optional[str] = None,
                      transport: Optional[httpx.AsyncBaseTransport] = None) -> list[dict]:
    """``[{id, name}]`` from the provider's model list (follows Anthropic pagination)."""
    url = models_url(api, base_url)
    headers = auth_headers(api, api_key)
    out: list[dict] = []
    params: dict[str, Any] = {"limit": 1000} if protocol(api) == "anthropic" else {}
    kwargs: dict[str, Any] = {"timeout": 15, "transport": transport} if transport else {"timeout": 15, "proxy": proxy}
    async with httpx.AsyncClient(**kwargs) as client:
        for _ in range(20):
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code} from {url}: {resp.text[:200]}")
            models, nxt = _parse(resp.json())
            out += models
            if not nxt:
                break
            params = {**params, "after_id": nxt}
    seen, unique = set(), []
    for m in out:
        if m["id"] not in seen:
            seen.add(m["id"])
            unique.append(m)
    return unique


def chat_model_kwargs(api: str, model: str, base_url: str, api_key: str) -> dict[str, Any]:
    """Arguments for ``langchain.chat_models.init_chat_model``."""
    if protocol(api) == "openai":
        # keyless local servers (vLLM, Ollama, ...): the OpenAI client insists on a key
        return dict(model=model, model_provider="openai", base_url=base_url, api_key=api_key or "not-needed",
                    streaming=True, stream_usage=True)
    return dict(model=model, model_provider="anthropic", base_url=anthropic_root(base_url),
                api_key=api_key, streaming=True, max_tokens=8192)
