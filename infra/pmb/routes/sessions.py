from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from models.session import CreateSessionRequest, StepRequest, StepUntilRequest

router = APIRouter(tags=["sessions"])


@router.post("/v1/sessions")
async def create_session(req: CreateSessionRequest, request: Request):
    account_svc = request.app.state.account_service
    session_svc = request.app.state.session_service

    account = account_svc.get_account(req.account_id)
    if account is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_argument", "message": "account_id not found"},
        )

    session_id, clock = await session_svc.create_session(req, account)

    return {
        "ok": True,
        "session_id": session_id,
        "account_id": req.account_id,
        "clock": clock.model_dump(),
    }


@router.get("/v1/sessions/{session_id}")
async def get_session(session_id: str, request: Request):
    session_svc = request.app.state.session_service
    state = session_svc.get_session(session_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "session not found"},
        )

    return {
        "session_id": session_id,
        "account_id": state.account_id,
        "clock": {
            "frequency": state.clock.frequency.value,
            "current_ts": state.clock.current_ts,
            "end_ts": state.clock.end_ts,
            "status": state.status.value,
        },
        "config": state.config.model_dump(),
    }


@router.post("/v1/sessions/{session_id}/step")
async def step_session(session_id: str, req: StepRequest, request: Request):
    session_svc = request.app.state.session_service
    state = session_svc.get_session(session_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "session not found"},
        )

    from models.enums import SessionStatus

    if state.status != SessionStatus.RUNNING:
        raise HTTPException(
            status_code=409,
            detail={"code": "conflict", "message": "session already finished"},
        )

    result = session_svc.step(session_id, req.step)
    return result


@router.post("/v1/sessions/{session_id}/step_until")
async def step_session_until(session_id: str, req: StepUntilRequest, request: Request):
    """Advance until a fill, a price trigger, a time or a session segment."""
    session_svc = request.app.state.session_service
    if session_svc.get_session(session_id) is None:
        raise HTTPException(status_code=404,
                            detail={"code": "not_found", "message": "session not found"})
    result = session_svc.step_until(session_id, req)
    if not result.get("ok"):
        raise HTTPException(status_code=409,
                            detail={"code": "conflict", "message": result.get("error")})
    return result


@router.get("/v1/sessions/{session_id}/state")
async def get_full_state(session_id: str, request: Request):
    """Consolidated snapshot (clock, account, positions, orders, market) for the UI."""
    session_svc = request.app.state.session_service
    state = session_svc.get_full_state(session_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "session not found"},
        )
    return state


@router.get("/v1/sessions/{session_id}/timeline")
async def get_timeline(session_id: str, request: Request):
    """The full list of bar timestamps — the scrubbable simulation clock."""
    session_svc = request.app.state.session_service
    timeline = session_svc.get_timeline(session_id)
    if timeline is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "session not found"},
        )
    return {"session_id": session_id, "timeline": timeline, "count": len(timeline)}


@router.post("/v1/sessions/{session_id}/rewind")
async def rewind_session(session_id: str, request: Request):
    """Time-travel back to target_ts, undoing every action placed after it."""
    body = await request.json()
    target_ts = body.get("target_ts")
    if not target_ts:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_argument", "message": "target_ts is required"},
        )
    session_svc = request.app.state.session_service
    result = session_svc.rewind(session_id, target_ts)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "session not found"},
        )
    return result


@router.post("/v1/sessions/{session_id}/stop")
async def stop_session(session_id: str, request: Request):
    session_svc = request.app.state.session_service
    ok = session_svc.stop_session(session_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "session not found"},
        )
    return {"ok": True, "session_id": session_id, "status": "STOPPED"}


@router.get("/v1/sessions/{session_id}/summary")
async def get_summary(session_id: str, request: Request):
    session_svc = request.app.state.session_service
    summary = session_svc.get_summary(session_id)
    if summary is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "session not found"},
        )
    return summary.model_dump()


@router.get("/v1/sessions/{session_id}/export")
async def export_session(
    session_id: str,
    request: Request,
    format: str = "json",
):
    history_svc = request.app.state.history_service
    if format == "csv":
        # Export all as separate CSV sections
        result = {}
        for what in ("orders", "trades", "equity_curve", "snapshots"):
            csv_data = history_svc.export_csv(session_id, what)
            if csv_data is not None:
                result[what] = csv_data
        if not result:
            raise HTTPException(
                status_code=404,
                detail={"code": "not_found", "message": "session not found"},
            )
        return result

    data = history_svc.export_json(session_id)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "session not found"},
        )
    return data


@router.get("/v1/sessions/{session_id}/option_chain")
async def get_option_chain(
    session_id: str,
    request: Request,
    underlying: str,
    expiry: str | None = None,
    window: int = 12,
):
    """Live, minute-level two-sided option chain (calls|strike|puts) at the current bar."""
    session_svc = request.app.state.session_service
    result = await session_svc.get_option_chain(session_id, underlying, expiry, window)
    if not result.get("ok"):
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": result.get("error", "unknown")},
        )
    return result


@router.post("/v1/sessions/{session_id}/add_stocks")
async def add_stocks(session_id: str, request: Request):
    body = await request.json()
    symbols = body.get("symbols", [])
    session_svc = request.app.state.session_service
    result = await session_svc.add_stocks(session_id, symbols)
    if not result.get("ok"):
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": result.get("error", "unknown")},
        )
    return result


@router.post("/v1/sessions/{session_id}/add_contracts")
async def add_contracts(session_id: str, request: Request):
    body = await request.json()
    contracts = body.get("contracts", [])
    session_svc = request.app.state.session_service
    result = await session_svc.add_option_contracts(session_id, contracts)
    if not result.get("ok"):
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": result.get("error", "unknown")},
        )
    return result


@router.get("/v1/sessions/{session_id}/checkpoint")
async def checkpoint_session(session_id: str, request: Request):
    """Export account and deterministic simulation state."""
    session_svc = request.app.state.session_service
    account_svc = request.app.state.account_service
    checkpoint = session_svc.export_checkpoint(session_id)
    state = session_svc.get_session(session_id)
    if checkpoint is None or state is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "session not found"},
        )
    account = account_svc.get_account(state.account_id)
    if account is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "conflict", "message": "session account not found"},
        )
    return {
        "ok": True,
        "account": account.model_dump(mode="json"),
        "checkpoint": checkpoint,
    }


@router.post("/v1/sessions/restore")
async def restore_session(request: Request):
    """Restore a checkpoint into a new account and independent session."""
    body = await request.json()
    checkpoint = body.get("checkpoint")
    account_raw = body.get("account")
    if not isinstance(checkpoint, dict) or not isinstance(account_raw, dict):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_argument",
                "message": "account and checkpoint are required",
            },
        )

    account_svc = request.app.state.account_service
    session_svc = request.app.state.session_service
    account = None
    existing_sessions = set(session_svc._sessions)
    try:
        account = account_svc.restore_account(account_raw)
        session_id, clock = await session_svc.restore_checkpoint(checkpoint, account)
    except (TypeError, ValueError, KeyError) as exc:
        if account is not None:
            account_svc._accounts.pop(account.account_id, None)
        for session_id in set(session_svc._sessions) - existing_sessions:
            session_svc._sessions.pop(session_id, None)
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_checkpoint", "message": str(exc)},
        ) from exc
    return {
        "ok": True,
        "session_id": session_id,
        "account_id": account.account_id,
        "clock": clock.model_dump(mode="json"),
    }
