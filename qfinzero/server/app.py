"""The QFinZero hub — one FastAPI app on :19777 fronting everything."""

from __future__ import annotations

import importlib.util
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from qfinzero import config
from qfinzero.runtime import qfinzero_version
from .proxy import ReverseProxy
from . import supervisor as sup_mod
from .supervisor import (
    Supervisor, UPQ_IN, ESP_IN, PMB_IN, PLAYGROUND_IN, DATA_ADMIN_IN, DASHBOARD_IN,
)

log = logging.getLogger("qfz.server")

_PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]

# /api/<name>/* -> internal base URL
_ROUTES = {
    "upq": UPQ_IN, "esp": ESP_IN, "pmb": PMB_IN,
    "playground": PLAYGROUND_IN, "data-admin": DATA_ADMIN_IN,
}


def _load_mcp_app():
    """Import mcp/server.py in isolation (avoids the local-dir vs pip-pkg clash)
    and return its streamable-HTTP ASGI app, or None if unavailable."""
    repo_root = Path(config.__file__).resolve().parent.parent
    path = repo_root / "mcp" / "server.py"
    if not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("_qfz_mcp_server", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mcp = mod.mcp
        # serve the handler at the mount root so /mcp maps cleanly
        mcp.settings.streamable_http_path = "/"
        return mcp.streamable_http_app()
    except Exception as e:  # noqa: BLE001
        log.warning("MCP unavailable (%s); /mcp disabled", e)
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    import os
    app.state.proxy = ReverseProxy()
    supervise = os.getenv("QFZ_SUPERVISE", "1").lower() not in ("0", "false", "off")
    if supervise:
        app.state.supervisor = Supervisor()
        app.state.supervisor.start_all()
        started = [c.name for c in app.state.supervisor.children if c.enabled]
        log.info("supervised children: %s", ", ".join(started) or "(none)")
        health = app.state.supervisor.wait_healthy(timeout=40.0)
        for name, ok in health.items():
            log.info("  child %-12s %s", name, "healthy" if ok else "NOT healthy")
    else:
        # Pure-gateway mode: proxy to services managed externally (no spawn).
        app.state.supervisor = Supervisor(children=[])
        log.info("gateway mode (QFZ_SUPERVISE=0): proxying to external services")

    try:
        async with AsyncExitStack() as stack:
            mcp_app = app.state.mcp_app
            if mcp_app is not None:
                await stack.enter_async_context(mcp_app.router.lifespan_context(mcp_app))
            yield
    finally:
        await app.state.proxy.aclose()
        app.state.supervisor.stop_all()


def build_app() -> FastAPI:
    app = FastAPI(title="QFinZero", version=qfinzero_version(), lifespan=lifespan)

    # MCP mounted in-process (single clean module — no child needed).
    mcp_app = _load_mcp_app()
    app.state.mcp_app = mcp_app
    if mcp_app is not None:
        app.mount("/mcp", mcp_app)

        # Starlette's Mount only matches "/mcp/..."; make bare "/mcp" work too.
        @app.api_route("/mcp", methods=["GET", "POST"], include_in_schema=False)
        async def _mcp_bare():
            return RedirectResponse(url="/mcp/", status_code=307)

    # ── aggregate health ────────────────────────────────────────
    # actual health URLs of the internal services (works in supervise + gateway modes)
    _HEALTH = {
        "upq": f"{UPQ_IN}/health", "esp": f"{ESP_IN}/esp/health",
        "pmb": f"{PMB_IN}/v1/health", "playground": f"{PLAYGROUND_IN}/health",
        "data-admin": f"{DATA_ADMIN_IN}/health",
    }

    @app.get("/health")
    async def health(request: Request):
        proxy = request.app.state.proxy
        import asyncio
        names = list(_HEALTH)
        results = await asyncio.gather(*(proxy.probe(_HEALTH[n]) for n in names))
        children = {n: ("up" if ok else "down") for n, ok in zip(names, results)}
        children["mcp"] = "up" if request.app.state.mcp_app is not None else "off"
        status = "ok" if all(v == "up" for k, v in children.items() if k != "mcp") else "degraded"
        return {"status": status, "service": "qfinzero", "version": qfinzero_version(),
                "port": config.SERVER_PORT, "children": children}

    @app.get("/svc")
    async def svc_index():
        # Raw service REST gateway. NOTE: the web UI owns /api/* (its own Next.js
        # backend-for-frontend), so raw services live under /svc/* to avoid
        # clobbering the UI's routes.
        return {"services": sorted(f"/svc/{n}" for n in _ROUTES), "mcp": "/mcp",
                "ui": "/", "ui_api": "/api/* (served by the web UI)"}

    # ── raw service proxies: /svc/<name>/* -> internal service ──
    def _make(base: str):
        async def _proxy(request: Request, path: str = ""):
            return await request.app.state.proxy.forward(request, base, path)
        return _proxy

    for name, base in _ROUTES.items():
        fn = _make(base)
        app.add_api_route(f"/svc/{name}", fn, methods=_PROXY_METHODS, include_in_schema=False)
        app.add_api_route(f"/svc/{name}/{{path:path}}", fn, methods=_PROXY_METHODS,
                          include_in_schema=False)

    # ── Web UI: proxy to Next.js child, else a landing page ─────
    def _ui_enabled(app: FastAPI) -> bool:
        c = app.state.supervisor.child("dashboard") if hasattr(app.state, "supervisor") else None
        return bool(c and c.enabled)

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
                   include_in_schema=False)
    async def ui(request: Request, path: str = ""):
        if _ui_enabled(request.app):
            return await request.app.state.proxy.forward(request, DASHBOARD_IN, path)
        if path in ("", "/") and request.method == "GET":
            return HTMLResponse(_LANDING)
        return JSONResponse({"error": "web UI not running", "hint": "build infra/dashboard-web or set QFZ_SERVE_UI"}, status_code=503)

    return app


_LANDING = """<!doctype html><meta charset=utf-8><title>QFinZero</title>
<style>body{font:15px/1.6 system-ui;max-width:44rem;margin:4rem auto;padding:0 1rem}
code{background:#8881;padding:.1em .4em;border-radius:4px}a{color:#2563eb}</style>
<h1>QFinZero</h1><p>Unified server. One port for everything.</p>
<ul>
<li><a href=/health>/health</a> — hub + children status</li>
<li><a href=/api>/api</a> — REST index (<code>/api/upq</code>, <code>/api/esp</code>,
<code>/api/pmb</code>, <code>/api/playground</code>, <code>/api/data-admin</code>)</li>
<li><code>/mcp</code> — MCP server (streamable-HTTP)</li>
</ul>
<p>The web UI is not running. Build it: <code>cd infra/dashboard-web &amp;&amp; pnpm build</code>,
then restart (or set <code>QFZ_SERVE_UI=1</code>).</p>"""


app = build_app()
