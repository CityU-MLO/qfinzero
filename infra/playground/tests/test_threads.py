"""Threads, stored history, context rebuild, compaction, interrupt and export."""

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import context as ctx  # noqa: E402
import main  # noqa: E402
import runner  # noqa: E402
from store import Store  # noqa: E402


class FakeLLM:
    def __init__(self):
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return AIMessage(content="- user studies SPY\n- SPY closed at 500")


LLM = FakeLLM()
SEEN: list[list] = []
LOCKS: list = []


async def fake_stream(llm, messages, as_of=None):
    SEEN.append(messages)
    LOCKS.append(as_of)
    yield {"type": "step_start", "t": 1000}
    yield {"type": "llm_chunk", "content": "Let me check. "}
    yield {"type": "step_end", "t": 1100, "text": "Let me check. ",
           "tool_calls": [{"id": "call_1", "name": "upq_stock_daily", "args": {"tickers": ["SPY"]}}],
           "usage": {"input_tokens": 900, "output_tokens": 20}}
    yield {"type": "tool_start", "id": "call_1", "tool": "upq_stock_daily", "input": {"tickers": ["SPY"]},
           "t": 1150, "run_id": "r1"}
    yield {"type": "tool_end", "id": None, "tool": "upq_stock_daily", "output": [{"close": 500.0}],
           "status": "done", "t": 1400, "run_id": "r1"}
    yield {"type": "step_start", "t": 1450}
    for part in ("SPY closed ", "at 500."):
        yield {"type": "llm_chunk", "content": part}
    yield {"type": "step_end", "t": 1600, "text": "SPY closed at 500.", "tool_calls": [],
           "usage": {"input_tokens": 1000, "output_tokens": 12}}


async def slow_stream(llm, messages, as_of=None):
    yield {"type": "step_start", "t": 1}
    yield {"type": "llm_chunk", "content": "Thinking about it"}
    await asyncio.sleep(30)
    yield {"type": "llm_chunk", "content": " never reached"}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_store", Store(tmp_path / "chat.sqlite3"))
    monkeypatch.setattr(runner, "make_llm", lambda *a, **k: (LLM, None))
    monkeypatch.setattr(runner, "stream_agent", fake_stream)
    SEEN.clear()
    with TestClient(main.app) as client:
        yield client


BODY = {"model": "m", "base_url": "http://x/v1", "api_key": "k", "as_of_date": "2026-08-20T14:00:00Z"}


def _chat(client, text, thread_id=None, user="alice", **extra):
    body = {**BODY, "messages": [{"role": "user", "content": text}], "thread_id": thread_id, **extra}
    with client.stream("POST", "/chat", json=body, headers={"x-qfz-user": user}) as r:
        assert r.status_code == 200
        return [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]


def test_chat_stores_steps_and_rebuilds_tool_context(app):
    events = _chat(app, "How did SPY close?")
    kinds = [e["type"] for e in events]
    assert kinds[0] == "turn_start" and kinds[-1] == "done"
    tid = events[0]["thread_id"]
    end = next(e for e in events if e["type"] == "tool_end")
    assert end["id"] == "call_1" and end["duration_ms"] == 250
    msg = events[-1]["message"]
    assert msg["status"] == "complete" and msg["content"] == "Let me check. \n\nSPY closed at 500."
    assert msg["usage"] == {"input_tokens": 1000, "output_tokens": 32}

    detail = app.get(f"/threads/{tid}", headers={"x-qfz-user": "alice"}).json()
    assert detail["thread"]["title"] == "How did SPY close?" and not detail["running"]
    (user, asst) = detail["messages"]
    assert asst["steps"][0]["tool_calls"][0]["output"] == [{"close": 500.0}]

    assert LOCKS[-1] == "2026-08-20T14:00:00Z"        # the cutoff locks the tools, not just the prompt
    _chat(app, "And QQQ?", thread_id=tid)
    second = SEEN[-1]
    ai = [m for m in second if isinstance(m, AIMessage)]
    assert ai[0].tool_calls[0]["id"] == "call_1"
    tool = next(m for m in second if isinstance(m, ToolMessage))
    assert tool.tool_call_id == "call_1" and "500" in tool.content
    assert second[-1].content == "And QQQ?"


def test_threads_are_private_and_exportable(app):
    tid = _chat(app, "hello there")[0]["thread_id"]
    assert app.get(f"/threads/{tid}", headers={"x-qfz-user": "bob"}).status_code == 404
    assert [t["id"] for t in app.get("/threads", headers={"x-qfz-user": "alice"}).json()["threads"]] == [tid]
    assert app.get("/threads", headers={"x-qfz-user": "bob"}).json()["threads"] == []
    assert app.get("/threads?q=hello", headers={"x-qfz-user": "alice"}).json()["threads"]
    app.patch(f"/threads/{tid}", json={"title": "SPY check"}, headers={"x-qfz-user": "alice"})
    md = app.get(f"/threads/{tid}/export", headers={"x-qfz-user": "alice"})
    assert md.headers["content-type"].startswith("text/markdown")
    assert 'filename="SPY-check.md"' in md.headers["content-disposition"]
    text = md.text
    assert text.startswith("# SPY check") and "## You" in text and "<code>upq_stock_daily</code>" in text
    assert "SPY closed at 500." in text
    assert "<code>" not in app.get(f"/threads/{tid}/export?tools=false", headers={"x-qfz-user": "alice"}).text
    ctx_info = app.get(f"/threads/{tid}/context", headers={"x-qfz-user": "alice"}).json()
    assert ctx_info["total"] > 0 and ctx_info["last_input_tokens"] == 1000
    assert app.delete(f"/threads/{tid}", headers={"x-qfz-user": "bob"}).status_code == 404
    assert app.delete(f"/threads/{tid}", headers={"x-qfz-user": "alice"}).json() == {"ok": True}
    assert app.get(f"/threads/{tid}", headers={"x-qfz-user": "alice"}).status_code == 404


def test_new_thread_and_manual_compact(app):
    tid = app.post("/threads", json={}, headers={"x-qfz-user": "alice"}).json()["id"]
    for q in ("one", "two", "three"):
        _chat(app, q, thread_id=tid)
    r = app.post(f"/threads/{tid}/compact", json={k: BODY[k] for k in ("model", "base_url", "api_key")},
                 headers={"x-qfz-user": "alice"}).json()
    assert r["ok"] and r["compacted_messages"] == 4
    info = app.get(f"/threads/{tid}/context", headers={"x-qfz-user": "alice"}).json()
    assert info["compacted_messages"] == 4 and info["summary"] > 0
    _chat(app, "four", thread_id=tid)
    sys_msg = SEEN[-1][0]
    assert "SPY closed at 500" in sys_msg.content          # the summary is in the system prompt
    assert [m.content for m in SEEN[-1] if m.type == "human"] == ["three", "four"]


@pytest.mark.asyncio
async def test_auto_compaction_and_interrupt(tmp_path, monkeypatch):
    store = Store(tmp_path / "c.sqlite3")
    monkeypatch.setattr(runner, "make_llm", lambda *a, **k: (LLM, None))
    monkeypatch.setattr(runner, "stream_agent", fake_stream)
    thread = store.create_thread("alice")
    cfg = runner.LLMConfig(api="openai", model="m", base_url="b", api_key="k")
    for q in ("a " * 3000, "b " * 3000, "c"):
        run, _ = runner.start_turn(store, store.get_thread(thread["id"], "alice"), q, cfg, BODY["as_of_date"],
                                   budget=3000)
        q_ = run.subscribe()
        await run.done.wait()
    seen = []
    while not q_.empty():
        seen.append(q_.get_nowait()["type"])
    assert "compacted" in seen
    assert store.get_thread(thread["id"], "alice")["summary_through"] >= 1

    monkeypatch.setattr(runner, "stream_agent", slow_stream)
    run, _ = runner.start_turn(store, store.get_thread(thread["id"], "alice"), "go", cfg, BODY["as_of_date"])
    with pytest.raises(RuntimeError):
        runner.start_turn(store, store.get_thread(thread["id"], "alice"), "again", cfg, BODY["as_of_date"])
    await asyncio.sleep(0.05)
    assert runner.interrupt(thread["id"])
    await asyncio.wait_for(run.done.wait(), 5)
    last = store.messages(thread["id"])[-1]
    assert last["status"] == "interrupted" and last["content"] == "Thinking about it"
    # the interrupted turn is in the next context, marked as such
    msgs = ctx.turn_messages(last, 1000)
    assert ctx.INTERRUPTED_NOTE in msgs[-1].content


def test_mcp_server_is_started_with_the_thread_cutoff_as_its_time_lock(monkeypatch):
    import mcp_tools
    monkeypatch.setenv("QFZ_TIME_LOCK_AS_OF", "2030-01-01T00:00:00Z")      # never inherited
    assert mcp_tools.get_mcp_server_params("2026-01-01T14:00:00Z").env["QFZ_TIME_LOCK_AS_OF"] == "2026-01-01T14:00:00Z"
    assert "QFZ_TIME_LOCK_AS_OF" not in mcp_tools.get_mcp_server_params(None).env
