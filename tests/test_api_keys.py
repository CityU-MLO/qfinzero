"""Distributed API keys: scopes, read-only, expiry, rate limits, usage, issuing."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from qfinzero.auth import AuthMiddleware, AuthStore  # noqa: E402
from qfinzero.auth.store import AuthError, key_allows, mcp_tool_allows  # noqa: E402

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
    from qfinzero.server import app as app_mod
    monkeypatch.setattr(app_mod, "_ROUTES", {n: "http://127.0.0.1:9" for n in app_mod._ROUTES})


def _echo_client(store):
    seen: dict = {}

    async def echo(scope, receive, send):
        msg = await receive()
        seen["body"] = msg.get("body", b"")
        seen["path"] = scope["path"]
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = AuthMiddleware(echo, store_factory=lambda: store)
    return TestClient(mw), seen, mw


def test_policy_helpers():
    assert key_allows(None, False, "POST", "/svc/pmb/v1/orders") is None          # legacy key
    assert key_allows(["market-data"], False, "GET", "/svc/upq/stock") is None
    assert "scopes" in key_allows(["market-data"], False, "GET", "/svc/esp/events")
    assert "read-only" in key_allows(["trading"], True, "POST", "/svc/pmb/v1/orders")
    assert key_allows(["events"], True, "POST", "/svc/esp/esp/events/query") is None   # a query
    assert key_allows(["events"], False, "GET", "/auth/me") is None
    assert mcp_tool_allows(["mcp", "market-data"], False, "upq_stock_daily") is None
    assert "trading" in mcp_tool_allows(["mcp", "market-data"], False, "pmb_trade")
    assert mcp_tool_allows(["mcp", "trading"], True, "pmb_get_positions") is None
    assert "read-only" in mcp_tool_allows(["mcp", "trading"], True, "pmb_buy_stock")


def test_store_scopes_expiry_and_migration(env):
    s = AuthStore()
    v = s.create_user("vic", PW, "viewer")
    with pytest.raises(AuthError, match="viewer role cannot"):
        s.create_api_key(v.id, "x", scopes=["trading"])
    with pytest.raises(AuthError, match="unknown"):
        s.create_api_key(v.id, "x", scopes=["everything"])
    with pytest.raises(AuthError, match="at least one"):
        s.create_api_key(v.id, "x", scopes=[])
    meta, token = s.create_api_key(v.id, "feed", scopes=["market-data", "events"], read_only=True,
                                   rate_per_min=5, note="for the notebook", created_by="root")
    assert meta["scopes"] == ["events", "market-data"] and meta["read_only"]
    assert meta["rate_per_min"] == 5 and meta["created_by"] == "root" and meta["user_id"] == v.id
    user, key = s.verify_api_key_full(token)
    assert user.id == v.id and key["scopes"] == ["events", "market-data"]
    # expiry
    meta2, tok2 = s.create_api_key(v.id, "short", expires_at=time.time() + 60)
    assert s.verify_api_key(tok2) is not None
    s.update_api_key(meta2["id"], expires_at=time.time() - 1)
    assert s.verify_api_key(tok2) is None
    assert [k for k in s.list_api_keys(v.id) if k["id"] == meta2["id"]][0]["expired"]
    # someone else's key
    other = s.create_user("ann", PW, "researcher")
    with pytest.raises(AuthError, match="not found"):
        s.update_api_key(meta["id"], user_id=other.id, name="mine")
    # usage accumulates
    day = time.strftime("%Y-%m-%d", time.gmtime())
    s.add_usage({(meta["id"], day): [3, 1]})
    s.add_usage({(meta["id"], day): [2, 0]})
    k = [k for k in s.list_api_keys(v.id) if k["id"] == meta["id"]][0]
    assert k["usage"] == [{"day": day, "requests": 5, "denied": 1}] and k["requests_total"] == 5


def test_old_database_is_migrated(env, tmp_path):
    db = tmp_path / "state" / "auth.sqlite3"
    db.parent.mkdir(parents=True)
    c = sqlite3.connect(db)
    c.executescript("""
        CREATE TABLE api_keys (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            name TEXT NOT NULL, prefix TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE,
            created_at REAL NOT NULL, last_used_at REAL, revoked INTEGER NOT NULL DEFAULT 0);""")
    c.commit()
    c.close()
    s = AuthStore()
    u = s.create_user("old", PW, "researcher")
    meta, token = s.create_api_key(u.id, "k")
    assert meta["scopes"] is None and s.verify_api_key(token).id == u.id


def test_middleware_enforces_scope_readonly_rate_and_mcp(env):
    store = AuthStore()
    u = store.create_user("res", PW, "researcher")
    _, data_tok = store.create_api_key(u.id, "data", scopes=["market-data"], rate_per_min=3)
    _, mcp_tok = store.create_api_key(u.id, "agent", scopes=["mcp", "market-data", "trading"],
                                      read_only=True)
    client, seen, mw = _echo_client(store)
    h = {"authorization": f"Bearer {data_tok}"}
    assert client.get("/svc/upq/stock", headers=h).status_code == 200
    r = client.get("/svc/esp/events", headers=h)
    assert r.status_code == 403 and "scopes" in r.json()["error"]
    assert client.get("/svc/upq/stock", headers=h).status_code == 200
    assert client.get("/svc/upq/stock", headers=h).status_code == 200
    r = client.get("/svc/upq/stock", headers=h)                       # 4th in a minute
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    # MCP: tools follow scopes; read-only blocks state-changing broker tools; body reaches the app
    m = {"authorization": f"Bearer {mcp_tok}", "content-type": "application/json"}
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "upq_stock_daily", "arguments": {}}}
    r = client.post("/mcp/", headers=m, content=json.dumps(call))
    assert r.status_code == 200 and json.loads(seen["body"])["params"]["name"] == "upq_stock_daily"
    call["params"]["name"] = "pmb_buy_stock"
    r = client.post("/mcp/", headers=m, content=json.dumps(call))
    assert r.status_code == 403 and "read-only" in r.json()["error"]
    call["params"]["name"] = "esp_search_news"
    assert client.post("/mcp/", headers=m, content=json.dumps([call])).status_code == 403
    assert client.post("/mcp/", headers=m, content=json.dumps(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})).status_code == 200
    # usage reached the store, denials counted
    mw.meter.flush()
    by = {k["name"]: k for k in store.list_api_keys(u.id)}
    assert by["data"]["requests_total"] == 5 and by["data"]["usage"][0]["denied"] == 2
    assert by["agent"]["usage"][0]["denied"] == 2


def test_routes_issue_patch_and_scopes(env):
    from qfinzero.server.app import build_app
    store = AuthStore()
    store.create_user("root", PW, "admin")
    vic = store.create_user("vic", PW, "viewer")
    with TestClient(build_app(auth_store=store), base_url="http://hub.test") as client:
        assert client.post("/auth/login", json={"username": "root", "password": PW}).status_code == 200
        sc = {x["id"]: x for x in client.get("/auth/scopes").json()["scopes"]}
        assert sc["admin"]["available"] and sc["trading"]["min_role"] == "researcher"
        r = client.post(f"/auth/users/{vic.id}/keys", json={"name": "vic-feed", "scopes": ["trading"]})
        assert r.status_code == 400 and "viewer role" in r.json()["detail"]
        r = client.post(f"/auth/users/{vic.id}/keys",
                        json={"name": "vic-feed", "scopes": ["market-data"], "expires_in_days": 30,
                              "rate_per_min": 60, "note": "class of 2026"})
        assert r.status_code == 200, r.text
        body = r.json()
        key, token = body["key"], body["token"]
        assert key["username"] == "vic" and key["created_by"] == "root"
        assert 29 * 86400 < key["expires_at"] - time.time() <= 30 * 86400
        assert client.post("/auth/keys", json={"expires_at": "2001-01-01"}).status_code == 400
        r = client.patch(f"/auth/keys/{key['id']}", json={"rate_per_min": None, "read_only": True})
        assert r.status_code == 200 and r.json()["key"]["rate_per_min"] is None
        assert r.json()["key"]["read_only"]
        client.cookies.clear()
        bearer = {"authorization": f"Bearer {token}"}
        assert client.get("/svc/upq/health", headers=bearer).status_code == 502      # proxied
        assert client.get("/svc/pmb/v1/accounts", headers=bearer).status_code == 403
        assert client.get("/auth/keys", headers=bearer).status_code == 403          # no self-service
        assert client.get("/auth/me", headers=bearer).json()["user"]["username"] == "vic"
        assert client.post("/auth/login", json={"username": "root", "password": PW}).status_code == 200
        users = client.get("/auth/users").json()
        k = [k for k in users["keys"] if k["id"] == key["id"]][0]
        assert k["requests_total"] >= 3 and k["note"] == "class of 2026"
        assert client.delete(f"/auth/keys/{key['id']}").status_code == 200
        client.cookies.clear()
        r = client.get("/svc/upq/health", headers=bearer)
        assert r.status_code == 401 and "revoked" in r.json()["error"]
