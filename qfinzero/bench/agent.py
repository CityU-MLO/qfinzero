"""Run a tool-calling LLM over the benchmark through the hub's MCP endpoint.

Any OpenAI-compatible chat-completions API works (OpenAI, vLLM, SGLang,
LiteLLM, OpenRouter, ...). For each task the runner

1. binds a PMB session when the task has ``as_of`` (or is a trading episode)
   and sends it as the ``X-QFZ-Session`` header, so the time lock is enforced
   by the server rather than by the prompt;
2. lets the model call MCP tools until it replies without a tool call;
3. scores the ``ANSWER:`` line, or the broker state for episodes.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from . import episodes
from .ops import ET
from .oracle import Endpoints
from .score import check, extract_answer
from .tasks import Task

SYSTEM = """You are a market-data analyst working with the QFinZero platform through its tools.
{clock}
Tool times are UTC unless a tool says otherwise; US market hours are given in US/Eastern (ET).
Use the tools to find the answer; do not guess numbers.
Finish with one final line of the form
ANSWER: <value>
where <value> is JSON: a number without units or % sign, a quoted string, true/false, or null."""

EPISODE = """You are trading in a QFinZero paper-trading session.
Account id: {account_id}
Session id: {session_id}
The session clock starts at {start} UTC and ends at {end} UTC. Use the pmb_* tools to place
orders and to advance the clock (pmb_step_session, pmb_step_until). Only the session's data up to
its current bar is visible. When you are done, reply with a short summary and the line
ANSWER: "done\""""


@dataclass
class LLM:
    model: str
    base_url: str
    api_key: Optional[str] = None
    temperature: float = 0.0
    max_tokens: int = 2048
    extra: dict = field(default_factory=dict)

    async def chat(self, client: httpx.AsyncClient, messages: list, tools: list) -> dict:
        body = {"model": self.model, "messages": messages, "tools": tools,
                "temperature": self.temperature, "max_tokens": self.max_tokens, **self.extra}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        r = await client.post(self.base_url.rstrip("/") + "/chat/completions", json=body,
                              headers=headers, timeout=300)
        r.raise_for_status()
        return r.json()


def lock_session(pmb, as_of: str) -> str:
    """A PMB session whose clock maps to ``as_of`` (see qfinzero.timelock).

    16:00 ET is held by a daily session on that date; any other minute by a
    minute session stepped to the bar that closes at ``as_of``.
    """
    t = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    et = t.astimezone(ET)
    acct = pmb.create_account(initial_cash=100_000, open_date=et.date().isoformat())["account_id"]
    if (et.hour, et.minute) == (16, 0):
        day = et.date().isoformat()
        sid = pmb.create_session(account_id=acct, frequency="1d", start_ts=day, end_ts=day,
                                 universe={"stocks": ["QZSP"]})["session_id"]
        pmb.step(sid, 1)
        return sid
    bar = (t - timedelta(minutes=1)).astimezone(timezone.utc)
    start = bar.strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (bar + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sid = pmb.create_session(account_id=acct, frequency="1m", start_ts=start, end_ts=end,
                             universe={"stocks": ["QZSP"]})["session_id"]
    pmb.step(sid, 1)
    return sid


def _tool_specs(tools, allow: Optional[list[str]]) -> list[dict]:
    out = []
    for t in tools:
        if allow and not any(t.name.startswith(p) for p in allow):
            continue
        out.append({"type": "function", "function": {
            "name": t.name, "description": (t.description or "")[:1024],
            "parameters": t.inputSchema or {"type": "object", "properties": {}}}})
    return out


def _tool_text(result) -> str:
    parts = [getattr(c, "text", "") for c in (result.content or [])]
    text = "\n".join(p for p in parts if p)
    return ("ERROR: " if result.isError else "") + text


@asynccontextmanager
async def _mcp_connect(url: str, headers: dict):
    """Streamable-HTTP MCP transport carrying the auth and session headers."""
    try:
        from mcp.client.streamable_http import streamable_http_client
    except ImportError:  # mcp < 1.24
        from mcp.client.streamable_http import streamablehttp_client
        async with streamablehttp_client(url, headers=headers) as streams:
            yield streams
        return
    async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(300, read=600)) as http:
        async with streamable_http_client(url, http_client=http) as streams:
            yield streams


async def _episode_loop(llm: LLM, mcp_url: str, headers: dict, system: str, user: str,
                        allow, max_turns: int, max_chars: int) -> dict:
    from mcp import ClientSession

    stats = {"tool_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "turns": 0}
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    async with _mcp_connect(mcp_url, headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = _tool_specs((await session.list_tools()).tools, allow)
            async with httpx.AsyncClient() as http:
                for _ in range(max_turns):
                    stats["turns"] += 1
                    resp = await llm.chat(http, messages, tools)
                    usage = resp.get("usage") or {}
                    stats["prompt_tokens"] += usage.get("prompt_tokens", 0)
                    stats["completion_tokens"] += usage.get("completion_tokens", 0)
                    msg = resp["choices"][0]["message"]
                    calls = msg.get("tool_calls") or []
                    messages.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")})
                    if not calls:
                        return {**stats, "reply": msg.get("content") or ""}
                    for c in calls:
                        stats["tool_calls"] += 1
                        try:
                            args = json.loads(c["function"].get("arguments") or "{}")
                            res = await session.call_tool(c["function"]["name"], args)
                            text = _tool_text(res)
                        except Exception as e:  # noqa: BLE001 — the model sees the error
                            text = f"ERROR: {type(e).__name__}: {e}"
                        if len(text) > max_chars:
                            text = text[:max_chars] + f"\n…[truncated {len(text) - max_chars} chars]"
                        messages.append({"role": "tool", "tool_call_id": c["id"], "content": text})
    return {**stats, "reply": "", "error": "max_turns reached"}


def run_agent(tasks: list[Task], llm: LLM, hub: str, api_key: Optional[str],
              allow: Optional[list[str]] = None, max_turns: int = 30, max_chars: int = 12000,
              progress=None) -> list[dict]:
    ep = Endpoints.hub(hub, api_key)
    _, _, pmb = ep.clients()
    mcp_url = hub.rstrip("/") + "/mcp/"
    results = []
    for t in tasks:
        t0 = time.perf_counter()
        r: dict = {"id": t.id, "category": t.category}
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        try:
            if t.episode:
                account_id, session_id = episodes.setup(pmb, t.episode)
                headers["X-QFZ-Session"] = session_id
                system = EPISODE.format(account_id=account_id, session_id=session_id,
                                        start=t.episode["start_ts"], end=t.episode["end_ts"])
                out = asyncio.run(_episode_loop(llm, mcp_url, headers, system, t.question,
                                                allow, max_turns, max_chars))
                r.update({k: v for k, v in out.items() if k != "reply"}, reply=out["reply"][-2000:])
                r.update(episodes.score_episode(pmb, t.episode, account_id, session_id))
            else:
                if t.as_of:
                    headers["X-QFZ-Session"] = lock_session(pmb, t.as_of)
                    et = datetime.fromisoformat(t.as_of.replace("Z", "+00:00")).astimezone(ET)
                    clock = f"The current time is {t.as_of} ({et:%Y-%m-%d %H:%M} ET). Data after it is not available."
                else:
                    clock = "The data covers January to March 2025."
                out = asyncio.run(_episode_loop(llm, mcp_url, headers, SYSTEM.format(clock=clock),
                                                t.question, allow, max_turns, max_chars))
                found, got = extract_answer(out["reply"])
                r.update({k: v for k, v in out.items() if k != "reply"}, reply=out["reply"][-2000:],
                         answer=got, expected=t.answer, answered=found,
                         correct=found and check(t.kind, t.answer, got, t.tolerance))
        except Exception as e:  # noqa: BLE001 — record and continue
            r.update(correct=False, error=f"{type(e).__name__}: {e}")
        r["seconds"] = round(time.perf_counter() - t0, 2)
        results.append(r)
        if progress:
            progress(r)
    return results
