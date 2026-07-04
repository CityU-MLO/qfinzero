"""QFinZero unified server.

A single hub on ``QFZ_SERVER_PORT`` (default 19777) that is the ONE public entry
point for everything:

    /            Web UI            (proxied to the internal Next.js dashboard)
    /api/upq/*   market data       (proxied to the internal Rust UPQ engine)
    /api/esp/*   news & events      ┐
    /api/pmb/*   paper broker       ├ proxied to internal FastAPI services the
    /api/playground/*  chat agent   │ hub supervises on localhost
    /api/data-admin/*  data console ┘
    /mcp         MCP server         (mounted in-process)
    /health      aggregate health of the hub + all children

The hub supervises the per-service processes (they bind localhost only), so it's
one command and one public port. See ``app.py``.
"""

from __future__ import annotations

__all__ = ["app", "proxy", "supervisor"]
