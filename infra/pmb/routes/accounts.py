from fastapi import APIRouter, HTTPException, Request

from models.account import CreateAccountRequest, AccountState
from models.enums import MarginStatus

router = APIRouter(tags=["accounts"])


@router.post("/v1/accounts")
async def create_account(req: CreateAccountRequest, request: Request):
    account_svc = request.app.state.account_service
    account = account_svc.create_account(req)

    state = AccountState(
        cash_available=account.initial_cash,
        equity=account.initial_cash,
        margin_excess=account.initial_cash,
        buying_power=account.initial_cash * 2,
        margin_status=MarginStatus.NORMAL,
    )

    return {
        "ok": True,
        "account_id": account.account_id,
        "created_at": account.created_at,
        "account_state": state.model_dump(),
    }


@router.get("/v1/accounts/{account_id}")
async def get_account(account_id: str, request: Request):
    account_svc = request.app.state.account_service
    account = account_svc.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "account not found"})

    # Check if there's an active session for this account
    session_svc = request.app.state.session_service
    for sid, state in session_svc._sessions.items():
        if state.account_id == account_id:
            im = state.margin_engine.total_initial_margin(state.ledger.positions)
            mm = state.margin_engine.total_maintenance_margin(state.ledger.positions)
            open_orders = [
                {
                    "order_id": o.order_id,
                    "instrument_id": o.instrument_id,
                    "side": o.side.value,
                    "order_type": o.order_type.value,
                    "qty": o.qty,
                    "limit_price": o.limit_price,
                    "status": o.status.value,
                }
                for o in state.order_manager.get_open_orders()
            ]
            snapshot = state.ledger.get_snapshot(im, mm, state.margin_engine.margin_status, open_orders)
            return snapshot.model_dump()

    # No active session, return initial state
    return AccountState(
        cash_available=account.initial_cash,
        equity=account.initial_cash,
        margin_excess=account.initial_cash,
        buying_power=account.initial_cash * 2,
        margin_status=MarginStatus.NORMAL,
    ).model_dump()


@router.get("/v1/accounts/{account_id}/positions")
async def get_positions(account_id: str, request: Request):
    session_svc = request.app.state.session_service
    for sid, state in session_svc._sessions.items():
        if state.account_id == account_id:
            return {
                "account_id": account_id,
                "ts": state.clock.current_ts,
                "positions": [p.model_dump() for p in state.ledger.positions_list()],
            }

    return {"account_id": account_id, "ts": "", "positions": []}


@router.get("/v1/accounts/{account_id}/orders")
async def get_account_orders(
    account_id: str,
    request: Request,
    session_id: str | None = None,
    status_in: str | None = None,
    limit: int | None = None,
):
    session_svc = request.app.state.session_service
    all_orders = []

    for sid, state in session_svc._sessions.items():
        if state.account_id == account_id:
            if session_id and sid != session_id:
                continue
            statuses = status_in.split(",") if status_in else None
            orders = state.order_manager.get_orders_filtered(
                session_id=sid, status_in=statuses
            )
            all_orders.extend([o.model_dump() for o in orders])

    if limit:
        all_orders = all_orders[:limit]

    return {"orders": all_orders}


@router.get("/v1/accounts/{account_id}/trades")
async def get_account_trades(
    account_id: str,
    request: Request,
    session_id: str | None = None,
    limit: int | None = None,
):
    session_svc = request.app.state.session_service
    all_trades = []

    for sid, state in session_svc._sessions.items():
        if state.account_id == account_id:
            if session_id and sid != session_id:
                continue
            trades = state.history.get_trades(session_id=sid, limit=limit)
            all_trades.extend(trades)

    if limit:
        all_trades = all_trades[:limit]

    return {"trades": all_trades}
