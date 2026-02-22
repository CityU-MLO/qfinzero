"""LangGraph ReAct agent with dynamic LLM and MCP tools."""

from typing import AsyncIterator, Any
import json
import traceback

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage
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
    return (
        f"You are a financial analysis assistant for QFinZero. "
        f"Today's date is {as_of_date}. "
        f"When querying market data, news, or events, do not use dates beyond {as_of_date}. "
        f"Use the available tools to answer questions about stocks, options, news, economic events, "
        f"and paper trading. Always cite the data you retrieved."
    )


def convert_messages(raw_messages: list[dict]) -> list[BaseMessage]:
    """Convert plain dicts to LangChain message objects."""
    result = []
    for m in raw_messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "user":
            result.append(HumanMessage(content=content))
        elif role == "assistant":
            result.append(AIMessage(content=content))
        elif role == "system":
            result.append(SystemMessage(content=content))
    return result


async def run_agent_stream(
    messages: list[dict],
    model: str,
    base_url: str,
    api_key: str,
    as_of_date: str,
) -> AsyncIterator[dict]:
    """
    Run the ReAct agent and yield SSE-ready event dicts.

    Yields dicts with keys:
        {"type": "tool_start", "tool": str, "input": dict}
        {"type": "tool_end",   "tool": str, "output": any}
        {"type": "llm_chunk",  "content": str}
        {"type": "done"}
        {"type": "error",      "message": str}
    """
    try:
        async with get_tools() as tools:
            # Init LLM with user-provided config
            llm = init_chat_model(
                model=model,
                model_provider="openai",  # openai-compatible
                base_url=base_url,
                api_key=api_key,
                streaming=True,
            )

            # Build agent
            system_msg = build_system_prompt(as_of_date)
            agent = create_react_agent(llm, tools, prompt=system_msg)

            # Convert messages
            lc_messages = convert_messages(messages)
            input_state = {"messages": lc_messages}

            # Stream events
            async for event in agent.astream_events(input_state, version="v2"):
                kind = event.get("event")

                if kind == "on_tool_start":
                    raw_input = event.get("data", {}).get("input", {})
                    # Filter out LangGraph internal runtime context (not user-facing)
                    clean_input = {k: v for k, v in raw_input.items() if k != "runtime"} if isinstance(raw_input, dict) else raw_input
                    yield {
                        "type": "tool_start",
                        "tool": event["name"],
                        "input": safe_serialize(clean_input),
                    }

                elif kind == "on_tool_end":
                    raw_output = event.get("data", {}).get("output", "")
                    # Extract text from MCP ToolMessage content blocks
                    try:
                        if hasattr(raw_output, "content"):
                            # ToolMessage object — extract text from content blocks
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
        # Recursively unwrap ExceptionGroup to surface real leaf exceptions
        def unwrap(exc, depth=0):
            if hasattr(exc, "exceptions") and depth < 10:
                return [msg for sub in exc.exceptions for msg in unwrap(sub, depth + 1)]
            return [f"{type(exc).__name__}: {exc}"]
        leaves = unwrap(e)
        detail = " | ".join(leaves)
        yield {"type": "error", "message": detail}
