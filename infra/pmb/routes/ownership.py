"""Per-user scoping of PMB accounts and sessions.

The hub authenticates callers and forwards the verified identity as
``x-qfz-user`` / ``x-qfz-role`` (PMB itself only listens on localhost). With an
identity present, a non-admin sees only accounts it owns and sessions on those
accounts; anything else answers 404 so other users' ids are not confirmed.
Requests without identity headers (direct local use, tests, scripts) keep the
old unscoped behaviour, and accounts created that way have no owner.
"""

from __future__ import annotations

import re

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

_ACCOUNT = re.compile(r"^/v1/accounts/([^/]+)")
_SESSION = re.compile(r"^/v1/sessions/([^/]+)")


def caller(request: Request) -> tuple[str | None, bool]:
    """``(username, is_admin)``; username is None when no identity was forwarded."""
    user = request.headers.get("x-qfz-user") or None
    return user, request.headers.get("x-qfz-role") == "admin"


def owns(request: Request, account) -> bool:
    user, admin = caller(request)
    if user is None or admin or account is None:
        return True
    return getattr(account, "owner", None) == user


def owner_for_new(request: Request) -> str | None:
    return caller(request)[0]


def _not_found(what: str):
    return JSONResponse(status_code=404, content={"detail": {"code": "not_found",
                                                            "message": f"{what} not found"}})


def require_account(request: Request, account_id: str) -> None:
    account = request.app.state.account_service.get_account(account_id)
    if account is not None and not owns(request, account):
        raise HTTPException(404, detail={"code": "not_found", "message": "account_id not found"})


def require_session(request: Request, session_id: str) -> None:
    state = request.app.state.session_service.get_session(session_id)
    if state is None:
        return
    account = request.app.state.account_service.get_account(state.account_id)
    if not owns(request, account):
        raise HTTPException(404, detail={"code": "not_found", "message": "session not found"})


async def ownership_middleware(request: Request, call_next):
    """Path-level checks for /v1/accounts/{id}/... and /v1/sessions/{id}/..."""
    user, admin = caller(request)
    if user is not None and not admin:
        path = request.url.path
        m = _ACCOUNT.match(path)
        if m:
            acct = request.app.state.account_service.get_account(m.group(1))
            if acct is not None and not owns(request, acct):
                return _not_found("account")
        m = _SESSION.match(path)
        if m and m.group(1) != "restore":
            state = request.app.state.session_service.get_session(m.group(1))
            if state is not None:
                acct = request.app.state.account_service.get_account(state.account_id)
                if not owns(request, acct):
                    return _not_found("session")
    return await call_next(request)
