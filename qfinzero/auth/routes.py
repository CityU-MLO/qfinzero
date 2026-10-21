"""``/auth/*`` endpoints served by the hub (login, setup, own keys, users)."""

from __future__ import annotations

import hmac
import os
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse

from .middleware import COOKIE, LoginThrottle, auth_mode
from .store import (ROLE_RANK, ROLES, SCOPES, AuthError, AuthStore, User, ensure_setup_token,
                    setup_token_path, sign_session)

SESSION_DAYS = float(os.environ.get("QFZ_SESSION_DAYS", "7"))


def _secure(request: Request) -> bool:
    flag = os.environ.get("QFZ_COOKIE_SECURE", "auto").lower()
    if flag in ("1", "true", "yes"):
        return True
    if flag in ("0", "false", "no"):
        return False
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto == "https"


def _client(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "?")


def key_options(body: dict) -> dict:
    """Key settings from a request body: ``scopes`` (list, or null for every
    scope), ``read_only``, ``expires_at`` (epoch seconds or ``YYYY-MM-DD``, end
    of that UTC day) or ``expires_in_days``, ``rate_per_min``, ``note``.
    Only the fields present are returned (for PATCH)."""
    out: dict = {}
    if "scopes" in body:
        sc = body["scopes"]
        if isinstance(sc, str):
            sc = [x.strip() for x in sc.split(",") if x.strip()]
        out["scopes"] = None if sc is None else [str(x) for x in sc]
    if "read_only" in body:
        out["read_only"] = bool(body["read_only"])
    if body.get("expires_in_days") not in (None, ""):
        try:
            days = float(body["expires_in_days"])
        except (TypeError, ValueError) as e:
            raise AuthError("expires_in_days must be a number") from e
        if days <= 0:
            raise AuthError("expires_in_days must be positive")
        out["expires_at"] = time.time() + days * 86400
    elif "expires_at" in body:
        v = body["expires_at"]
        if v in (None, ""):
            out["expires_at"] = None
        elif isinstance(v, (int, float)):
            out["expires_at"] = float(v)
        else:
            try:
                d = datetime.strptime(str(v)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError as e:
                raise AuthError("expires_at must be YYYY-MM-DD") from e
            out["expires_at"] = d.timestamp() + 86399
        if out["expires_at"] is not None and out["expires_at"] <= time.time():
            raise AuthError("expires_at is in the past")
    if "rate_per_min" in body:
        v = body["rate_per_min"]
        try:
            n = int(v) if v not in (None, "", 0, "0") else None
        except (TypeError, ValueError) as e:
            raise AuthError("rate_per_min must be a whole number") from e
        if n is not None and not 1 <= n <= 100_000:
            raise AuthError("rate_per_min must be between 1 and 100000")
        out["rate_per_min"] = n
    if "note" in body:
        out["note"] = str(body["note"] or "")
    return out


def build_router(store_factory, secret_factory) -> APIRouter:
    """``store_factory()`` -> AuthStore, ``secret_factory()`` -> bytes (lazy, testable)."""
    r = APIRouter(prefix="/auth")
    throttle = LoginThrottle()

    def store() -> AuthStore:
        return store_factory()

    def me(request: Request) -> User:
        user = getattr(request.state, "user", None)
        if user is None:
            raise HTTPException(401, "authentication required")
        return user

    def admin(request: Request) -> User:
        user = me(request)
        if user.role != "admin":
            raise HTTPException(403, "requires role admin")
        return user

    def login_response(request: Request, user: User, body: dict) -> JSONResponse:
        ttl = int(SESSION_DAYS * 86400)
        resp = JSONResponse(body)
        resp.set_cookie(COOKIE, sign_session(secret_factory(), user, ttl), max_age=ttl,
                        httponly=True, samesite="lax", secure=_secure(request), path="/")
        return resp

    @r.get("/status")
    def status():
        mode = auth_mode()
        n = store().count_users() if mode != "off" else 0
        return {"mode": mode, "has_users": n > 0, "setup_required": mode != "off" and n == 0}

    @r.post("/setup")
    def setup(request: Request, body: dict = Body(...)):
        """Create the first admin; needs the one-time token from the server log
        (or ``_state/setup_token``)."""
        s = store()
        if s.count_users() > 0:
            raise HTTPException(409, "already set up")
        expected = ensure_setup_token()
        if not hmac.compare_digest(str(body.get("token", "")), expected):
            raise HTTPException(403, "invalid setup token")
        try:
            user = s.create_user(body.get("username", ""), body.get("password", ""), "admin",
                                 body.get("display_name", ""))
        except AuthError as e:
            raise HTTPException(400, str(e)) from e
        setup_token_path().unlink(missing_ok=True)
        s.audit(user.username, "setup", "first admin created")
        return login_response(request, user, {"ok": True, "user": user.public()})

    @r.post("/login")
    def login(request: Request, body: dict = Body(...)):
        username = str(body.get("username", ""))
        client = _client(request)
        if throttle.blocked(client, username):
            raise HTTPException(429, "too many failed attempts; try again in a few minutes")
        user = store().authenticate(username, str(body.get("password", "")))
        if user is None:
            throttle.fail(client, username)
            store().audit(username, "login_failed", client)
            raise HTTPException(401, "invalid username or password")
        throttle.ok(client, username)
        store().audit(user.username, "login", client)
        return login_response(request, user, {"ok": True, "user": user.public()})

    @r.post("/logout")
    def logout():
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    @r.get("/me")
    def whoami(request: Request):
        """The signed-in user, or ``{"user": null}`` (public, so the site can ask)."""
        user = getattr(request.state, "user", None)
        if user is None:
            return {"user": None}
        return {"user": user.public(), "via": getattr(request.state, "auth_via", "")}

    @r.post("/password")
    def change_password(request: Request, body: dict = Body(...)):
        user = me(request)
        s = store()
        if not s.authenticate(user.username, str(body.get("current_password", ""))):
            raise HTTPException(403, "current password is wrong")
        try:
            s.set_password(user.id, str(body.get("new_password", "")))
        except AuthError as e:
            raise HTTPException(400, str(e)) from e
        s.audit(user.username, "password_changed")
        fresh = s.get_user(user.id)
        return login_response(request, fresh, {"ok": True})     # re-issue (version bumped)

    def flush(request: Request) -> None:
        meter = getattr(request.state, "key_meter", None)
        if meter is not None:
            meter.flush()

    def no_key_admin(request: Request) -> None:
        """Keys are managed from a signed-in session, or by a key with the admin scope."""
        key = getattr(request.state, "api_key", None)
        if key is not None and key["scopes"] is not None and "admin" not in key["scopes"]:
            raise HTTPException(403, "API keys cannot manage keys without the admin scope")

    def issue(request: Request, actor: User, owner_id: int, body: dict) -> dict:
        no_key_admin(request)
        try:
            opts = key_options(body)
            meta, token = store().create_api_key(owner_id, str(body.get("name", "")),
                                                 created_by=actor.username, **opts)
        except AuthError as e:
            raise HTTPException(400, str(e)) from e
        store().audit(actor.username, "key_created", f"{meta['prefix']} for {meta['username']}")
        return {"key": meta, "token": token,
                "note": "the owner and admins can show the token again from the key list"}

    @r.get("/scopes")
    def scopes(request: Request):
        user = me(request)
        return {"scopes": [{"id": k, "paths": list(v[0]), "min_role": v[1], "description": v[2],
                            "available": ROLE_RANK.get(user.role, -1) >= ROLE_RANK[v[1]]}
                           for k, v in SCOPES.items()]}

    # own API keys
    @r.get("/keys")
    def keys(request: Request):
        flush(request)
        return {"keys": store().list_api_keys(me(request).id)}

    @r.post("/keys")
    def create_key(request: Request, body: dict = Body(default={})):
        user = me(request)   # a key never exceeds its owner's role
        return issue(request, user, user.id, body)

    @r.patch("/keys/{key_id}")
    def update_key(request: Request, key_id: int, body: dict = Body(...)):
        user = me(request)
        no_key_admin(request)
        try:
            k = store().update_api_key(key_id, user_id=None if user.role == "admin" else user.id,
                                       **({"name": body["name"]} if "name" in body else {}),
                                       **key_options(body))
        except AuthError as e:
            raise HTTPException(404 if "not found" in str(e) else 400, str(e)) from e
        store().audit(user.username, "key_updated", f"{k['prefix']}:{sorted(body)}")
        return {"key": k}

    @r.get("/keys/{key_id}/token")
    def reveal_key(request: Request, key_id: int):
        """Show a key's token again: your own keys, or any key for an admin."""
        user = me(request)
        no_key_admin(request)
        try:
            token = store().reveal_api_key(key_id, None if user.role == "admin" else user.id)
        except AuthError as e:
            raise HTTPException(404 if "not found" in str(e) else 409, str(e)) from e
        store().audit(user.username, "key_revealed", str(key_id))
        return JSONResponse({"id": key_id, "token": token}, headers={"cache-control": "no-store"})

    @r.delete("/keys/{key_id}")
    def revoke_key(request: Request, key_id: int):
        user = me(request)
        no_key_admin(request)
        try:
            store().revoke_api_key(key_id, None if user.role == "admin" else user.id)
        except AuthError as e:
            raise HTTPException(404, str(e)) from e
        store().audit(user.username, "key_revoked", str(key_id))
        return {"ok": True}

    @r.post("/users/{user_id}/keys")
    def issue_key(request: Request, user_id: int, body: dict = Body(default={})):
        actor = admin(request)
        if store().get_user(user_id) is None:
            raise HTTPException(404, "user not found")
        return issue(request, actor, user_id, body)

    # user administration
    @r.get("/users")
    def users(request: Request):
        admin(request)
        flush(request)
        return {"users": [u.public() for u in store().list_users()], "roles": list(ROLES),
                "keys": store().list_api_keys()}

    @r.post("/users")
    def create_user(request: Request, body: dict = Body(...)):
        actor = admin(request)
        try:
            user = store().create_user(body.get("username", ""), body.get("password", ""),
                                       body.get("role", "researcher"), body.get("display_name", ""))
        except AuthError as e:
            raise HTTPException(400, str(e)) from e
        store().audit(actor.username, "user_created", f"{user.username}:{user.role}")
        return {"user": user.public()}

    @r.patch("/users/{user_id}")
    def update_user(request: Request, user_id: int, body: dict = Body(...)):
        actor = admin(request)
        s = store()
        try:
            user = s.update_user(user_id, role=body.get("role"), disabled=body.get("disabled"),
                                 display_name=body.get("display_name"))
            if body.get("password"):
                s.set_password(user_id, str(body["password"]))
        except AuthError as e:
            raise HTTPException(400, str(e)) from e
        s.audit(actor.username, "user_updated", f"{user.username}:{sorted(body)}")
        return {"user": s.get_user(user_id).public()}

    @r.delete("/users/{user_id}")
    def delete_user(request: Request, user_id: int):
        actor = admin(request)
        if actor.id == user_id:
            raise HTTPException(400, "you cannot delete yourself")
        try:
            store().delete_user(user_id)
        except AuthError as e:
            raise HTTPException(400, str(e)) from e
        store().audit(actor.username, "user_deleted", str(user_id))
        return {"ok": True}

    return r


def bootstrap_admin(store: AuthStore, log) -> None:
    """First run: create ``QFZ_ADMIN_USERNAME``/``QFZ_ADMIN_PASSWORD`` if set,
    else print a one-time setup token for the /setup page."""
    if auth_mode() == "off" or store.count_users() > 0:
        return
    user = os.environ.get("QFZ_ADMIN_USERNAME", "admin")
    pw = os.environ.get("QFZ_ADMIN_PASSWORD", "")
    if pw:
        try:
            store.create_user(user, pw, "admin")
            log.warning("created admin user %r from QFZ_ADMIN_PASSWORD", user)
            return
        except AuthError as e:
            log.error("QFZ_ADMIN_PASSWORD rejected: %s", e)
    token = ensure_setup_token()
    log.warning("no users yet: open /setup and enter setup token %s "
                "(or run `qfz-auth create-user <name> --role admin`)", token)
