import json
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from models.account import CreateAccountRequest
from models.enums import InstrumentType, Market
from models.market import StockBar
from models.position import Position
from models.session import CreateSessionRequest
from services.account_service import AccountService
from services.session_service import SessionService
from routes.sessions import router as sessions_router


class FakeUPQ:
    async def get_stock_minute_bars(self, tickers, start, end):
        bars = [
            StockBar(
                symbol="SPY",
                window_start_ns=ns,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=100,
            )
            for ns, price in [
                (1_000_000_000, 500),
                (2_000_000_000, 501),
                (3_000_000_000, 502),
            ]
        ]
        if "QQQ" in tickers:
            bars.append(
                StockBar(
                    symbol="QQQ",
                    window_start_ns=2_500_000_000,
                    open=400,
                    high=400,
                    low=400,
                    close=400,
                    volume=100,
                )
            )
        return bars

    async def get_option_minute_bars(self, contract, start, end):
        return []


@pytest.mark.asyncio
async def test_checkpoint_round_trip_creates_independent_session():
    accounts = AccountService()
    source_account = accounts.create_account(
        CreateAccountRequest(
            initial_cash=100_000,
            market=Market.US,
            start_date="2025-01-02",
        )
    )
    service = SessionService(FakeUPQ())
    session_id, _ = await service.create_session(
        CreateSessionRequest(
            account_id=source_account.account_id,
            frequency="1m",
            start_ts="1970-01-01T00:00:01+00:00",
            end_ts="1970-01-01T00:00:03+00:00",
            universe={"stocks": ["SPY"], "options": []},
        ),
        source_account,
    )
    service.step(session_id)
    await service.add_stocks(session_id, ["QQQ"])
    source = service.get_session(session_id)
    source.ledger._cash = 98_750.0
    source.ledger._positions["STOCK:SPY"] = Position(
        instrument_id="STOCK:SPY",
        type=InstrumentType.STOCK,
        qty=5,
        avg_price=500,
        mark_price=501,
    )
    source.action_log.append(
        {"seq": 0, "index": 0, "ts": source.clock.current_ts, "kind": "cancel", "order_id": "missing"}
    )

    exported_account = json.loads(source_account.model_dump_json())
    checkpoint = json.loads(json.dumps(service.export_checkpoint(session_id)))
    restored_account = accounts.restore_account(exported_account)
    restored_id, _ = await service.restore_checkpoint(checkpoint, restored_account)
    restored = service.get_session(restored_id)

    assert restored_id != session_id
    assert restored.account_id != source.account_id
    assert restored.clock.current_ns == source.clock.current_ns
    assert restored.clock._timestamps == source.clock._timestamps
    assert restored.ledger.cash == 98_750.0
    assert restored.ledger.positions["STOCK:SPY"].qty == 5
    assert restored.action_log == source.action_log
    assert service.step(restored_id)["clock"]["current_ts"] != ""


@pytest.mark.asyncio
async def test_restore_rejects_clock_missing_from_market_data():
    accounts = AccountService()
    account = accounts.create_account(
        CreateAccountRequest(initial_cash=100_000, market=Market.US)
    )
    service = SessionService(FakeUPQ())
    session_id, _ = await service.create_session(
        CreateSessionRequest(
            account_id=account.account_id,
            frequency="1m",
            start_ts="1970-01-01T00:00:01+00:00",
            end_ts="1970-01-01T00:00:03+00:00",
            universe={"stocks": ["SPY"], "options": []},
        ),
        account,
    )
    checkpoint = service.export_checkpoint(session_id)
    checkpoint["clock_current_ns"] = 999
    restored_account = accounts.restore_account(json.loads(account.model_dump_json()))

    with pytest.raises(ValueError, match="clock is absent"):
        await service.restore_checkpoint(checkpoint, restored_account)

    assert len(service._sessions) == 1


def test_checkpoint_http_routes_restore_account_and_session():
    accounts = AccountService()
    source_account = accounts.create_account(
        CreateAccountRequest(
            initial_cash=50_000,
            market=Market.US,
            start_date="2025-01-02",
        )
    )
    source_account.cash = 49_500
    sessions = SessionService(FakeUPQ())
    session_id, _ = asyncio.run(
        sessions.create_session(
            CreateSessionRequest(
                account_id=source_account.account_id,
                frequency="1m",
                start_ts="1970-01-01T00:00:01+00:00",
                end_ts="1970-01-01T00:00:03+00:00",
                universe={"stocks": ["SPY"], "options": []},
            ),
            source_account,
        )
    )
    sessions.step(session_id)

    app = FastAPI()
    app.state.account_service = accounts
    app.state.session_service = sessions
    app.include_router(sessions_router)

    with TestClient(app) as client:
        exported = client.get(f"/v1/sessions/{session_id}/checkpoint")
        assert exported.status_code == 200
        restored = client.post("/v1/sessions/restore", json=exported.json())

    assert restored.status_code == 200, restored.text
    result = restored.json()
    assert result["session_id"] != session_id
    assert result["account_id"] != source_account.account_id
    assert accounts.get_account(result["account_id"]).cash == 49_500
    assert sessions.get_session(result["session_id"]).clock.current_ns == 1_000_000_000
