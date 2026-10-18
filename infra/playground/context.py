"""Model context for a thread: rebuild, budget, trim and compact.

Each turn the context is rebuilt from the stored messages:

    system prompt (+ summary of compacted turns)
    user / assistant turns after the summary, with every tool call paired
    with its result, as the model originally saw them
    the new user message

It must fit ``budget`` tokens (the context window the user set). Two levers,
in this order:

1. **Trim tool outputs.** Results older than the last ``KEEP_FULL_TURNS``
   assistant turns are cut to ``OLD_TOOL_CHARS``; recent ones to
   ``RECENT_TOOL_CHARS``. Market data is bulky and old rows are rarely needed
   verbatim; the model can query again.
2. **Compact.** When the trimmed context is still above ``COMPACT_AT`` of the
   budget, the oldest turns (all but the last ``KEEP_TURNS``) are summarised
   by the model into the thread's summary and dropped from the context. The
   messages stay in the history and in exports.

Token counts are estimates (about 4 characters per token for Latin text, one
per CJK character); providers report the real input size per request, which
the UI shows next to the estimate.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

KEEP_FULL_TURNS = 2
OLD_TOOL_CHARS = 1_500
RECENT_TOOL_CHARS = 24_000
COMPACT_AT = 0.8
KEEP_TURNS = 2              # user+assistant pairs kept verbatim when compacting
DEFAULT_BUDGET = 128_000
INTERRUPTED_NOTE = "[The user interrupted this response.]"


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    wide = sum(1 for ch in text if ord(ch) > 0x2E7F)      # CJK and other wide scripts
    return int((len(text) - wide) / 4 + wide) + 1


def message_tokens(m: BaseMessage) -> int:
    n = estimate_tokens(m.content if isinstance(m.content, str) else json.dumps(m.content))
    for tc in getattr(m, "tool_calls", None) or []:
        n += estimate_tokens(tc["name"]) + estimate_tokens(json.dumps(tc.get("args", {}))) + 8
    return n + 4


def render_output(output: Any, limit: int) -> str:
    text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…[truncated {len(text) - limit:,} characters; call the tool again for the rest]"


def turn_messages(msg: dict, tool_limit: int) -> list[BaseMessage]:
    """LangChain messages for one stored message."""
    if msg["role"] == "user":
        return [HumanMessage(content=msg["content"])]
    out: list[BaseMessage] = []
    for step in msg.get("steps") or []:
        calls = [c for c in step.get("tool_calls") or [] if c.get("status") in ("done", "error")]
        text = step.get("text") or ""
        if not calls and not text:
            continue
        out.append(AIMessage(content=text, tool_calls=[
            {"id": c["id"], "name": c["tool"], "args": c.get("input") or {}, "type": "tool_call"} for c in calls]))
        for c in calls:
            body = c.get("output") if c.get("status") == "done" else f"Error: {c.get('error') or 'tool failed'}"
            out.append(ToolMessage(content=render_output(body, tool_limit), tool_call_id=c["id"], name=c["tool"]))
    if msg.get("status") == "interrupted":
        if out and isinstance(out[-1], AIMessage) and not out[-1].tool_calls:
            out[-1] = AIMessage(content=f"{out[-1].content}\n\n{INTERRUPTED_NOTE}".strip())
        else:
            out.append(AIMessage(content=INTERRUPTED_NOTE))
    if not out:
        # keep user/assistant alternation even for a failed turn
        out.append(AIMessage(content="(no response)" if msg.get("status") != "error"
                             else f"(the response failed: {msg.get('error') or 'error'})"))
    return out


def _turn_starts(messages: list[dict]) -> list[int]:
    return [i for i, m in enumerate(messages) if m["role"] == "user"]


def history_messages(messages: Iterable[dict], summary_through: int = -1,
                     recent_chars: int = RECENT_TOOL_CHARS) -> list[BaseMessage]:
    """Messages after the summary, tool outputs trimmed by age."""
    live = [m for m in messages if m["seq"] > summary_through]
    assistant_idx = [i for i, m in enumerate(live) if m["role"] == "assistant"]
    recent = set(assistant_idx[-KEEP_FULL_TURNS:])
    out: list[BaseMessage] = []
    for i, m in enumerate(live):
        out += turn_messages(m, recent_chars if i in recent else OLD_TOOL_CHARS)
    return out


def total_tokens(msgs: list[BaseMessage]) -> int:
    return sum(message_tokens(m) for m in msgs)


def system_message(prompt: str, summary: str | None) -> SystemMessage:
    if summary:
        prompt += ("\n\nSummary of the earlier part of this conversation (the turns themselves "
                   "are no longer in context):\n" + summary)
    return SystemMessage(content=prompt)


def usage(thread: dict, messages: list[dict], prompt: str, budget: int) -> dict:
    """Estimated context size if the next turn started now."""
    sys_t = estimate_tokens(prompt)
    sum_t = estimate_tokens(thread.get("summary") or "")
    hist = history_messages(messages, thread.get("summary_through", -1))
    msg_t = sum(message_tokens(m) for m in hist)
    last = next((m.get("usage") for m in reversed(messages) if m["role"] == "assistant" and m.get("usage")), None)
    compacted = sum(1 for m in messages if m["seq"] <= thread.get("summary_through", -1))
    return {"budget": budget, "system": sys_t, "summary": sum_t, "messages": msg_t,
            "total": sys_t + sum_t + msg_t, "messages_in_context": len(messages) - compacted,
            "compacted_messages": compacted, "last_input_tokens": (last or {}).get("input_tokens")}


def compaction_cut(messages: list[dict], summary_through: int, keep_turns: int = KEEP_TURNS) -> int | None:
    """``seq`` of the last message to fold into the summary, or None when
    there is nothing old enough to compact."""
    live = [m for m in messages if m["seq"] > summary_through]
    starts = _turn_starts(live)
    if len(starts) <= keep_turns:
        return None
    first_kept = starts[-keep_turns] if keep_turns else len(live)
    if first_kept == 0:
        return None
    return live[first_kept - 1]["seq"]


SUMMARY_PROMPT = (
    "You are compacting a conversation between a user and a financial research / paper "
    "trading assistant so it can continue in a smaller context. Write a concise summary "
    "that keeps: the user's goals and preferences; key facts and numbers retrieved (tickers, "
    "dates and times, prices, levels); conclusions reached; every identifier needed to "
    "continue (account ids, session ids, order ids, contracts); trades placed and positions "
    "held; open questions. Use short bullet points. Do not invent anything."
)


def transcript(messages: list[dict], tool_chars: int = 600) -> str:
    """Plain-text transcript fed to the summariser."""
    lines = []
    for m in messages:
        if m["role"] == "user":
            lines.append(f"USER: {m['content']}")
            continue
        for step in m.get("steps") or []:
            for c in step.get("tool_calls") or []:
                lines.append(f"TOOL {c['tool']}({json.dumps(c.get('input') or {}, ensure_ascii=False)}) -> "
                             f"{render_output(c.get('output', c.get('error')), tool_chars)}")
            if step.get("text"):
                lines.append(f"ASSISTANT: {step['text']}")
        if m.get("status") == "interrupted":
            lines.append(INTERRUPTED_NOTE)
    return "\n".join(lines)


async def summarise(llm, previous: str | None, messages: list[dict]) -> str:
    """Fold ``messages`` (and a previous summary) into a new summary."""
    body = transcript(messages)
    if previous:
        body = f"Earlier summary:\n{previous}\n\nConversation since then:\n{body}"
    res = await llm.ainvoke([SystemMessage(content=SUMMARY_PROMPT), HumanMessage(content=body)])
    content = res.content
    if isinstance(content, list):
        content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return str(content).strip()
