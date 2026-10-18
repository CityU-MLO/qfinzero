"""``/auth/*`` endpoints served by the hub (login, setup, own keys, users)."""

from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse

from .middleware import COOKIE, LoginThrottle, auth_mode
from .store import (ROLES, AuthError, AuthStore, User, ensure_setup_token, setup_token_path,
                    sign_session)

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
        user = me(request)
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

    # own API keys
    @r.get("/keys")
    def keys(request: Request):
        return {"keys": store().list_api_keys(me(request).id)}

    @r.post("/keys")
    def create_key(request: Request, body: dict = Body(default={})):
        user = me(request)   # a key acts with its owner's role
        meta, token = store().create_api_key(user.id, str(body.get("name", "")))
        store().audit(user.username, "key_created", meta["prefix"])
        return {"key": meta, "token": token,
                "note": "copy the token now; it is not shown again"}

    @r.delete("/keys/{key_id}")
    def revoke_key(request: Request, key_id: int):
        user = me(request)
        try:
            store().revoke_api_key(key_id, None if user.role == "admin" else user.id)
        except AuthError as e:
            raise HTTPException(404, str(e)) from e
        store().audit(user.username, "key_revoked", str(key_id))
        return {"ok": True}

    # user administration
    @r.get("/users")
    def users(request: Request):
        admin(request)
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
