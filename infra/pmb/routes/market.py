from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["market"])


@router.get("/v1/sessions/{session_id}/market")
async def get_market_snapshot(session_id: str, request: Request):
    session_svc = request.app.state.session_service
    state = session_svc.get_session(session_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "session not found"},
        )

    ts_ns = state.clock.current_ns
    if ts_ns is None:
        return {"ts": "", "stocks": [], "options": []}

    stock_bars = state.cache.get_stock_bars_at(ts_ns)
    option_bars = state.cache.get_option_bars_at(ts_ns)

    stocks = []
    for sym, bar in stock_bars.items():
        stocks.append(
            {
                "symbol": sym,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
        )

    options = []
    for contract, bar in option_bars.items():
        options.append(
            {
                "contract": contract,
                "close": bar.close,
                "volume": bar.volume,
            }
        )

    return {
        "ts": state.clock.current_ts,
        "stocks": stocks,
        "options": options,
    }
