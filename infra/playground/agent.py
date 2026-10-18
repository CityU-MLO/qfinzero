"""LangGraph ReAct agent with dynamic LLM and MCP tools.

The agent is stateless: each turn gets the whole context (see ``context.py``)
and yields normalised events; ``runner.py`` turns them into the stored turn
and the stream the browser reads.
"""

from typing import AsyncIterator, Any
import json
import time

import httpx
from langchain.chat_models import init_chat_model
from langchain_core.messages import BaseMessage
from langgraph.prebuilt import create_react_agent

from mcp_tools import get_tools
from providers import chat_model_kwargs, protocol


def chunk_text(content: Any) -> str:
    """Text of a streamed chunk: a string (OpenAI) or content blocks (Anthropic
    protocol, which also streams thinking, signature and tool-input blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content
                       if isinstance(b, dict) and b.get("type") in ("text", "text_delta"))
    return ""


def safe_serialize(obj: Any) -> Any:
    """Recursively convert non-JSON-serializable objects to strings."""
    if isinstance(obj, dict):
        return {k: safe_serialize(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [safe_serialize(i) for i in obj]
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


def build_system_prompt(as_of_date: str) -> str:
    """
    as_of_date: UTC ISO string, e.g. "2025-02-26T14:00:00.000Z"
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    ET = ZoneInfo("America/New_York")

    # Parse UTC time and compute ET equivalent for human-readable display
    try:
        utc_dt = datetime.fromisoformat(as_of_date.replace("Z", "+00:00"))
        et_dt = utc_dt.astimezone(ET)
        et_str = et_dt.strftime("%Y-%m-%d %H:%M %Z")  # auto EST/EDT
        utc_str = utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        utc_str = as_of_date
        et_str = as_of_date

    return (
        f"You are a financial analysis assistant for QFinZero. "
        f"The current simulation time is {utc_str} UTC ({et_str}). "
        f"All tool datetime parameters use UTC. Convert user-mentioned times "
        f"(e.g. '10:00 AM') from ET to UTC before calling tools. "
        f"Do not use data beyond this timestamp. "
        f"When calling tools that accept a 'now_utc' parameter, always pass '{utc_str}' "
        f"to ensure backtesting data boundaries are respected. "
        f"Use the available tools to answer questions about stocks, futures, options, news, "
        f"economic events, and paper trading. Always cite the data you retrieved."
    )


def make_llm(api: str, model: str, base_url: str, api_key: str, proxy: str | None):
    """``(chat model, http client to close or None)``. The egress proxy applies to
    OpenAI-protocol calls (the Anthropic client is created by langchain-anthropic)."""
    http_client = httpx.AsyncClient(proxy=proxy) if proxy and protocol(api) == "openai" else None
    kwargs: dict[str, Any] = chat_model_kwargs(api, model, base_url, api_key)
    if http_client is not None:
        kwargs["http_async_client"] = http_client
    return init_chat_model(**kwargs), http_client


def _ms() -> int:
    return int(time.time() * 1000)


def _tool_output(raw: Any) -> Any:
    try:
        if hasattr(raw, "content"):
            blocks = raw.content
            if isinstance(blocks, str):
                text = blocks
            else:
                texts = [b["text"] for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
                text = texts[0] if texts else str(raw)
            try:
                return json.loads(text)
            except (TypeError, ValueError):
                return text
        if isinstance(raw, str):
            return json.loads(raw)
        return raw
    except Exception:
        return str(raw)[:4000]


async def run_agent_stream(llm, messages: list[BaseMessage]) -> AsyncIterator[dict]:
    """Run the ReAct agent over ``messages`` (system prompt first) and yield:

        {"type": "step_start", "t"}                     a model call begins
        {"type": "llm_chunk", "content"}
        {"type": "step_end", "t", "text", "tool_calls": [{id, name, args}], "usage"}
        {"type": "tool_start", "id", "tool", "input", "t"}
        {"type": "tool_end", "id", "tool", "output", "status", "t"}

    Errors propagate to the caller.
    """
    async with get_tools() as tools:
        agent = create_react_agent(llm, tools)
        pending: dict[str, list[str]] = {}       # tool name -> ids of the step's calls, FIFO
        async for event in agent.astream_events({"messages": messages}, version="v2"):
            kind = event.get("event")
            data = event.get("data", {})
            if kind == "on_chat_model_start":
                yield {"type": "step_start", "t": _ms()}
            elif kind == "on_chat_model_stream":
                chunk = data.get("chunk")
                text = chunk_text(getattr(chunk, "content", None)) if chunk else ""
                if text:
                    yield {"type": "llm_chunk", "content": text}
            elif kind == "on_chat_model_end":
                out = data.get("output")
                calls = [{"id": tc.get("id") or f"call_{i}", "name": tc["name"], "args": safe_serialize(tc.get("args") or {})}
                         for i, tc in enumerate(getattr(out, "tool_calls", None) or [])]
                pending = {}
                for c in calls:
                    pending.setdefault(c["name"], []).append(c["id"])
                um = getattr(out, "usage_metadata", None) or {}
                yield {"type": "step_end", "t": _ms(), "text": chunk_text(getattr(out, "content", "")),
                       "tool_calls": calls,
                       "usage": {"input_tokens": um.get("input_tokens"), "output_tokens": um.get("output_tokens")}}
            elif kind == "on_tool_start":
                raw_input = data.get("input", {})
                clean = {k: v for k, v in raw_input.items() if k != "runtime"} if isinstance(raw_input, dict) else raw_input
                ids = pending.get(event["name"]) or []
                yield {"type": "tool_start", "id": ids.pop(0) if ids else f"call_{event.get('run_id', '')[:8]}",
                       "tool": event["name"], "input": safe_serialize(clean), "t": _ms(),
                       "run_id": event.get("run_id")}
            elif kind == "on_tool_end":
                raw = data.get("output", "")
                status = "error" if getattr(raw, "status", None) == "error" else "done"
                yield {"type": "tool_end", "id": getattr(raw, "tool_call_id", None), "tool": event["name"],
                       "output": safe_serialize(_tool_output(raw)), "status": status, "t": _ms(),
                       "run_id": event.get("run_id")}
