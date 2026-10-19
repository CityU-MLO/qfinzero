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
import threading
import time
from typing import Optional
from urllib.parse import quote

from .store import ROLE_RANK, AuthStore, User, key_allows, load_secret, mcp_tool_allows, read_session

COOKIE = "qfz_session"
IDENTITY_HEADERS = (b"x-qfz-user", b"x-qfz-role", b"x-qfz-user-id")

# Paths anyone may load (the public site, the documentation, login, health,
# static assets). The docs are the repository's own markdown, already public.
PUBLIC_EXACT = {"/", "/login", "/setup", "/health", "/favicon.ico", "/robots.txt", "/docs",
                "/api/docs", "/auth/login", "/auth/logout", "/auth/status", "/auth/setup", "/auth/me"}
PUBLIC_PREFIXES = ("/_next/", "/static/", "/brand/", "/docs/")
ADMIN_PREFIXES = ("/svc/data-admin", "/api/data-admin", "/auth/users", "/data", "/admin")
READ_METHODS = {"GET", "HEAD", "OPTIONS"}
# services whose POSTs are queries (JSON bodies), open to viewers
QUERY_PREFIXES = ("/svc/esp", "/api/esp", "/svc/upq", "/api/upq")


def auth_mode() -> str:
    return os.environ.get("QFZ_AUTH_MODE", "required").strip().lower()


def required_role(method: str, path: str) -> Optional[str]:
    """Least role needed for ``method path``; ``None`` means public."""
    if path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES):
        if path.startswith(("/docs", "/api/docs")) and method.upper() not in READ_METHODS:
            return "viewer"                  # the docs are public to read only
        return None
    if path.startswith(ADMIN_PREFIXES):
        return "admin"
    if path.startswith("/mcp"):
        return "researcher"                  # agents act (trade, research) through MCP
    if path.startswith("/auth/"):
        return "viewer"                      # own profile, own keys, password
    if method.upper() in READ_METHODS or path.startswith(QUERY_PREFIXES):
        return "viewer"
    return "researcher"                      # any write through /svc, /api or the UI


class KeyMeter:
    """Per-key request counting and rate limiting, in memory.

    A sliding one-minute window per key enforces ``rate_per_min``; counts are
    added to the store's daily usage table at most every ``flush_s`` seconds
    (and when :meth:`flush` is called), so a busy key costs no write per call."""

    def __init__(self, store_getter, flush_s: float = 30.0):
        self._store = store_getter
        self._flush_s = flush_s
        self._lock = threading.Lock()
        self._hits: dict[int, list[float]] = {}
        self._pending: dict[tuple[int, str], list[int]] = {}
        self._last = time.time()

    def allow(self, key_id: int, rate_per_min: Optional[int]) -> tuple[bool, int]:
        """``(allowed, seconds until a slot frees)``; records the request."""
        now = time.time()
        with self._lock:
            ok, wait = True, 0
            if rate_per_min:
                hits = [t for t in self._hits.get(key_id, []) if now - t < 60]
                if len(hits) >= rate_per_min:
                    ok, wait = False, max(1, int(60 - (now - hits[0])) + 1)
                else:
                    hits.append(now)
                self._hits[key_id] = hits
            self._count(key_id, now, denied=not ok)
        self._maybe_flush(now)
        return ok, wait

    def deny(self, key_id: int) -> None:
        with self._lock:
            self._count(key_id, time.time(), denied=True)

    def _count(self, key_id: int, now: float, denied: bool) -> None:
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        c = self._pending.setdefault((key_id, day), [0, 0])
        c[0] += 1
        c[1] += int(denied)

    def _maybe_flush(self, now: float) -> None:
        if now - self._last >= self._flush_s:
            self.flush()

    def flush(self) -> None:
        with self._lock:
            pending, self._pending = self._pending, {}
            self._last = time.time()
        try:
            self._store().add_usage(pending)
        except Exception:  # noqa: BLE001 — usage is best effort; never fail a request on it
            pass


async def _buffer(receive):
    """Read a request body and return it with a ``receive`` that replays it."""
    chunks, more = [], True
    while more:
        msg = await receive()
        if msg["type"] != "http.request":
            break
        chunks.append(msg.get("body", b""))
        more = msg.get("more_body", False)
    body = b"".join(chunks)
    sent = False

    async def replay():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    return body, replay


def _mcp_denied(body: bytes, key: dict) -> Optional[str]:
    """Check every ``tools/call`` in a JSON-RPC message (or batch) against the key."""
    try:
        msg = json.loads(body or b"null")
    except ValueError:
        return None                       # not ours to judge; the MCP app answers
    for m in msg if isinstance(msg, list) else [msg]:
        if isinstance(m, dict) and m.get("method") == "tools/call":
            tool = str((m.get("params") or {}).get("name", ""))
            why = mcp_tool_allows(key["scopes"], key["read_only"], tool)
            if why:
                return why
    return None


def _wants_html(headers: dict) -> bool:
    return "text/html" in headers.get(b"accept", b"").decode(errors="ignore")


class AuthMiddleware:
    def __init__(self, app, store_factory=None):
        self.app = app
        self._factory = store_factory or AuthStore
        self._store: AuthStore | None = None
        self._secret: bytes | None = None
        self.meter = KeyMeter(lambda: self.store)

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
        user, via, _key = self.identify_full(headers)
        return user, via

    def identify_full(self, headers: dict) -> tuple[Optional[User], str, Optional[dict]]:
        authz = headers.get(b"authorization", b"").decode(errors="ignore")
        token = ""
        if authz.lower().startswith("bearer "):
            token = authz[7:].strip()
        token = token or headers.get(b"x-api-key", b"").decode(errors="ignore").strip()
        if token:
            found = self.store.verify_api_key_full(token)
            return (found[0], "api_key", found[1]) if found else (None, "api_key", None)
        cookie = headers.get(b"cookie", b"").decode(errors="ignore")
        for part in cookie.split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE and value:
                data = read_session(self.secret, value)
                if data:
                    user = self.store.get_user(int(data["u"]))
                    if user and not user.disabled and user.session_version == data.get("v"):
                        return user, "cookie", None
        return None, "", None

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        raw = [(k, v) for k, v in scope.get("headers", []) if k.lower() not in IDENTITY_HEADERS]
        headers = {k.lower(): v for k, v in raw}
        method = scope.get("method", "GET")
        path = scope.get("path", "/")

        if auth_mode() == "off":
            user = User(id=0, username="local", role="admin")
            via, key = "off", None
        else:
            user, via, key = self.identify_full(headers)
            need = required_role(method, path)
            if need is not None:
                if user is None:
                    msg = ("invalid, revoked or expired API key" if via == "api_key"
                           else "authentication required")
                    return await self._deny(scope, send, 401, msg, headers, path)
                if ROLE_RANK.get(user.role, -1) < ROLE_RANK[need]:
                    if key:
                        self.meter.deny(key["id"])
                    return await self._deny(scope, send, 403, f"requires role {need}",
                                            headers, path)
                if key is not None:
                    why = key_allows(key["scopes"], key["read_only"], method, path)
                    if why:
                        self.meter.deny(key["id"])
                        return await self._deny(scope, send, 403, why, headers, path)
                    if path.startswith("/mcp") and method.upper() == "POST" and scope["type"] == "http":
                        body, receive = await _buffer(receive)
                        why = _mcp_denied(body, key)
                        if why:
                            self.meter.deny(key["id"])
                            return await self._deny(scope, send, 403, why, headers, path)
                    ok, wait = self.meter.allow(key["id"], key["rate_per_min"])
                    if not ok:
                        return await self._deny(scope, send, 429,
                                                f"rate limit of {key['rate_per_min']} requests/min reached",
                                                headers, path, retry_after=wait)
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
            scope["state"] = {**scope["state"], "user": user, "auth_via": via,
                              "api_key": key, "key_meter": self.meter}
        else:
            scope = dict(scope, headers=raw)
        return await self.app(scope, receive, send)

    async def _deny(self, scope, send, status: int, message: str, headers: dict, path: str,
                    retry_after: int = 0):
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
        if status == 403 and scope.get("method") == "GET" and _wants_html(headers):
            page = (_FORBIDDEN_HTML % message).encode()
            await send({"type": "http.response.start", "status": 403,
                        "headers": [(b"content-type", b"text/html; charset=utf-8"),
                                    (b"cache-control", b"no-store")]})
            await send({"type": "http.response.body", "body": page})
            return
        body = json.dumps({"error": message, "status": status}).encode()
        hdrs = [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]
        if status == 401:
            hdrs.append((b"www-authenticate", b'Bearer realm="qfinzero"'))
        if retry_after:
            hdrs.append((b"retry-after", str(retry_after).encode()))
        await send({"type": "http.response.start", "status": status, "headers": hdrs})
        await send({"type": "http.response.body", "body": body})


_FORBIDDEN_HTML = """<!doctype html><meta charset=utf-8><title>No access · QFinZero</title>
<style>body{font:14px/1.6 ui-sans-serif,-apple-system,"Segoe UI",sans-serif;background:#f6f7f9;
color:#1d2331;display:grid;place-items:center;min-height:100vh;margin:0}main{max-width:26rem;
padding:1.5rem;background:#fff;border:1px solid #dfe2e8;border-radius:8px}a{color:#2557c2;
font-weight:500}</style><main><h1 style="margin:0 0 .5rem;font-size:1.15rem">
You don't have access to this page</h1><p>Your account's role does not allow it (%s). Ask an
admin to change your role.</p><p>你的账户角色无权访问此页面，请联系管理员。</p>
<p><a href="/chat">Back to the console</a> &middot; <a href="/account">Your account</a></p></main>"""


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
