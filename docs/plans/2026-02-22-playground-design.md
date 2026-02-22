# Playground Feature Design

**Date:** 2026-02-22
**Branch:** feat/data-platform-frontend
**Status:** Approved

---

## Overview

Add a **Playground** page to the QFinZero dashboard — a chatbot-style interface where users configure an LLM provider (model, API key, base URL), set an "as-of date" for historical context, and type natural language queries. The system invokes QFinZero tools (UPQ/NPP/PMB) via a LangGraph ReAct agent and streams both tool call details and the final answer back to the UI.

---

## Requirements

- User specifies LLM provider: model name, base URL, API key (any OpenAI-compatible endpoint)
- User sets an "as-of date"; all tool calls are bounded by this date (injected into system prompt)
- Natural language input → LangGraph agent → tool calls → streamed response
- UI shows: tool name called, input parameters, returned data (expandable JSON), and final LLM answer
- Multi-turn conversation within a session (history passed per request; agent is stateless)
- All 29 MCP tools available: UPQ (7), NPP (9), PMB (13)

---

## Architecture

```
Browser (Next.js /playground)
  └─ Config Panel + Chat UI
       │
       │ POST /api/playground/chat  (SSE, Next.js BFF)
       ▼
Next.js API Route  →  forwards SSE stream
       │
       │ POST http://localhost:19310/chat  (SSE)
       ▼
LangGraph Agent Service  (infra/playground/, Python FastAPI, port 19310)
  ├── ReAct agent loop (LangGraph)
  ├── LLM: user-configured provider via langchain init_chat_model
  ├── Tools: langchain-mcp-adapters MCPToolkit → mcp/server.py (stdio)
  └── SSE events: tool_start / tool_end / llm_chunk / done / error
```

---

## Backend: LangGraph Agent Service

**Location:** `infra/playground/`

### Files

```
infra/playground/
├── main.py          # FastAPI app, /chat SSE endpoint, /health
├── agent.py         # LangGraph ReAct agent, dynamic LLM init, as_of_date injection
├── mcp_tools.py     # MCPToolkit stdio connection to mcp/server.py
├── config.py        # Port, timeout, MCP server path constants
└── requirements.txt # langgraph, langchain-mcp-adapters, langchain-openai, fastapi, sse-starlette
```

### `/chat` Request/Response

**Request:**
```json
POST /chat
{
  "messages": [
    {"role": "user", "content": "Get AAPL closing price last week"}
  ],
  "model": "gpt-4o",
  "base_url": "https://api.openai.com/v1",
  "api_key": "sk-...",
  "as_of_date": "2025-01-15"
}
```

**SSE Stream Events:**
```
data: {"type": "tool_start", "tool": "upq_stock_daily", "input": {"tickers": ["AAPL"], "start": "2025-01-08", "end": "2025-01-15"}}
data: {"type": "tool_end",   "tool": "upq_stock_daily", "output": [{"date": "2025-01-15", "close": 185.2, ...}]}
data: {"type": "llm_chunk",  "content": "AAPL closed at $185.2 on Jan 15..."}
data: {"type": "done"}
```

### Agent Design

- **System prompt:** Includes `as_of_date` to instruct the agent to bound all tool queries to that date. E.g.: `"Today is {as_of_date}. Do not query data beyond this date."`
- **LLM init:** `langchain.chat_models.init_chat_model(model, base_url=..., api_key=...)` — supports any OpenAI-compatible provider
- **Tools:** `langchain-mcp-adapters` `MCPToolkit` connects to `mcp/server.py` via stdio, auto-loads all 29 tools
- **Agent loop:** `langgraph.prebuilt.create_react_agent` with streaming via `.astream_events()`
- **Stateless:** No server-side session state; full `messages` history passed in each request

---

## Frontend: Next.js Pages and Components

**Location:** `infra/dashboard-web/src/`

### New Files

```
app/playground/page.tsx
app/api/playground/chat/route.ts
components/playground/
├── playground-layout.tsx    # Left/right split layout
├── config-panel.tsx         # Model, base URL, API key, as-of date form
├── chat-panel.tsx           # Message list + SSE consumer + input box
├── message-bubble.tsx       # User / AI message rendering
└── tool-call-card.tsx       # Collapsible tool call card (reuses json-viewer.tsx)
```

### UI Layout

```
┌──────────────────────────────────────────────────────────┐
│  navbar  [Status] [News] [Calendar] [Sanity] [Playground]│
├────────────────┬─────────────────────────────────────────┤
│  Config        │  Chat                                   │
│                │                                         │
│  Model         │  [user] Get AAPL price last week        │
│  [gpt-4o    ▼] │                                         │
│                │  ┌─ tool: upq_stock_daily  ✓ ─────────┐ │
│  Base URL      │  │ ▶ input  {tickers:[AAPL],...}       │ │
│  [https://...] │  │ ▶ output [{date,close,...}]         │ │
│                │  └────────────────────────────────────┘ │
│  API Key       │                                         │
│  [sk-......  ] │  [AI] AAPL closed at $185.2 on Jan 15  │
│                │                                         │
│  As of Date    │  ─────────────────────────────────────  │
│  [2025-01-15]  │  [Type your question...]    [Send]      │
└────────────────┴─────────────────────────────────────────┘
```

### Tool Call Card Behavior

- Default: collapsed, shows tool name + status badge (loading / done / error)
- Expanded: input params (JSON) + output data (JSON), reusing existing `json-viewer.tsx`
- Error state: shows error message in red

### State Management

- Config values: `useState` in page component, persisted to `localStorage`
- Messages: `useState` array, appended as SSE events arrive
- SSE consumption: `EventSource` or `fetch` with `ReadableStream` in `chat-panel.tsx`

---

## Integration

### Environment Variables

```
# infra/dashboard-web/.env.local
PLAYGROUND_SERVICE_URL=http://localhost:19310
```

### Service Startup

Add `infra/playground/main.py` to `scripts/run_all.sh` alongside UPQ/NPP/PMB.

### Navbar

Add "Playground" entry to `components/navbar.tsx`.

---

## Task Breakdown for Parallel Implementation

### Track B: Backend (infra/playground/)

| ID | Task | Dependencies |
|----|------|--------------|
| B1 | Scaffold `infra/playground/` with `requirements.txt`, `config.py` | none |
| B2 | `mcp_tools.py`: MCPToolkit stdio connection to mcp/server.py | B1 |
| B3 | `agent.py`: LangGraph ReAct agent with dynamic LLM + as_of_date system prompt | B2 |
| B4 | `main.py`: FastAPI `/chat` SSE endpoint + `/health` | B3 |

### Track F: Frontend (infra/dashboard-web/)

| ID | Task | Dependencies |
|----|------|--------------|
| F1 | `app/api/playground/chat/route.ts`: BFF SSE proxy to backend | none |
| F2 | `config-panel.tsx`: model/url/key/date config form | none |
| F3 | `tool-call-card.tsx`: collapsible tool call display (json-viewer reuse) | none |
| F4 | `message-bubble.tsx` + `chat-panel.tsx`: message list + SSE consumer | F1, F2, F3 |
| F5 | `playground-layout.tsx` + `app/playground/page.tsx` + navbar entry | F4 |

### Track M: Integration

| ID | Task | Dependencies |
|----|------|--------------|
| M1 | `.env.local` update + startup script integration | B4, F5 |
| M2 | End-to-end smoke test: send query, verify tool calls stream correctly | M1 |

---

## Key Design Decisions

1. **LangGraph over raw LLM loop** — built-in streaming, ReAct pattern, easy to extend to multi-agent later
2. **MCP via stdio** — reuses existing `mcp/server.py` without any modification; no HTTP MCP transport needed
3. **Stateless agent** — full message history passed per request; simplifies backend, no session persistence
4. **As-of date via system prompt** — simplest reliable approach; constrains tool call date params via LLM instruction
5. **SSE streaming** — real-time tool call visibility; Next.js API route transparently proxies the stream
6. **Config in localStorage** — no auth system needed; user manages their own API keys client-side
