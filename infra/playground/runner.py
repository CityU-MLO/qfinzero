"""One assistant turn, run in the background.

``start_turn`` stores the user message, then runs the agent in an asyncio task
that builds the assistant record step by step and fans its events out to any
subscribed stream. The run does not depend on the browser: closing the page
keeps it going (the thread shows it as running and the result is stored), and
``interrupt`` cancels it, keeping what was produced so far with status
``interrupted``.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import agent as agent_mod
import context as ctx
from store import Store, new_id, title_from

TERMINAL = ("done", "interrupted", "error")


@dataclass
class LLMConfig:
    api: str
    model: str
    base_url: str
    api_key: str
    proxy: Optional[str] = None


@dataclass
class Run:
    thread_id: str
    record: dict
    task: Optional[asyncio.Task] = None
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    done: asyncio.Event = field(default_factory=asyncio.Event)

    def publish(self, event: dict) -> None:
        for q in list(self.subscribers):
            q.put_nowait(event)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self.subscribers:
            self.subscribers.remove(q)


RUNS: dict[str, Run] = {}

# Injection points for tests.
make_llm: Callable[..., Any] = agent_mod.make_llm
stream_agent: Callable[..., Any] = agent_mod.run_agent_stream


def _ms() -> int:
    return int(time.time() * 1000)


async def prepare_context(store: Store, thread: dict, llm, prompt: str, budget: int,
                          auto_compact: bool, publish: Callable[[dict], None]) -> list:
    """System prompt + history for the next model call, compacting first when
    the estimate is above ``COMPACT_AT`` of the budget."""
    messages = store.messages(thread["id"])
    through = thread.get("summary_through", -1)
    hist = ctx.history_messages(messages, through)
    total = ctx.estimate_tokens(prompt) + ctx.estimate_tokens(thread.get("summary") or "") + ctx.total_tokens(hist)
    if auto_compact and total > ctx.COMPACT_AT * budget:
        cut = ctx.compaction_cut(messages, through)
        if cut is not None:
            folded = [m for m in messages if through < m["seq"] <= cut]
            summary = await ctx.summarise(llm, thread.get("summary"), folded)
            thread = store.update_thread(thread["id"], thread["owner"], summary=summary, summary_through=cut) or thread
            through = cut
            hist = ctx.history_messages(messages, through)
            publish({"type": "compacted", "through": cut, "messages": len(folded),
                     "summary_tokens": ctx.estimate_tokens(summary)})
    system = ctx.system_message(prompt, thread.get("summary"))
    if ctx.message_tokens(system) + ctx.total_tokens(hist) > budget:
        hist = ctx.history_messages(messages, through, recent_chars=ctx.OLD_TOOL_CHARS)
    return [system, *hist]


def _apply(record: dict, ev: dict, run_ids: dict[str, str]) -> Optional[dict]:
    """Fold an agent event into the record; returns the event for the browser."""
    steps = record["steps"]
    kind = ev["type"]
    if kind == "step_start":
        steps.append({"text": "", "tool_calls": [], "started_at": ev["t"], "ended_at": None})
        return {"type": "step_start", "step": len(steps) - 1, "t": ev["t"]}
    if not steps:
        steps.append({"text": "", "tool_calls": [], "started_at": _ms(), "ended_at": None})
    step = steps[-1]
    si = len(steps) - 1
    if kind == "llm_chunk":
        step["text"] += ev["content"]
        return {"type": "llm_chunk", "step": si, "content": ev["content"]}
    if kind == "step_end":
        if ev.get("text") and len(ev["text"]) >= len(step["text"]):
            step["text"] = ev["text"]
        step["ended_at"] = ev["t"]
        step["usage"] = ev.get("usage")
        step["tool_calls"] = [{"id": c["id"], "tool": c["name"], "input": c["args"], "status": "pending"}
                              for c in ev.get("tool_calls") or []]
        return {"type": "step_end", "step": si, "t": ev["t"], "text": step["text"],
                "tool_calls": step["tool_calls"], "usage": ev.get("usage")}
    if kind == "tool_start":
        call = next((c for s in reversed(steps) for c in s["tool_calls"] if c["id"] == ev["id"]), None)
        if call is None:
            call = {"id": ev["id"], "tool": ev["tool"], "input": ev.get("input"), "status": "pending"}
            step["tool_calls"].append(call)
        call.update(status="running", started_at=ev["t"])
        if ev.get("input") is not None:
            call["input"] = ev["input"]
        if ev.get("run_id"):
            run_ids[ev["run_id"]] = call["id"]
        return {"type": "tool_start", "step": si, "id": call["id"], "tool": call["tool"],
                "input": call["input"], "t": ev["t"]}
    if kind == "tool_end":
        cid = ev.get("id") or run_ids.get(ev.get("run_id") or "")
        call = next((c for s in reversed(steps) for c in s["tool_calls"] if c["id"] == cid), None) or next(
            (c for s in reversed(steps) for c in s["tool_calls"] if c["tool"] == ev["tool"] and c["status"] == "running"),
            None)
        if call is None:
            return None
        call.update(status=ev.get("status", "done"), ended_at=ev["t"])
        if call["status"] == "error":
            call["error"] = ev.get("output") if isinstance(ev.get("output"), str) else str(ev.get("output"))
        call["output"] = ev.get("output")
        return {"type": "tool_end", "step": si, "id": call["id"], "tool": call["tool"], "status": call["status"],
                "output": call["output"], "t": ev["t"],
                "duration_ms": ev["t"] - call.get("started_at", ev["t"])}
    return None


def _finish_record(record: dict, status: str, error: str | None = None) -> None:
    record["status"] = status
    record["finished_at"] = time.time()
    if error:
        record["error"] = error
    for s in record["steps"]:
        for c in s["tool_calls"]:
            if c["status"] in ("pending", "running"):
                c["status"] = "cancelled" if status == "interrupted" else "error"
    record["content"] = "\n\n".join(s["text"] for s in record["steps"] if s.get("text"))
    ins = [s.get("usage", {}) or {} for s in record["steps"]]
    record["usage"] = {"input_tokens": next((u.get("input_tokens") for u in reversed(ins) if u.get("input_tokens")), None),
                       "output_tokens": sum(u.get("output_tokens") or 0 for u in ins) or None}


async def _run(store: Store, run: Run, thread: dict, llm_cfg: LLMConfig, as_of: str,
               budget: int, auto_compact: bool) -> None:
    record = run.record
    run_ids: dict[str, str] = {}
    http_client = None
    status, error = "complete", None
    try:
        llm, http_client = make_llm(llm_cfg.api, llm_cfg.model, llm_cfg.base_url, llm_cfg.api_key, llm_cfg.proxy)
        messages = await prepare_context(store, thread, llm, agent_mod.build_system_prompt(as_of), budget,
                                         auto_compact, run.publish)
        record["context_tokens"] = ctx.total_tokens(messages)
        run.publish({"type": "context", "tokens": record["context_tokens"], "budget": budget})
        async for ev in stream_agent(llm, messages, as_of=as_of or None):
            out = _apply(record, ev, run_ids)
            if out is not None:
                run.publish(out)
    except asyncio.CancelledError:
        status = "interrupted"
    except Exception as e:  # noqa: BLE001 — reported to the user and stored with the turn
        def leaves(exc, depth=0):
            if hasattr(exc, "exceptions") and depth < 10:
                return [m for sub in exc.exceptions for m in leaves(sub, depth + 1)]
            return [f"{type(exc).__name__}: {exc}"]
        status, error = "error", " | ".join(leaves(e))
    except BaseException:  # noqa: BLE001 — a cancel wrapped in an exception group by the MCP task group
        status = "interrupted"
    finally:
        if http_client is not None:
            try:
                await http_client.aclose()
            except Exception:  # noqa: BLE001
                pass
        _finish_record(record, status, error)
        saved = store.add_message(thread["id"], "assistant", record["content"], id=record["id"],
                                  steps=record["steps"], status=status, error=error, model=llm_cfg.model,
                                  usage=record["usage"], created_at=record["created_at"],
                                  finished_at=record["finished_at"])
        store.update_thread(thread["id"], thread["owner"], model=llm_cfg.model, api=llm_cfg.api, as_of=as_of)
        RUNS.pop(thread["id"], None)
        kind = {"complete": "done", "interrupted": "interrupted", "error": "error"}[status]
        run.publish({"type": kind, "message": saved, **({"error": error} if error else {})})
        run.done.set()


def start_turn(store: Store, thread: dict, text: str, llm_cfg: LLMConfig, as_of: str,
               budget: int = ctx.DEFAULT_BUDGET, auto_compact: bool = True) -> tuple[Run, dict]:
    """Store the user message and start the assistant turn. Raises RuntimeError
    when the thread already has a running turn."""
    if thread["id"] in RUNS:
        raise RuntimeError("this conversation is still answering; stop it first")
    user = store.add_message(thread["id"], "user", text)
    if not thread.get("title"):
        thread = store.update_thread(thread["id"], thread["owner"], title=title_from(text)) or thread
    record = {"id": new_id("msg"), "thread_id": thread["id"], "role": "assistant", "content": "",
              "steps": [], "status": "running", "model": llm_cfg.model, "created_at": time.time()}
    run = Run(thread_id=thread["id"], record=record)
    RUNS[thread["id"]] = run
    run.task = asyncio.create_task(_run(store, run, thread, llm_cfg, as_of, budget, auto_compact))
    return run, user


def interrupt(thread_id: str) -> bool:
    run = RUNS.get(thread_id)
    if run is None or run.task is None or run.task.done():
        return False
    run.task.cancel()
    return True
