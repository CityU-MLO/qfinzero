"""Provider protocols of the chat agent (no network: httpx.MockTransport)."""

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import providers as P  # noqa: E402


def test_urls_and_headers():
    assert P.models_url("openai", "http://h:8081/v1/") == "http://h:8081/v1/models"
    assert P.models_url("antigravity", "http://h:8081/antigravity") == "http://h:8081/antigravity/v1/models"
    assert P.models_url("anthropic", "https://api.anthropic.com/v1") == "https://api.anthropic.com/v1/models"
    assert P.auth_headers("openai", "k") == {"Authorization": "Bearer k"}
    h = P.auth_headers("antigravity", "k")
    assert h["x-api-key"] == "k" and h["anthropic-version"]
    assert P.auth_headers("openai", "") == {}
    assert "x-api-key" not in P.auth_headers("anthropic", "")
    with pytest.raises(ValueError):
        P.protocol("gemini")


def test_chat_model_kwargs():
    o = P.chat_model_kwargs("openai", "gpt-6", "http://h/v1", "k")
    assert o["model_provider"] == "openai" and o["base_url"] == "http://h/v1"
    a = P.chat_model_kwargs("antigravity", "gemini-3-flash", "http://h/antigravity/v1", "k")
    assert a["model_provider"] == "anthropic" and a["base_url"] == "http://h/antigravity"


def _run(api, handler):
    return asyncio.run(P.list_models(api, "http://h/x", "k", transport=httpx.MockTransport(handler)))


def test_openai_model_list():
    def handler(req):
        assert req.url.path == "/x/models" and req.headers["authorization"] == "Bearer k"
        return httpx.Response(200, json={"data": [{"id": "gpt-6", "display_name": "GPT-6"}, {"id": "gpt-6"}, {"id": "o9"}]})
    assert _run("openai", handler) == [{"id": "gpt-6", "name": "GPT-6"}, {"id": "o9", "name": "o9"}]


def test_anthropic_pagination():
    pages = {None: {"data": [{"id": "a"}], "has_more": True, "last_id": "a"},
             "a": {"data": [{"id": "b", "display_name": "B"}], "has_more": False}}

    def handler(req):
        assert req.url.path == "/x/v1/models" and req.headers["x-api-key"] == "k"
        return httpx.Response(200, json=pages[req.url.params.get("after_id")])
    assert [m["id"] for m in _run("anthropic", handler)] == ["a", "b"]


def test_error_status_is_reported():
    with pytest.raises(RuntimeError, match="HTTP 401"):
        _run("openai", lambda req: httpx.Response(401, text="bad key"))


def test_chunk_text_handles_both_protocols():
    import importlib
    try:
        agent = importlib.import_module("agent")
    except Exception:  # agent needs the langchain stack; skip if unavailable
        pytest.skip("langchain stack not installed")
    assert agent.chunk_text("hi") == "hi"
    assert agent.chunk_text([{"type": "text", "text": "a"}, {"type": "thinking", "thinking": "x"},
                             {"type": "text", "text": "b"}]) == "ab"
    assert agent.chunk_text(None) == ""
