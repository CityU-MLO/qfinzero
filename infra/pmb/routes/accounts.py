from fastapi import APIRouter, HTTPException, Request

from models.account import (
    CreateAccountRequest,
    AccountState,
    TradeRequest,
    NextDayRequest,
)
from models.enums import MarginStatus
from services.account_service import FrozenAccountError, AccountClosedError

router = APIRouter(tags=["accounts"])


def _svc(request: Request):
    return request.app.state.account_service


def _require_status(request: Request, account_id: str) -> dict:
    status = _svc(request).status_view(account_id)
    if status is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "account not found"},
        )
    return status


async def _latest_daily_closes(request: Request, symbols: list[str], as_of_date: str) -> dict[str, float]:
    """Latest UPQ daily close per stock symbol at/before as_of_date (real prices)."""
    from datetime import datetime, timedelta

    upq = getattr(request.app.state, "upq", None)
    stocks = [s.upper() for s in symbols if not s.upper().startswith("O:")]
    if upq is None or not stocks:
        return {}
    end = as_of_date[:10]
    try:
        start = (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=10)).date().isoformat()
        bars = await upq.get_stock_daily_bars(stocks, start, end)
    except Exception:  # noqa: BLE001 — pricing is best-effort
        return {}
    best: dict[str, tuple[int, float]] = {}
    for b in bars:
        if b.symbol not in best or b.window_start_ns > best[b.symbol][0]:
            best[b.symbol] = (b.window_start_ns, b.close)
    return {s: px for s, (_, px) in best.items()}


async def _market_price(request: Request, symbol: str, as_of_date: str, rule: str) -> float | None:
    """A single symbol's UPQ market price (close or open) at/before as_of_date."""
    from datetime import datetime, timedelta

    upq = getattr(request.app.state, "upq", None)
    if upq is None or symbol.upper().startswith("O:"):
        return None
    end = as_of_date[:10]
    try:
        start = (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=10)).date().isoformat()
        bars = await upq.get_stock_daily_bars([symbol.upper()], start, end)
    except Exception:  # noqa: BLE001
        return None
    if not bars:
        return None
    bar = max(bars, key=lambda b: b.window_start_ns)
    return bar.open if rule == "open" else bar.close


async def _mark_from_upq(request: Request, account_id: str) -> None:
    """Mark held stock positions to the real UPQ price so unrealized P&L is live."""
    svc = _svc(request)
    account = svc.get_account(account_id)
    cfg = getattr(request.app.state, "pmb_config", {}) or {}
    if account is None or not account.positions or not cfg.get("auto_price_from_upq", True):
        return
    prices = await _latest_daily_closes(request, list(account.positions), account.current_date)
    if prices:
        svc.mark_prices(account_id, prices)


# ── Allocation & status ────────────────────────────────────────────────


@router.post("/v1/accounts")
async def create_account(req: CreateAccountRequest, request: Request):
    # fill unset fields from the broker config (single settings surface)
    cfg = getattr(request.app.state, "pmb_config", {}) or {}
    if req.initial_cash is None:
        req.initial_cash = float(cfg.get("initial_cash", 100_000.0))
    if req.market is None:
        from models.enums import Market
        try:
            req.market = Market(str(cfg.get("default_market", "us")).lower())
        except ValueError:
            req.market = Market.US
    account = _svc(request).create_account(req)
    status = _svc(request).status_view(account.account_id)
    return {
        "ok": True,
        "account_id": account.account_id,
        "market": account.market.value,
        "created_at": account.created_at,
        # full broker status under both keys for convenience / back-compat
        "account_state": status,
        "account": status,
    }


@router.get("/v1/accounts/{account_id}")
async def get_account(account_id: str, request: Request):
    account_svc = _svc(request)
    account = account_svc.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "account not found"})

    # Back-compat: if a backtest session is attached, surface its live ledger
    # snapshot (enriched with broker metadata) as before.
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
            data = snapshot.model_dump()
            data.update(
                {
                    "account_id": account_id,
                    "market": account.market.value,
                    "status": account.status.value,
                    "trading_day": account.trading_day,
                    "open_date": account.open_date,
                    "current_date": account.current_date,
                    "session_id": sid,
                }
            )
            return data

    # Otherwise the broker book is the source of truth.
    return account_svc.status_view(account_id)


@router.get("/v1/accounts/{account_id}/status")
async def get_account_status(account_id: str, request: Request):
    """Canonical broker status — what an agent queries from its account id."""
    await _mark_from_upq(request, account_id)
    return _require_status(request, account_id)


@router.get("/v1/accounts/{account_id}/history")
async def get_account_history(account_id: str, request: Request, limit: int | None = None):
    """Step-by-step trading history (one record per closed trading day)."""
    history = _svc(request).history_view(account_id, limit=limit)
    if history is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "account not found"},
        )
    return {"account_id": account_id, "days": history, "count": len(history)}


# ── Trading & day gating ───────────────────────────────────────────────


@router.post("/v1/accounts/{account_id}/trade")
async def place_trade(account_id: str, req: TradeRequest, request: Request):
    svc = _svc(request)
    account = svc.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "account not found"})

    cfg = getattr(request.app.state, "pmb_config", {}) or {}
    price = req.price
    price_source = "supplied"
    # When the agent omits a price, execute at the real UPQ market price for the
    # account's current trading day — so the broker is linked to real data, not
    # an agent-chosen price.
    if price is None:
        if not cfg.get("auto_price_from_upq", True):
            raise HTTPException(status_code=400, detail={"code": "invalid_argument", "message": "price is required (auto pricing disabled)"})
        price = await _market_price(request, req.symbol, account.current_date, str(cfg.get("price_rule", "close")))
        if price is None:
            raise HTTPException(status_code=422, detail={
                "code": "no_market_data",
                "message": f"no UPQ price for {req.symbol.upper()} at {account.current_date[:10]}",
            })
        price_source = f"upq:{cfg.get('price_rule', 'close')}"

    try:
        fill = svc.trade(account_id, req.symbol, req.side, req.qty, price, req.note)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "account not found"})
    except FrozenAccountError as e:
        raise HTTPException(status_code=409, detail={"code": "frozen", "message": str(e)})
    except AccountClosedError:
        raise HTTPException(status_code=409, detail={"code": "closed", "message": "account is closed"})
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "invalid_argument", "message": str(e)})

    await _mark_from_upq(request, account_id)
    return {"ok": True, "fill": fill.model_dump(), "price_source": price_source, "account": svc.status_view(account_id)}


@router.post("/v1/accounts/{account_id}/end_day")
async def end_day(account_id: str, request: Request):
    """Close the trading day and freeze the account until next_day."""
    try:
        record = _svc(request).end_day(account_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "account not found"})
    except AccountClosedError:
        raise HTTPException(status_code=409, detail={"code": "closed", "message": "account is closed"})
    return {"ok": True, "day": record.model_dump(), "account": _svc(request).status_view(account_id)}


@router.post("/v1/accounts/{account_id}/next_day")
async def next_day(account_id: str, request: Request, req: NextDayRequest | None = None):
    """Unfreeze and advance to the next trading day. Body is optional."""
    date = req.date if req else None
    try:
        account = _svc(request).next_day(account_id, date)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "account not found"})
    except AccountClosedError:
        raise HTTPException(status_code=409, detail={"code": "closed", "message": "account is closed"})
    return {"ok": True, "account": _svc(request).status_view(account.account_id)}


@router.post("/v1/accounts/{account_id}/close")
async def close_account(account_id: str, request: Request):
    try:
        account = _svc(request).close_account(account_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "account not found"})
    return {"ok": True, "account": _svc(request).status_view(account.account_id)}


# ── Session-derived views (unchanged) ──────────────────────────────────


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

    # No session: fall back to the broker book's positions.
    account = _svc(request).get_account(account_id)
    if account is not None:
        return {
            "account_id": account_id,
            "ts": account.current_date,
            "positions": [p.to_view() for p in account.open_positions()],
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
