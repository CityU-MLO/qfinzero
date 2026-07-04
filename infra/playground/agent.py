"""LangGraph ReAct agent with dynamic LLM and MCP tools."""

from typing import AsyncIterator, Any
import json
import traceback

import httpx
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from mcp_tools import get_tools


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
    from datetime import datetime, timezone
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
        f"Use the available tools to answer questions about stocks, news, economic events, "
        f"and paper trading. Always cite the data you retrieved."
    )


# Module-level checkpointer — persists across requests for the lifetime of the process
_checkpointer = MemorySaver()


async def run_agent_stream(
    thread_id: str,
    user_message: str,
    model: str,
    base_url: str,
    api_key: str,
    as_of_date: str,
    proxy: str | None = None,
) -> AsyncIterator[dict]:
    """
    Run the ReAct agent for one user turn and yield SSE-ready event dicts.
    Conversation state (including tool call history) is persisted in-process
    via MemorySaver, keyed by thread_id.

    Yields dicts with keys:
        {"type": "tool_start", "tool": str, "input": dict}
        {"type": "tool_end",   "tool": str, "output": any}
        {"type": "llm_chunk",  "content": str}
        {"type": "done"}
        {"type": "error",      "message": str}
    """
    # Route LLM API calls through the egress proxy when configured; local MCP tool
    # calls are unaffected (they run over stdio, not this client).
    http_client = httpx.AsyncClient(proxy=proxy) if proxy else None
    try:
        async with get_tools() as tools:
            llm_kwargs: dict[str, Any] = dict(
                model=model,
                model_provider="openai",
                base_url=base_url,
                api_key=api_key,
                streaming=True,
            )
            if http_client is not None:
                llm_kwargs["http_async_client"] = http_client
            llm = init_chat_model(**llm_kwargs)

            system_msg = build_system_prompt(as_of_date)
            agent = create_react_agent(
                llm, tools, prompt=system_msg, checkpointer=_checkpointer
            )

            config = {"configurable": {"thread_id": thread_id}}
            input_state = {"messages": [HumanMessage(content=user_message)]}

            async for event in agent.astream_events(input_state, config=config, version="v2"):
                kind = event.get("event")

                if kind == "on_tool_start":
                    raw_input = event.get("data", {}).get("input", {})
                    clean_input = {k: v for k, v in raw_input.items() if k != "runtime"} if isinstance(raw_input, dict) else raw_input
                    yield {
                        "type": "tool_start",
                        "tool": event["name"],
                        "input": safe_serialize(clean_input),
                    }

                elif kind == "on_tool_end":
                    raw_output = event.get("data", {}).get("output", "")
                    try:
                        if hasattr(raw_output, "content"):
                            blocks = raw_output.content
                            texts = [b["text"] for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
                            text = texts[0] if texts else str(raw_output)
                            output = json.loads(text)
                        elif isinstance(raw_output, str):
                            output = json.loads(raw_output)
                        else:
                            output = raw_output
                    except Exception:
                        output = str(raw_output)[:2000]
                    yield {
                        "type": "tool_end",
                        "tool": event["name"],
                        "output": safe_serialize(output),
                    }

                elif kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        yield {"type": "llm_chunk", "content": chunk.content}

            yield {"type": "done"}

    except Exception as e:
        def unwrap(exc, depth=0):
            if hasattr(exc, "exceptions") and depth < 10:
                return [msg for sub in exc.exceptions for msg in unwrap(sub, depth + 1)]
            return [f"{type(exc).__name__}: {exc}"]
        leaves = unwrap(e)
        yield {"type": "error", "message": " | ".join(leaves)}
    finally:
        if http_client is not None:
            await http_client.aclose()
