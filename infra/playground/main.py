"""Playground Agent Service — FastAPI + SSE."""

import json
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
import uvicorn

from config import HOST, PORT
from agent import run_agent_stream


app = FastAPI(title="QFinZero Playground Agent", version="0.1.0")

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


@app.get("/health")
async def health():
    return {"status": "ok", "service": "playground"}


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
        ):
            yield {"data": json.dumps(event)}

    return EventSourceResponse(event_generator())


if __name__ == "__main__":
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
