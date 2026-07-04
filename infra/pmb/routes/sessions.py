from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from models.session import CreateSessionRequest, StepRequest

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
