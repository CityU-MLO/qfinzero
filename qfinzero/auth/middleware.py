"""Hub authentication: an ASGI middleware in front of the UI, ``/svc``, ``/mcp``.

Pure ASGI (not ``BaseHTTPMiddleware``) so SSE streams and the mounted MCP app
pass through untouched. For every HTTP request it

1. strips any client-supplied ``x-qfz-user`` / ``x-qfz-role`` / ``x-qfz-user-id``,
2. identifies the caller from ``Authorization: Bearer qfz_...`` (or
   ``X-API-Key``) or the ``qfz_session`` cookie,
3. applies the access policy (:func:`required_role`),
4. injects the verified identity as headers for the services behind the hub.

Unauthenticated page loads are redirected to ``/login?next=...``; API calls get
``401``. ``QFZ_AUTH_MODE=off`` disables checks (local development): every
request then runs as ``local`` with the admin role.
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional
from urllib.parse import quote

from .store import ROLE_RANK, AuthStore, User, load_secret, read_session

COOKIE = "qfz_session"
IDENTITY_HEADERS = (b"x-qfz-user", b"x-qfz-role", b"x-qfz-user-id")

# Paths anyone may load (the public site, login, health, static assets).
PUBLIC_EXACT = {"/", "/login", "/setup", "/health", "/favicon.ico", "/robots.txt",
                "/auth/login", "/auth/logout", "/auth/status", "/auth/setup"}
PUBLIC_PREFIXES = ("/_next/", "/static/", "/brand/")
ADMIN_PREFIXES = ("/svc/data-admin", "/api/data-admin", "/auth/users", "/data", "/admin")
READ_METHODS = {"GET", "HEAD", "OPTIONS"}


def auth_mode() -> str:
    return os.environ.get("QFZ_AUTH_MODE", "required").strip().lower()


def required_role(method: str, path: str) -> Optional[str]:
    """Least role needed for ``method path``; ``None`` means public."""
    if path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES):
        return None
    if path.startswith(ADMIN_PREFIXES):
        return "admin"
    if path.startswith("/mcp"):
        return "researcher"                  # agents act (trade, research) through MCP
    if path.startswith("/auth/"):
        return "viewer"                      # own profile, own keys, password
    if method.upper() in READ_METHODS:
        return "viewer"
    return "researcher"                      # any write through /svc, /api or the UI


def _wants_html(headers: dict) -> bool:
    return "text/html" in headers.get(b"accept", b"").decode(errors="ignore")


class AuthMiddleware:
    def __init__(self, app, store_factory=None):
        self.app = app
        self._factory = store_factory or AuthStore
        self._store: AuthStore | None = None
        self._secret: bytes | None = None

    @property
    def store(self) -> AuthStore:
        if self._store is None:
            self._store = self._factory()
        return self._store

    @property
    def secret(self) -> bytes:
        if self._secret is None:
            self._secret = load_secret()
        return self._secret

    # identity
    def identify(self, headers: dict) -> tuple[Optional[User], str]:
        authz = headers.get(b"authorization", b"").decode(errors="ignore")
        token = ""
        if authz.lower().startswith("bearer "):
            token = authz[7:].strip()
        token = token or headers.get(b"x-api-key", b"").decode(errors="ignore").strip()
        if token:
            return self.store.verify_api_key(token), "api_key"
        cookie = headers.get(b"cookie", b"").decode(errors="ignore")
        for part in cookie.split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE and value:
                data = read_session(self.secret, value)
                if data:
                    user = self.store.get_user(int(data["u"]))
                    if user and not user.disabled and user.session_version == data.get("v"):
                        return user, "cookie"
        return None, ""

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        raw = [(k, v) for k, v in scope.get("headers", []) if k.lower() not in IDENTITY_HEADERS]
        headers = {k.lower(): v for k, v in raw}
        method = scope.get("method", "GET")
        path = scope.get("path", "/")

        if auth_mode() == "off":
            user = User(id=0, username="local", role="admin")
            via = "off"
        else:
            user, via = self.identify(headers)
            need = required_role(method, path)
            if need is not None:
                if user is None:
                    return await self._deny(scope, send, 401, "authentication required",
                                            headers, path)
                if ROLE_RANK.get(user.role, -1) < ROLE_RANK[need]:
                    return await self._deny(scope, send, 403, f"requires role {need}",
                                            headers, path)
                # CSRF: a cookie-authenticated write must come from our own origin
                if via == "cookie" and method.upper() not in READ_METHODS:
                    origin = headers.get(b"origin", b"").decode(errors="ignore")
                    host = headers.get(b"host", b"").decode(errors="ignore")
                    if origin and origin.split("://", 1)[-1] != host:
                        return await self._deny(scope, send, 403, "cross-origin request refused",
                                                headers, path)
        if user is not None:
            raw += [(b"x-qfz-user", user.username.encode()),
                    (b"x-qfz-role", user.role.encode()),
                    (b"x-qfz-user-id", str(user.id).encode())]
            scope = dict(scope, headers=raw)
            scope.setdefault("state", {})
            scope["state"] = {**scope["state"], "user": user, "auth_via": via}
        else:
            scope = dict(scope, headers=raw)
        return await self.app(scope, receive, send)

    async def _deny(self, scope, send, status: int, message: str, headers: dict, path: str):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401 if status == 401 else 4403})
            return
        if status == 401 and scope.get("method") == "GET" and _wants_html(headers):
            qs = scope.get("query_string", b"").decode()
            nxt = quote(path + (f"?{qs}" if qs else ""), safe="")
            await send({"type": "http.response.start", "status": 302,
                        "headers": [(b"location", f"/login?next={nxt}".encode()),
                                    (b"cache-control", b"no-store")]})
            await send({"type": "http.response.body", "body": b""})
            return
        body = json.dumps({"error": message, "status": status}).encode()
        hdrs = [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]
        if status == 401:
            hdrs.append((b"www-authenticate", b'Bearer realm="qfinzero"'))
        await send({"type": "http.response.start", "status": status, "headers": hdrs})
        await send({"type": "http.response.body", "body": body})


class LoginThrottle:
    """At most 5 failures per (client, username) per 5 minutes."""

    def __init__(self, limit: int = 5, window_s: int = 300):
        self.limit, self.window = limit, window_s
        self._fails: dict[tuple[str, str], list[float]] = {}

    def blocked(self, client: str, username: str) -> bool:
        now = time.time()
        k = (client, username.lower())
        self._fails[k] = [t for t in self._fails.get(k, []) if now - t < self.window]
        return len(self._fails[k]) >= self.limit

    def fail(self, client: str, username: str) -> None:
        self._fails.setdefault((client, username.lower()), []).append(time.time())

    def ok(self, client: str, username: str) -> None:
        self._fails.pop((client, username.lower()), None)
