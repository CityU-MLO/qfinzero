"""Playground Agent Service — FastAPI + SSE.

Conversations are threads stored in SQLite (``store.py``) and scoped to the
hub user (``x-qfz-user``). A turn runs in the background (``runner.py``):
``POST /chat`` streams it, ``POST /threads/{id}/interrupt`` stops it, and
``GET /threads/{id}`` shows a running turn's progress to a page that
reconnects.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (PROJECT_ROOT, Path(__file__).resolve().parent):   # repo, and this service's modules
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from config import HOST, PORT, LLM_PROXY
import context as ctx
import runner
from agent import build_system_prompt
from export import thread_markdown
from providers import API_TYPES, list_models
from qfinzero.runtime import qfinzero_version
from store import Store


app = FastAPI(title="QFinZero Playground Agent", version=qfinzero_version())

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET", "PATCH", "DELETE"],
    allow_headers=["*"],
)

_store: Optional[Store] = None


def store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


def owner(request: Request) -> Optional[str]:
    return request.headers.get("x-qfz-user") or None


def _thread_or_404(request: Request, tid: str) -> dict:
    t = store().get_thread(tid, owner(request))
    if t is None:
        raise HTTPException(404, detail="conversation not found")
    return t


class Message(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class LLMFields(BaseModel):
    model: str
    base_url: str
    api_key: str
    proxy: str | None = None  # optional per-request LLM egress proxy; overrides server default
    api: str = "openai"  # openai | anthropic | antigravity (see providers.py)

    def llm(self) -> runner.LLMConfig:
        return runner.LLMConfig(api=self.api, model=self.model, base_url=self.base_url, api_key=self.api_key,
                                proxy=(self.proxy or LLM_PROXY) or None)


class ChatRequest(LLMFields):
    thread_id: str | None = None   # omitted: a new conversation
    messages: list[Message]        # only the latest user message is used; the history is stored
    as_of_date: str                # simulation time, UTC ISO
    context_tokens: int = ctx.DEFAULT_BUDGET
    auto_compact: bool = True


@app.get("/health")
async def health():
    return {"status": "ok", "service": "playground", "version": qfinzero_version()}


class TestConnectionRequest(BaseModel):
    base_url: str
    api_key: str
    proxy: str | None = None  # optional per-request LLM egress proxy; overrides server default
    api: str = "openai"


@app.post("/models")
async def provider_models(req: TestConnectionRequest):
    """The models a provider offers: ``{ok, models: [{id, name}]}`` or ``{ok: false, error}``."""
    if req.api not in API_TYPES:
        return {"ok": False, "error": f"unknown api type {req.api!r}"}
    try:
        models = await list_models(req.api, req.base_url, req.api_key, (req.proxy or LLM_PROXY) or None)
        return {"ok": True, "models": models}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/test-connection")
async def test_connection(req: TestConnectionRequest):
    """Test LLM provider connectivity through its model list."""
    r = await provider_models(req)
    return {"ok": r["ok"], **({"count": len(r["models"])} if r["ok"] else {"error": r["error"]})}


# ── threads ──────────────────────────────────────────────────────────────

class NewThread(BaseModel):
    title: str = ""


class ThreadPatch(BaseModel):
    title: str


def _summary(t: dict) -> dict:
    return {k: t.get(k) for k in ("id", "title", "created_at", "updated_at", "model", "as_of", "message_count")} | {
        "running": t["id"] in runner.RUNS}


@app.get("/threads")
async def list_threads(request: Request, q: str = "", limit: int = 200):
    return {"threads": [_summary(t) for t in store().list_threads(owner(request), q=q, limit=limit)]}


@app.post("/threads")
async def create_thread(request: Request, body: NewThread):
    return _summary(store().create_thread(owner(request), body.title.strip()) | {"message_count": 0})


@app.get("/threads/{tid}")
async def get_thread(request: Request, tid: str):
    t = _thread_or_404(request, tid)
    run = runner.RUNS.get(tid)
    return {"thread": _summary(t) | {"summary": t.get("summary"), "summary_through": t.get("summary_through")},
            "messages": store().messages(tid), "running": run is not None,
            "live": run.record if run else None}


@app.patch("/threads/{tid}")
async def rename_thread(request: Request, tid: str, body: ThreadPatch):
    _thread_or_404(request, tid)
    return _summary(store().update_thread(tid, owner(request), title=body.title.strip()[:200]))


@app.delete("/threads/{tid}")
async def delete_thread(request: Request, tid: str):
    _thread_or_404(request, tid)
    runner.interrupt(tid)
    store().delete_thread(tid, owner(request))
    return {"ok": True}


@app.post("/threads/{tid}/interrupt")
async def interrupt_thread(request: Request, tid: str):
    _thread_or_404(request, tid)
    run = runner.RUNS.get(tid)
    if not runner.interrupt(tid):
        return {"ok": False, "running": False}
    if run is not None:
        try:
            await asyncio.wait_for(run.done.wait(), timeout=10)
        except asyncio.TimeoutError:
            pass
    return {"ok": True}


@app.get("/threads/{tid}/context")
async def thread_context(request: Request, tid: str, budget: int = ctx.DEFAULT_BUDGET, as_of: str = ""):
    t = _thread_or_404(request, tid)
    prompt = build_system_prompt(as_of or t.get("as_of") or "")
    return ctx.usage(t, store().messages(tid), prompt, budget)


class CompactRequest(LLMFields):
    keep_turns: int = 1


@app.post("/threads/{tid}/compact")
async def compact_thread(request: Request, tid: str, body: CompactRequest):
    t = _thread_or_404(request, tid)
    if tid in runner.RUNS:
        raise HTTPException(409, detail="the conversation is answering; stop it first")
    messages = store().messages(tid)
    cut = ctx.compaction_cut(messages, t.get("summary_through", -1), keep_turns=max(0, body.keep_turns))
    if cut is None:
        return {"ok": False, "error": "nothing to compact yet"}
    cfg = body.llm()
    llm, http_client = runner.make_llm(cfg.api, cfg.model, cfg.base_url, cfg.api_key, cfg.proxy)
    try:
        folded = [m for m in messages if t.get("summary_through", -1) < m["seq"] <= cut]
        summary = await ctx.summarise(llm, t.get("summary"), folded)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        if http_client is not None:
            await http_client.aclose()
    store().update_thread(tid, owner(request), summary=summary, summary_through=cut)
    return {"ok": True, "compacted_messages": len(folded), "summary": summary}


@app.get("/threads/{tid}/export")
async def export_thread(request: Request, tid: str, tools: bool = True):
    t = _thread_or_404(request, tid)
    md = thread_markdown(t, store().messages(tid), tools=tools)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in (t.get("title") or tid))[:60].strip("-")
    return PlainTextResponse(md, media_type="text/markdown; charset=utf-8",
                             headers={"content-disposition": f'attachment; filename="{safe or tid}.md"'})


# ── chat ─────────────────────────────────────────────────────────────────

@app.post("/chat")
async def chat(request: Request, req: ChatRequest):
    user_message = next((m.content for m in reversed(req.messages) if m.role == "user"), "").strip()
    if not user_message:
        raise HTTPException(400, detail="empty message")
    who = owner(request)
    thread = store().get_thread(req.thread_id, who) if req.thread_id else None
    if thread is None:
        thread = store().create_thread(who, model=req.model, api=req.api, as_of=req.as_of_date)
    try:
        run, user = runner.start_turn(store(), thread, user_message, req.llm(), req.as_of_date,
                                      budget=max(4_000, req.context_tokens), auto_compact=req.auto_compact)
    except RuntimeError as e:
        raise HTTPException(409, detail=str(e))
    queue = run.subscribe()

    async def events() -> AsyncIterator[dict]:
        try:
            yield {"data": json.dumps({"type": "turn_start", "thread_id": thread["id"], "user": user,
                                       "message_id": run.record["id"]})}
            while True:
                ev = await queue.get()
                yield {"data": json.dumps(ev, default=str)}
                if ev["type"] in runner.TERMINAL:
                    break
        finally:
            # the page went away: the turn keeps running (stop it with /interrupt)
            run.unsubscribe(queue)

    return EventSourceResponse(events())


if __name__ == "__main__":
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
