# Playground Feature Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Playground page to the QFinZero dashboard — a chatbot UI where users configure an LLM provider, set an as-of date, type natural language queries, and watch a LangGraph ReAct agent invoke QFinZero tools (UPQ/ESP/PMB via MCP) in real time.

**Architecture:** A new Python FastAPI service (`infra/playground/`, port 19310) runs a LangGraph ReAct agent that connects to `mcp/server.py` via stdio to load all 29 QFinZero tools. The Next.js dashboard adds a `/playground` page with a config panel (model/URL/key/date) and a streaming chat UI. The Next.js BFF proxies SSE from the Python service to the browser.

**Tech Stack:** Python 3.10+, LangGraph, langchain-mcp-adapters, FastAPI, sse-starlette; Next.js 15, React 19, TypeScript, TanStack Query, Tailwind, shadcn/ui.

---

## Parallel Execution Strategy

This plan is split into **3 independent tracks** that can be worked in parallel by separate agents:

- **Track B (Backend):** `infra/playground/` — Python FastAPI + LangGraph service. No frontend dependency.
- **Track F (Frontend):** `infra/dashboard-web/` — Next.js components + BFF route. No backend dependency during development (mock SSE).
- **Track M (Integration):** Ties tracks together after both complete.

Agents should each work in their own worktree branch off `feat/data-platform-frontend`.

---

## Track B: Backend — LangGraph Agent Service

### Task B1: Scaffold infra/playground/

**Files:**
- Create: `infra/playground/requirements.txt`
- Create: `infra/playground/config.py`

**Step 1: Create requirements.txt**

```
langgraph>=0.2.0
langchain>=0.3.0
langchain-openai>=0.2.0
langchain-mcp-adapters>=0.1.0
fastapi>=0.115.0
sse-starlette>=2.1.0
uvicorn>=0.32.0
pydantic>=2.0.0
```

**Step 2: Create config.py**

```python
import os
from pathlib import Path

PORT = int(os.environ.get("PLAYGROUND_PORT", "19310"))
HOST = os.environ.get("PLAYGROUND_HOST", "0.0.0.0")

# Path to mcp/server.py relative to project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
MCP_SERVER_PATH = str(PROJECT_ROOT / "mcp" / "server.py")

# Backend service URLs (passed to MCP server via env)
UPQ_URL = os.environ.get("QFINZERO_UPQ_URL", "http://127.0.0.1:19703")
ESP_URL = os.environ.get("QFINZERO_ESP_URL", "http://127.0.0.1:19702")
PMB_URL = os.environ.get("QFINZERO_PMB_URL", "http://127.0.0.1:19701")

REQUEST_TIMEOUT_S = int(os.environ.get("PLAYGROUND_TIMEOUT_S", "120"))
```

**Step 3: Install dependencies**

```bash
pip install -r infra/playground/requirements.txt
```

**Step 4: Verify import**

```bash
python -c "import langgraph; import langchain_mcp_adapters; import fastapi; print('OK')"
```
Expected: `OK`

**Step 5: Commit**

```bash
git add infra/playground/requirements.txt infra/playground/config.py
git commit -m "feat(playground): scaffold backend service with config and requirements"
```

---

### Task B2: mcp_tools.py — Load tools from mcp/server.py via stdio

**Files:**
- Create: `infra/playground/mcp_tools.py`

**Context:** `langchain-mcp-adapters` provides `MCPToolkit` which connects to an MCP server via stdio and converts its tools to LangChain-compatible tools. The MCP server is `mcp/server.py` at project root.

**Step 1: Create mcp_tools.py**

```python
"""Load QFinZero MCP tools via stdio connection to mcp/server.py."""

import sys
from langchain_mcp_adapters.tools import MCPToolkit
from mcp import StdioServerParameters
from config import MCP_SERVER_PATH, UPQ_URL, ESP_URL, PMB_URL


def get_mcp_server_params() -> StdioServerParameters:
    """Build stdio params to launch mcp/server.py as a subprocess."""
    return StdioServerParameters(
        command=sys.executable,
        args=[MCP_SERVER_PATH],
        env={
            "QFINZERO_UPQ_URL": UPQ_URL,
            "QFINZERO_ESP_URL": ESP_URL,
            "QFINZERO_PMB_URL": PMB_URL,
        },
    )


async def load_tools() -> list:
    """Connect to mcp/server.py and return all tools as LangChain tools."""
    params = get_mcp_server_params()
    toolkit = MCPToolkit(server_params=params)
    await toolkit.initialize()
    return toolkit.get_tools()
```

**Step 2: Smoke test (requires mcp/server.py reachable)**

```bash
cd infra/playground
python -c "
import asyncio
from mcp_tools import load_tools

async def main():
    tools = await load_tools()
    print(f'Loaded {len(tools)} tools')
    print([t.name for t in tools[:5]])

asyncio.run(main())
"
```
Expected: `Loaded 29 tools` (or close to it) with tool names like `upq_stock_daily`, `esp_query_events`, etc.

**Step 3: Commit**

```bash
git add infra/playground/mcp_tools.py
git commit -m "feat(playground): load MCP tools from mcp/server.py via stdio"
```

---

### Task B3: agent.py — LangGraph ReAct agent

**Files:**
- Create: `infra/playground/agent.py`

**Context:** `langgraph.prebuilt.create_react_agent` builds a ReAct loop. We use `.astream_events()` to get fine-grained streaming events (tool_start, tool_end, llm token chunks). The LLM is initialized dynamically per-request using `langchain.chat_models.init_chat_model` which supports any OpenAI-compatible endpoint.

**Step 1: Create agent.py**

```python
"""LangGraph ReAct agent with dynamic LLM and MCP tools."""

from typing import AsyncIterator
import json

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage
from langgraph.prebuilt import create_react_agent

from mcp_tools import load_tools


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
        # Load tools fresh per request (MCP server is stateless)
        tools = await load_tools()

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
                yield {
                    "type": "tool_start",
                    "tool": event["name"],
                    "input": event.get("data", {}).get("input", {}),
                }

            elif kind == "on_tool_end":
                raw_output = event.get("data", {}).get("output", "")
                # Tool output is JSON string from mcp/server.py
                try:
                    output = json.loads(raw_output) if isinstance(raw_output, str) else raw_output
                except Exception:
                    output = raw_output
                yield {
                    "type": "tool_end",
                    "tool": event["name"],
                    "output": output,
                }

            elif kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield {"type": "llm_chunk", "content": chunk.content}

        yield {"type": "done"}

    except Exception as e:
        yield {"type": "error", "message": str(e)}
```

**Step 2: Verify import**

```bash
cd infra/playground
python -c "from agent import run_agent_stream; print('OK')"
```
Expected: `OK`

**Step 3: Commit**

```bash
git add infra/playground/agent.py
git commit -m "feat(playground): LangGraph ReAct agent with streaming tool call events"
```

---

### Task B4: main.py — FastAPI SSE endpoint

**Files:**
- Create: `infra/playground/main.py`

**Step 1: Create main.py**

```python
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
    messages: list[Message]
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
        raw_messages = [{"role": m.role, "content": m.content} for m in req.messages]
        async for event in run_agent_stream(
            messages=raw_messages,
            model=req.model,
            base_url=req.base_url,
            api_key=req.api_key,
            as_of_date=req.as_of_date,
        ):
            yield {"data": json.dumps(event)}

    return EventSourceResponse(event_generator())


if __name__ == "__main__":
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
```

**Step 2: Start service**

```bash
cd infra/playground
python main.py
```
Expected: `Uvicorn running on http://0.0.0.0:19310`

**Step 3: Test health endpoint**

```bash
curl http://localhost:19310/health
```
Expected: `{"status":"ok","service":"playground"}`

**Step 4: Test chat endpoint (curl SSE)**

```bash
curl -N -X POST http://localhost:19310/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Check UPQ health"}],
    "model": "gpt-4o-mini",
    "base_url": "https://api.openai.com/v1",
    "api_key": "YOUR_KEY",
    "as_of_date": "2025-01-15"
  }'
```
Expected: SSE stream with `tool_start`, `tool_end`, `llm_chunk`, `done` events.

**Step 5: Commit**

```bash
git add infra/playground/main.py
git commit -m "feat(playground): FastAPI SSE /chat endpoint for agent service"
```

---

## Track F: Frontend — Next.js Playground UI

### Task F1: BFF SSE proxy route

**Files:**
- Create: `infra/dashboard-web/src/app/api/playground/chat/route.ts`
- Modify: `infra/dashboard-web/.env.local` (add one line)

**Step 1: Add env var to .env.local**

Add to the end of `infra/dashboard-web/.env.local`:
```
PLAYGROUND_SERVICE_URL=http://localhost:19310
```

**Step 2: Create the API route**

```typescript
// infra/dashboard-web/src/app/api/playground/chat/route.ts
import { NextRequest } from "next/server";

const PLAYGROUND_URL =
  process.env.PLAYGROUND_SERVICE_URL ?? "http://localhost:19310";

export async function POST(request: NextRequest) {
  const body = await request.text();

  const upstream = await fetch(`${PLAYGROUND_URL}/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body,
    // @ts-expect-error: Node fetch duplex
    duplex: "half",
  });

  if (!upstream.ok || !upstream.body) {
    return new Response(
      JSON.stringify({ error: `upstream ${upstream.status}` }),
      { status: 502, headers: { "content-type": "application/json" } }
    );
  }

  return new Response(upstream.body, {
    status: 200,
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-cache",
      connection: "keep-alive",
    },
  });
}
```

**Step 3: Verify it builds**

```bash
cd infra/dashboard-web
npm run typecheck
```
Expected: No errors.

**Step 4: Commit**

```bash
git add src/app/api/playground/chat/route.ts .env.local
git commit -m "feat(playground): add BFF SSE proxy route to agent service"
```

---

### Task F2: config-panel.tsx

**Files:**
- Create: `infra/dashboard-web/src/components/playground/config-panel.tsx`

**Context:** Uses shadcn/ui `Input`, `Label`, `Button` (already in `components/ui/`). Persists config to localStorage.

**Step 1: Create config-panel.tsx**

```typescript
"use client";

import { useEffect } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export interface PlaygroundConfig {
  model: string;
  baseUrl: string;
  apiKey: string;
  asOfDate: string;
}

const STORAGE_KEY = "playground_config";

const DEFAULT_CONFIG: PlaygroundConfig = {
  model: "gpt-4o-mini",
  baseUrl: "https://api.openai.com/v1",
  apiKey: "",
  asOfDate: new Date().toISOString().slice(0, 10),
};

export function loadConfig(): PlaygroundConfig {
  if (typeof window === "undefined") return DEFAULT_CONFIG;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? { ...DEFAULT_CONFIG, ...JSON.parse(raw) } : DEFAULT_CONFIG;
  } catch {
    return DEFAULT_CONFIG;
  }
}

export function saveConfig(config: PlaygroundConfig) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
}

interface ConfigPanelProps {
  config: PlaygroundConfig;
  onChange: (config: PlaygroundConfig) => void;
  disabled?: boolean;
}

export function ConfigPanel({ config, onChange, disabled }: ConfigPanelProps) {
  function set(key: keyof PlaygroundConfig, value: string) {
    const next = { ...config, [key]: value };
    onChange(next);
    saveConfig(next);
  }

  return (
    <aside className="flex flex-col gap-5 p-5 border-r min-w-[240px] max-w-[280px] bg-white/60 rounded-l-2xl">
      <div>
        <h2 className="text-xs font-bold uppercase tracking-widest text-muted-foreground mb-3">
          LLM Config
        </h2>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <Label htmlFor="model" className="text-xs">Model</Label>
            <Input
              id="model"
              value={config.model}
              onChange={(e) => set("model", e.target.value)}
              placeholder="gpt-4o-mini"
              disabled={disabled}
              className="text-sm h-8"
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="baseUrl" className="text-xs">Base URL</Label>
            <Input
              id="baseUrl"
              value={config.baseUrl}
              onChange={(e) => set("baseUrl", e.target.value)}
              placeholder="https://api.openai.com/v1"
              disabled={disabled}
              className="text-sm h-8"
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="apiKey" className="text-xs">API Key</Label>
            <Input
              id="apiKey"
              type="password"
              value={config.apiKey}
              onChange={(e) => set("apiKey", e.target.value)}
              placeholder="sk-..."
              disabled={disabled}
              className="text-sm h-8"
            />
          </div>
        </div>
      </div>

      <div>
        <h2 className="text-xs font-bold uppercase tracking-widest text-muted-foreground mb-3">
          Context
        </h2>
        <div className="flex flex-col gap-1">
          <Label htmlFor="asOfDate" className="text-xs">As of Date</Label>
          <Input
            id="asOfDate"
            type="date"
            value={config.asOfDate}
            onChange={(e) => set("asOfDate", e.target.value)}
            disabled={disabled}
            className="text-sm h-8"
          />
        </div>
      </div>
    </aside>
  );
}
```

**Step 2: Verify**

```bash
cd infra/dashboard-web && npm run typecheck
```
Expected: No errors.

**Step 3: Commit**

```bash
git add src/components/playground/config-panel.tsx
git commit -m "feat(playground): config panel with model/url/key/date fields"
```

---

### Task F3: tool-call-card.tsx

**Files:**
- Create: `infra/dashboard-web/src/components/playground/tool-call-card.tsx`

**Context:** Reuses existing `JsonViewer` from `@/components/news/json-viewer`. Shows tool name, status badge, collapsible input/output.

**Step 1: Create tool-call-card.tsx**

```typescript
"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { JsonViewer } from "@/components/news/json-viewer";

export type ToolCallStatus = "loading" | "done" | "error";

export interface ToolCallData {
  id: string;
  tool: string;
  input?: Record<string, unknown>;
  output?: unknown;
  error?: string;
  status: ToolCallStatus;
}

interface ToolCallCardProps {
  call: ToolCallData;
}

export function ToolCallCard({ call }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false);

  const statusIcon = {
    loading: <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-500" />,
    done: <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />,
    error: <XCircle className="h-3.5 w-3.5 text-rose-500" />,
  }[call.status];

  const chevron = expanded
    ? <ChevronDown className="h-3 w-3 text-muted-foreground" />
    : <ChevronRight className="h-3 w-3 text-muted-foreground" />;

  return (
    <div className="rounded-lg border bg-zinc-50 text-sm overflow-hidden">
      <button
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-zinc-100 transition-colors text-left"
        onClick={() => setExpanded(!expanded)}
      >
        {statusIcon}
        <span className="font-mono text-xs font-semibold text-zinc-700 flex-1">{call.tool}</span>
        {chevron}
      </button>

      {expanded && (
        <div className="px-3 pb-3 flex flex-col gap-2">
          {call.input && (
            <JsonViewer data={call.input} title="Input" />
          )}
          {call.output !== undefined && (
            <JsonViewer data={call.output} title="Output" />
          )}
          {call.error && (
            <p className="text-xs text-rose-500 font-mono">{call.error}</p>
          )}
        </div>
      )}
    </div>
  );
}
```

**Step 2: Verify**

```bash
cd infra/dashboard-web && npm run typecheck
```
Expected: No errors.

**Step 3: Commit**

```bash
git add src/components/playground/tool-call-card.tsx
git commit -m "feat(playground): tool call card with collapsible JSON input/output"
```

---

### Task F4: message-bubble.tsx + chat-panel.tsx

**Files:**
- Create: `infra/dashboard-web/src/components/playground/message-bubble.tsx`
- Create: `infra/dashboard-web/src/components/playground/chat-panel.tsx`

**Context:** `chat-panel.tsx` consumes SSE from `/api/playground/chat` using the Fetch API + `ReadableStream`. Each SSE event is parsed as JSON and updates the message/tool-call state. The `textarea` sends on Enter (not Shift+Enter).

**Step 1: Create message-bubble.tsx**

```typescript
"use client";

import { cn } from "@/lib/utils";
import { ToolCallCard, ToolCallData } from "./tool-call-card";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolCalls?: ToolCallData[];
}

interface MessageBubbleProps {
  message: ChatMessage;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div className={cn("flex flex-col gap-2", isUser ? "items-end" : "items-start")}>
      {/* Tool calls (assistant only, shown above text) */}
      {!isUser && message.toolCalls && message.toolCalls.length > 0 && (
        <div className="flex flex-col gap-1.5 w-full max-w-[90%]">
          {message.toolCalls.map((call) => (
            <ToolCallCard key={call.id} call={call} />
          ))}
        </div>
      )}

      {/* Message text */}
      {message.content && (
        <div
          className={cn(
            "rounded-2xl px-4 py-2.5 text-sm max-w-[90%] leading-relaxed",
            isUser
              ? "bg-primary text-primary-foreground rounded-br-sm"
              : "bg-white border text-foreground rounded-bl-sm"
          )}
        >
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>
      )}
    </div>
  );
}
```

**Step 2: Create chat-panel.tsx**

```typescript
"use client";

import { useRef, useState, useEffect, useCallback } from "react";
import { Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { PlaygroundConfig } from "./config-panel";
import { MessageBubble, ChatMessage } from "./message-bubble";
import { ToolCallData } from "./tool-call-card";

interface ChatPanelProps {
  config: PlaygroundConfig;
}

function makeId() {
  return Math.random().toString(36).slice(2);
}

export function ChatPanel({ config }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;

    setInput("");
    setStreaming(true);

    // Add user message
    const userMsg: ChatMessage = { id: makeId(), role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);

    // Add empty assistant message placeholder
    const assistantId = makeId();
    const assistantMsg: ChatMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      toolCalls: [],
    };
    setMessages((prev) => [...prev, assistantMsg]);

    // Build history for request (all prior messages except the new placeholder)
    const history = [...messages, userMsg].map((m) => ({
      role: m.role,
      content: m.content,
    }));

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch("/api/playground/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          messages: history,
          model: config.model,
          base_url: config.baseUrl,
          api_key: config.apiKey,
          as_of_date: config.asOfDate,
        }),
        signal: controller.signal,
      });

      if (!res.ok || !res.body) {
        throw new Error(`HTTP ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      // Track active tool call id for pairing start/end
      const toolCallMap: Record<string, ToolCallData> = {};

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim();
          if (!raw) continue;

          let event: Record<string, unknown>;
          try {
            event = JSON.parse(raw);
          } catch {
            continue;
          }

          const type = event.type as string;

          if (type === "tool_start") {
            const callId = makeId();
            const call: ToolCallData = {
              id: callId,
              tool: event.tool as string,
              input: event.input as Record<string, unknown>,
              status: "loading",
            };
            toolCallMap[event.tool as string] = call;
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, toolCalls: [...(m.toolCalls ?? []), call] }
                  : m
              )
            );
          } else if (type === "tool_end") {
            const toolName = event.tool as string;
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? {
                      ...m,
                      toolCalls: (m.toolCalls ?? []).map((c) =>
                        c.tool === toolName
                          ? { ...c, output: event.output, status: "done" as const }
                          : c
                      ),
                    }
                  : m
              )
            );
          } else if (type === "llm_chunk") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, content: m.content + (event.content as string) }
                  : m
              )
            );
          } else if (type === "error") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, content: `Error: ${event.message as string}` }
                  : m
              )
            );
          }
          // "done" event: nothing to do, streaming will end
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, content: `Connection error: ${(err as Error).message}` }
              : m
          )
        );
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }, [input, streaming, messages, config]);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage();
    }
  }

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-4">
        {messages.length === 0 && (
          <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
            Ask anything about market data, news, or trading...
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t p-3 flex gap-2 items-end bg-white/80">
        <Textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type your question... (Enter to send, Shift+Enter for newline)"
          className="resize-none text-sm min-h-[40px] max-h-[120px]"
          rows={1}
          disabled={streaming}
        />
        <Button
          onClick={() => void sendMessage()}
          disabled={streaming || !input.trim()}
          size="icon"
          className="shrink-0 h-10 w-10"
        >
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
```

**Step 3: Verify**

```bash
cd infra/dashboard-web && npm run typecheck
```
Expected: No errors.

**Step 4: Commit**

```bash
git add src/components/playground/message-bubble.tsx src/components/playground/chat-panel.tsx
git commit -m "feat(playground): message bubble and streaming chat panel with SSE consumer"
```

---

### Task F5: Page, layout, navbar

**Files:**
- Create: `infra/dashboard-web/src/components/playground/playground-layout.tsx`
- Create: `infra/dashboard-web/src/app/playground/page.tsx`
- Modify: `infra/dashboard-web/src/components/navbar.tsx`

**Step 1: Create playground-layout.tsx**

```typescript
"use client";

import { useState } from "react";
import { ConfigPanel, PlaygroundConfig, loadConfig } from "./config-panel";
import { ChatPanel } from "./chat-panel";

export function PlaygroundLayout() {
  const [config, setConfig] = useState<PlaygroundConfig>(loadConfig);

  return (
    <div className="flex flex-1 min-h-0 rounded-2xl border bg-white/80 shadow-sm overflow-hidden">
      <ConfigPanel config={config} onChange={setConfig} />
      <ChatPanel config={config} />
    </div>
  );
}
```

**Step 2: Create app/playground/page.tsx**

```typescript
import { PlaygroundLayout } from "@/components/playground/playground-layout";

export default function PlaygroundPage() {
  return (
    <div className="flex flex-col h-[calc(100vh-6rem)]">
      <PlaygroundLayout />
    </div>
  );
}
```

**Step 3: Add Playground to navbar**

In `infra/dashboard-web/src/components/navbar.tsx`, update `NAV_ITEMS`:

```typescript
const NAV_ITEMS = [
  { href: "/", label: "Status" },
  { href: "/news", label: "News Browser" },
  { href: "/calendar", label: "Calendar Browser" },
  { href: "/sanity", label: "Sanity Checks" },
  { href: "/playground", label: "Playground" },
];
```

**Step 4: Verify and run dev**

```bash
cd infra/dashboard-web
npm run typecheck
npm run dev
```
Expected: No type errors. Visit `http://localhost:3000/playground` — config panel on left, empty chat on right.

**Step 5: Commit**

```bash
git add src/components/playground/playground-layout.tsx \
        src/app/playground/page.tsx \
        src/components/navbar.tsx
git commit -m "feat(playground): playground page, layout, and navbar entry"
```

---

## Track M: Integration

### Task M1: Wire up and smoke test

**Prerequisites:** Track B (B4 done, service running on 19310) + Track F (F5 done, dashboard running)

**Step 1: Start all services**

In separate terminals:
```bash
# Terminal 1: QFinZero backend services (UPQ/ESP/PMB)
bash scripts/run_all.sh

# Terminal 2: Playground agent service
cd infra/playground && python main.py

# Terminal 3: Dashboard
cd infra/dashboard-web && npm run dev
```

**Step 2: Verify playground health**

```bash
curl http://localhost:19310/health
```
Expected: `{"status":"ok","service":"playground"}`

**Step 3: Open browser**

Navigate to `http://localhost:3000/playground`.

Fill in:
- Model: `gpt-4o-mini` (or your available model)
- Base URL: `https://api.openai.com/v1`
- API Key: your key
- As of Date: `2025-01-15`

**Step 4: Send a test query**

Type: `Check UPQ service health`

Expected behavior:
1. Tool call card appears: `upq_health` with loading spinner
2. Card updates to done, output JSON visible when expanded
3. LLM response streams in below the tool card

**Step 5: Send a data query**

Type: `What was AAPL's closing price on January 10th, 2025?`

Expected:
1. `upq_stock_daily` tool card appears with `tickers: ["AAPL"]`, date bounded by as_of_date
2. Output shows daily bar data
3. LLM summarizes the price

**Step 6: Commit integration**

```bash
git add .
git commit -m "feat(playground): complete playground integration - backend + frontend wired"
```

---

## Notes for Agent Parallel Execution

**Track B agent** works in `infra/playground/` only. Never touches `infra/dashboard-web/`.

**Track F agent** works in `infra/dashboard-web/src/` only. Never touches `infra/playground/`. For F1-F3, no running backend needed. For F4-F5, use `npm run dev` to visually verify layout (chat will show connection error without backend — that's expected).

**Track M agent** runs after both B and F tracks report completion. Its job is to wire up and do end-to-end verification.

**Merge order:** B merges first → F merges second (resolve any conflicts in `.env.local`) → M does final smoke test commit.
