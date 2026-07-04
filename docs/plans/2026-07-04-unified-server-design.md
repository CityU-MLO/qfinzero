# QFinZero Unified Server (:19777) — Design

**Date:** 2026-07-04
**Status:** Implemented (core validated)

## Goal

Collapse the multi-process, multi-port sprawl (7 services across 19300–19390 in
Rust + Node + Python) into **one server on one public port (19777)** that serves
the **Web UI**, the **REST API**, and the **MCP server**.

## Decision

**Hub + proxy** (chosen over full single-process). One FastAPI app on `:19777`:

- **Supervises** the individual services as localhost children (they no longer
  bind public ports). Rust UPQ and the Next.js dashboard stay as-is (child
  processes) — no rewrite, keeps UPQ's speed and the existing UI.
- **Reverse-proxies** `/api/<svc>/*` to each child (streaming, so SSE flows).
- **Mounts MCP in-process** at `/mcp` (single clean module — no child needed).
- One command (`scripts/serve.sh`), one port.

Why not true in-process merge of the Python services: they use bare top-level
imports with `sys.path` hacks (`from config import settings`; PMB ships its own
`clients/` package), so importing all four into one process collides on
`config`/`routes`/`services`/`clients`. Refactoring every service into a proper
package is a separate, higher-risk change — deferred.

## Layout

```
qfinzero/server/
  proxy.py       streaming reverse proxy (httpx; drops hop-by-hop; SSE passthrough)
  supervisor.py  Child registry; launch/health/stop; internal peer wiring
  app.py         hub FastAPI: combined lifespan (start children + run MCP session
                 manager), /api/* proxies, /mcp mount + bare-path redirect,
                 aggregate /health, UI proxy or landing page
  __main__.py    uvicorn entrypoint  (python -m qfinzero.server / qfz-server)
```

Public surface: `/` (UI), `/api/{upq,esp,pmb,playground,data-admin}/*`, `/mcp`,
`/health`, `/api` (index).

## Config

`qfinzero/config.py`: `QFZ_SERVER_HOST` (0.0.0.0), `QFZ_SERVER_PORT` (19777),
`SERVER_URL`. The 193xx service ports become **internal** children. Clients still
read `UPQ_URL`/`ESP_URL`/`PMB_URL` (internal) for in-cluster calls; external users
hit `:19777/api/*`.

**Modes:** `QFZ_SUPERVISE=0` = pure gateway (proxy to externally-managed
services); `QFZ_SERVE_UI=0` = skip the Next.js child (hub serves a landing page).

## Validation (2026-07-04)

Live on a free test port (19777 was occupied on the dev box by an unrelated app):

- `/health` → hub JSON with per-child status; `/api` index.
- `/api/upq/health`, `/api/esp/esp/health`, `/api/pmb/v1/health` → real responses
  proxied from the running Rust/Python services.
- `/mcp` and `/mcp/` → MCP `initialize` returns proper JSON-RPC (serverInfo
  "QFinZero"; tools/resources/prompts capabilities). Bare `/mcp` 307-redirects to
  `/mcp/` (Starlette `Mount` only matches the sub-path).
- `/` → landing page when UI is off; proxies to the Next.js child when on.

## Follow-ups

- Each supervised Python service needs its deps installed in the hub's
  interpreter (or run via its own venv) — otherwise that child crashes and the
  hub reports it `down` (hub stays up).
- Optional: true in-process merge (package-ify the services) to drop the Python
  child processes entirely.
- Point the Next.js dashboard's API routes at `/api/*` on the hub so the UI is
  fully same-origin.
