"""Hub authentication: store, policy, middleware and /auth routes."""

from __future__ import annotations

import os
import sys

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from qfinzero.auth import AuthMiddleware, AuthStore, required_role  # noqa: E402
from qfinzero.auth.store import (AuthError, ensure_setup_token, read_session,  # noqa: E402
                                 sign_session)

PW = "correct-horse-battery"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("QFZ_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("QFZ_AUTH_DB", str(tmp_path / "state" / "auth.sqlite3"))
    monkeypatch.setenv("QFZ_SUPERVISE", "0")
    monkeypatch.setenv("QFZ_AUTH_MODE", "required")
    monkeypatch.delenv("QFZ_SECRET_KEY", raising=False)
    monkeypatch.delenv("QFZ_ADMIN_PASSWORD", raising=False)
    return tmp_path


@pytest.fixture(autouse=True)
def _dead_upstreams(monkeypatch):
    """Never reach real services: point every /svc route at a closed port."""
    from qfinzero.server import app as app_mod
    monkeypatch.setattr(app_mod, "_ROUTES", {n: "http://127.0.0.1:9" for n in app_mod._ROUTES})


@pytest.fixture
def hub(env):
    from qfinzero.server.app import build_app
    store = AuthStore()
    app = build_app(auth_store=store)
    with TestClient(app, base_url="http://hub.test") as client:
        yield client, store


# ── store ────────────────────────────────────────────────────────────────

def test_store_users_keys_and_sessions(env):
    s = AuthStore()
    with pytest.raises(AuthError):
        s.create_user("bob", "short")
    with pytest.raises(AuthError):
        s.create_user("Bad Name!", PW)
    u = s.create_user("Alice", PW, "admin")
    assert u.username == "alice" and s.authenticate("ALICE", PW).id == u.id
    assert s.authenticate("alice", "wrong-password") is None
    meta, token = s.create_api_key(u.id, "runner")
    assert token.startswith("qfz_") and s.verify_api_key(token).id == u.id
    assert "key_hash" not in str(s.list_api_keys())
    s.revoke_api_key(meta["id"])
    assert s.verify_api_key(token) is None
    secret = b"s" * 32
    cookie = sign_session(secret, u, 60)
    assert read_session(secret, cookie)["u"] == u.id
    assert read_session(b"x" * 32, cookie) is None
    with pytest.raises(AuthError):
        s.update_user(u.id, role="viewer")            # last admin
    s.set_password(u.id, "another-long-password")
    assert s.get_user(u.id).session_version == u.session_version + 1


def test_policy():
    assert required_role("GET", "/") is None and required_role("GET", "/login") is None
    assert required_role("GET", "/_next/static/x.js") is None
    assert required_role("GET", "/svc/upq/stock") == "viewer"
    assert required_role("POST", "/svc/esp/esp/events/query") == "viewer"     # a query, not a write
    assert required_role("POST", "/svc/pmb/v1/orders") == "researcher"
    assert required_role("POST", "/svc/pmb/v1/orders") == "researcher"
    assert required_role("POST", "/mcp/") == "researcher"
    assert required_role("GET", "/svc/data-admin/data/config") == "admin"
    assert required_role("GET", "/admin/users") == "admin"
    assert required_role("GET", "/docs") is None and required_role("GET", "/docs/mcp-tools") is None
    assert required_role("GET", "/api/docs") is None
    assert required_role("POST", "/api/docs") == "viewer"
    assert required_role("GET", "/doc") == "viewer"          # not a prefix match of /docs/


# ── hub ──────────────────────────────────────────────────────────────────

def _login(client, user, pw=PW):
    r = client.post("/auth/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return r


def test_unauthenticated_requests_are_refused_or_redirected(hub):
    client, _ = hub
    assert client.get("/svc/upq/health").status_code == 401
    r = client.get("/broker", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/login?next=%2Fbroker"
    assert client.get("/auth/status").json()["setup_required"] is True
    assert client.get("/health").status_code == 200


def test_setup_needs_the_one_time_token(hub):
    client, store = hub
    bad = client.post("/auth/setup", json={"token": "nope", "username": "root", "password": PW})
    assert bad.status_code == 403
    token = ensure_setup_token()
    ok = client.post("/auth/setup", json={"token": token, "username": "root", "password": PW})
    assert ok.status_code == 200 and "qfz_session" in ok.cookies
    assert client.get("/auth/me").json()["user"]["role"] == "admin"
    again = client.post("/auth/setup", json={"token": token, "username": "x", "password": PW})
    assert again.status_code == 409


def test_roles_cookies_keys_and_header_spoofing(hub):
    client, store = hub
    store.create_user("root", PW, "admin")
    _login(client, "root")
    r = client.post("/auth/users", json={"username": "vic", "password": PW, "role": "viewer"})
    assert r.status_code == 200
    client.post("/auth/logout")
    client.cookies.clear()
    _login(client, "vic")
    # viewer: reads pass the gate (502 = proxied, no upstream in tests), writes do not
    assert client.get("/svc/upq/health").status_code == 502
    assert client.post("/svc/pmb/v1/orders", json={}).status_code == 403
    assert client.post("/mcp/", json={}).status_code == 403
    assert client.get("/auth/users").status_code == 403
    # a forged role header does not help
    assert client.post("/svc/pmb/v1/orders", json={},
                       headers={"x-qfz-role": "admin", "x-qfz-user": "root"}).status_code == 403
    # API keys act as their owner
    key = client.post("/auth/keys", json={"name": "bot"}).json()["token"]
    client.cookies.clear()
    bearer = {"authorization": f"Bearer {key}"}
    assert client.get("/auth/me", headers=bearer).json()["user"]["username"] == "vic"
    assert client.get("/auth/me", headers={"authorization": "Bearer qfz_bad_x"}).json()["user"] is None
    assert client.get("/admin/users", headers={**bearer, "accept": "text/html"}).status_code == 403


def test_docs_root_is_the_web_hub_not_swagger(hub):
    client, _ = hub
    paths = {getattr(r, "path", "") for r in client.app.routes}
    assert "/docs" not in paths and "/redoc" not in paths and "/svc/openapi.json" in paths


def test_csrf_and_password_change_invalidate(hub):
    client, store = hub
    store.create_user("res", PW, "researcher")
    _login(client, "res")
    assert client.post("/svc/pmb/v1/orders", json={},
                       headers={"origin": "https://evil.example"}).status_code == 403
    assert client.post("/svc/pmb/v1/orders", json={},
                       headers={"origin": "http://hub.test"}).status_code == 502
    old = client.cookies.get("qfz_session")
    r = client.post("/auth/password", json={"current_password": PW,
                                            "new_password": "a-new-long-password"})
    assert r.status_code == 200
    client.cookies.clear()
    client.cookies.set("qfz_session", old)
    assert client.get("/auth/me").json()["user"] is None   # version bumped
    assert client.get("/svc/upq/health").status_code == 401


def test_login_throttle(hub):
    client, store = hub
    store.create_user("t", PW, "viewer")
    for _ in range(5):
        assert client.post("/auth/login", json={"username": "t", "password": "x"}).status_code == 401
    assert client.post("/auth/login", json={"username": "t", "password": PW}).status_code == 429


def test_middleware_strips_and_injects_identity(env):
    seen = {}

    async def echo(scope, receive, send):
        seen.update({k.decode(): v.decode() for k, v in scope["headers"]})
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    store = AuthStore()
    u = store.create_user("ann", PW, "researcher")
    _, token = store.create_api_key(u.id, "k")
    client = TestClient(AuthMiddleware(echo, store_factory=lambda: store))
    client.get("/svc/upq/x", headers={"authorization": f"Bearer {token}", "x-qfz-role": "admin"})
    assert (seen["x-qfz-user"], seen["x-qfz-role"]) == ("ann", "researcher")


def test_auth_off_mode(env, monkeypatch):
    monkeypatch.setenv("QFZ_AUTH_MODE", "off")
    from qfinzero.server.app import build_app
    with TestClient(build_app(auth_store=AuthStore())) as client:
        assert client.get("/svc/upq/health").status_code == 502       # passes the gate
        assert client.get("/auth/status").json()["mode"] == "off"
