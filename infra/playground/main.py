"""Playground Agent Service — FastAPI + SSE."""

import json
import sys
from pathlib import Path
from typing import AsyncIterator

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import HOST, PORT, LLM_PROXY
from agent import run_agent_stream
from qfinzero.runtime import qfinzero_version


app = FastAPI(title="QFinZero Playground Agent", version=qfinzero_version())

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


class Message(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    thread_id: str
    messages: list[Message]  # only the latest user message is used; kept for API compat
    model: str
    base_url: str
    api_key: str
    as_of_date: str  # "YYYY-MM-DD"
    proxy: str | None = None  # optional per-request LLM egress proxy; overrides server default


@app.get("/health")
async def health():
    return {"status": "ok", "service": "playground", "version": qfinzero_version()}


class TestConnectionRequest(BaseModel):
    base_url: str
    api_key: str
    proxy: str | None = None  # optional per-request LLM egress proxy; overrides server default


@app.post("/test-connection")
async def test_connection(req: TestConnectionRequest):
    """Test LLM provider connectivity by hitting the /models endpoint."""
    url = req.base_url.rstrip("/") + "/models"
    proxy = (req.proxy or LLM_PROXY) or None
    try:
        async with httpx.AsyncClient(timeout=10, proxy=proxy) as client:
            resp = await client.get(
                url, headers={"Authorization": f"Bearer {req.api_key}"}
            )
        if resp.status_code == 200:
            return {"ok": True}
        return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/chat")
async def chat(req: ChatRequest):
    async def event_generator() -> AsyncIterator[dict]:
        # Only the last user message is passed; full history is in the checkpointer
        user_message = next(
            (m.content for m in reversed(req.messages) if m.role == "user"), ""
        )
        async for event in run_agent_stream(
            thread_id=req.thread_id,
            user_message=user_message,
            model=req.model,
            base_url=req.base_url,
            api_key=req.api_key,
            as_of_date=req.as_of_date,
            proxy=(req.proxy or LLM_PROXY) or None,
        ):
            yield {"data": json.dumps(event)}

    return EventSourceResponse(event_generator())


if __name__ == "__main__":
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
