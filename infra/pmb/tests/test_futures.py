"""Futures: per-contract margin, daily variation margin, margin calls, liquidation."""

from datetime import datetime, timezone

import pytest

from domain.futures import DEFAULT_SPECS, root_of, session_date_of
from domain.ledger import Ledger
from domain.margin_engine import MarginEngine
from models.account import CreateAccountRequest, MarginConfig
from models.enums import EventType, InstrumentType, Market, MarginStatus, OrderType, Side
from models.instrument import Instrument
from models.market import FutureBar
from models.order import CreateOrderRequest, OrderSpec
from models.session import CreateSessionRequest, ExecutionConfig, Universe
from services.account_service import AccountService
from services.order_service import OrderService
from services.session_service import SessionService


def ns(iso: str) -> int:
    return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() * 1e9)


# ── pure accounting ──────────────────────────────────────────────────────

def test_root_and_session_date():
    assert [root_of(s) for s in ("ZNZ6", "ESZ26", "ZN", "CL.v.1", "M2KU6", "6EH7")] == \
        ["ZN", "ES", "ZN", "CL", "M2K", "6E"]
    # 17:59 ET is still the 2025-01-07 session; 18:00 ET opens 2025-01-08
    assert session_date_of(ns("2025-01-07T22:59:00")) == "2025-01-07"
    assert session_date_of(ns("2025-01-07T23:00:00")) == "2025-01-08"


def test_ledger_moves_only_fees_and_variation_margin_through_cash():
    led = Ledger(100_000)
    iid = "FUTURE:ZN"
    led.apply_fill(iid, InstrumentType.FUTURE, Side.BUY, 2, 110.0, fees=3.0, multiplier=1000)
    assert led.cash == 100_000 - 3.0                      # no notional paid
    led.update_market_prices({iid: 110.5})
    assert led.total_equity() == pytest.approx(100_000 - 3 + 2 * 0.5 * 1000)
    (vm,) = led.settle_futures({iid: 110.25}, "2025-01-07")
    assert vm["amount"] == pytest.approx(500.0) and led.cash == pytest.approx(100_497.0)
    assert led.positions[iid].basis_price == 110.25
    # equity is unchanged by the settlement itself
    led.update_market_prices({iid: 110.25})
    assert led.total_equity() == pytest.approx(100_497.0)
    realized = led.apply_fill(iid, InstrumentType.FUTURE, Side.SELL, 2, 110.5, fees=3.0, multiplier=1000)
    assert realized == pytest.approx(1000.0)               # from the trade price
    assert led.cash == pytest.approx(100_000 - 6 + 1000)    # cash got exactly the P&L
    assert iid not in led.positions


def test_ledger_flip_and_add_blend_the_basis():
    led = Ledger(50_000)
    iid = "FUTURE:CL"
    led.apply_fill(iid, InstrumentType.FUTURE, Side.SELL, 1, 80.0, 0.0, multiplier=1000)
    led.apply_fill(iid, InstrumentType.FUTURE, Side.SELL, 1, 82.0, 0.0, multiplier=1000)
    p = led.positions[iid]
    assert (p.qty, p.avg_price, p.basis_price) == (-2, 81.0, 81.0)
    led.apply_fill(iid, InstrumentType.FUTURE, Side.BUY, 3, 79.0, 0.0, multiplier=1000)
    p = led.positions[iid]
    assert (p.qty, p.avg_price, p.basis_price) == (1, 79.0, 79.0)
    assert led.cash == pytest.approx(50_000 + 2 * 2.0 * 1000)


def test_margin_per_contract_from_spec_or_override():
    eng = MarginEngine(MarginConfig())
    zn = DEFAULT_SPECS["ZN"]
    assert eng.future_initial_for_order("ZNZ6", 2, 110.0) == pytest.approx(2 * 110 * 1000 * zn.margin_rate * 1.1)
    eng = MarginEngine(MarginConfig(future_specs={"ZN": {"maintenance_margin": 2000},
                                                  "QQ": {"multiplier": 10, "margin_rate": 0.1}}))
    assert eng.future_initial_for_order("ZN", 1, 110.0) == pytest.approx(2200.0)
    assert eng.future_spec("ZNZ6").multiplier == 1000            # the rest of the built-in spec is kept
    assert eng.future_spec("QQZ6").multiplier == 10
    assert eng.future_spec("XYZ") is None


# ── a session: settlement, margin call, liquidation ──────────────────────

# 2025-01-07 (Tue) and 01-08 (Wed) are EST: 09:30 ET = 14:30 UTC, 18:00 ET = 23:00 UTC
BARS = [
    ("2025-01-07T14:30:00", 90.0),
    ("2025-01-07T14:31:00", 89.0),
    ("2025-01-07T21:59:00", 86.0),    # last bar of session 01-07
    ("2025-01-07T23:00:00", 86.2),    # 18:00 ET: session 01-08
    ("2025-01-08T21:59:00", 85.5),    # last bar of session 01-08
    ("2025-01-08T23:00:00", 85.6),    # session 01-09
]
SETTLES = {"2025-01-07": 86.0, "2025-01-08": 85.5}


class FakeUPQ:
    async def get_future_minute_bars(self, tickers, start, end):
        return [FutureBar(symbol="CL", root="CL", window_start_ns=ns(t), open=p, high=p, low=p, close=p,
                          volume=10, session_date=session_date_of(ns(t))) for t, p in BARS]

    async def get_future_daily_bars(self, tickers, start, end):
        return [FutureBar(symbol="CL", root="CL", window_start_ns=ns(d + "T00:00:00"), open=s, high=s, low=s,
                          close=s, volume=100, settle=s, session_date=d) for d, s in SETTLES.items()]

    async def get_future_quotes(self, symbol, start, end):
        return []


async def _session(cash=10_000.0):
    accounts = AccountService()
    account = accounts.create_account(CreateAccountRequest(initial_cash=cash, market=Market.US))
    svc = SessionService(FakeUPQ())
    sid, _ = await svc.create_session(CreateSessionRequest(
        account_id=account.account_id, start_ts="2025-01-07T00:00:00", end_ts="2025-01-09T12:00:00",
        universe=Universe(futures=["CL"]), execution_config=ExecutionConfig(slippage_bps=0.0),
    ), account)
    return svc, OrderService(svc), sid, account.account_id


def _buy(orders, sid, acct, qty=1, symbol="CL"):
    spec = OrderSpec(instrument=Instrument(type=InstrumentType.FUTURE, symbol=symbol), side=Side.BUY,
                     order_type=OrderType.MARKET, qty=qty)
    return orders.place_order(CreateOrderRequest(session_id=sid, account_id=acct, order=spec))


def _events(res, kind):
    return [e for e in res["events"] if e["type"] == kind.value]


@pytest.mark.asyncio
async def test_unknown_contract_and_initial_margin_are_checked():
    svc, orders, sid, acct = await _session()
    assert "no contract spec" in _buy(orders, sid, acct, symbol="QQZ6")["error"]
    # CL at 90: initial 90 * 1000 * 8% * 1.1 = 7,920 per contract; two need 15,840 > 10,000
    assert _buy(orders, sid, acct, qty=2)["ok"]
    res = svc.step(sid, 1)
    (rej,) = [e for e in _events(res, EventType.ORDER_EVENT) if e["payload"]["status"] == "REJECTED"]
    assert rej["payload"]["reason_code"] == "INSUFFICIENT_MARGIN"


@pytest.mark.asyncio
async def test_variation_margin_call_and_liquidation():
    svc, orders, sid, acct = await _session()
    _buy(orders, sid, acct)
    state = svc.get_session(sid)
    res = svc.step(sid, 1)                                   # filled at 90.00
    assert _events(res, EventType.TRADE_EVENT)[0]["payload"]["price"] == 90.0
    assert state.ledger.cash == pytest.approx(10_000 - 1.5)

    res = svc.step(sid, 2)                                   # ... to the 01-07 settlement at 86
    (vm,) = _events(res, EventType.VARIATION_MARGIN)
    assert vm["payload"]["amount"] == pytest.approx(-4000.0) and vm["payload"]["session_date"] == "2025-01-07"
    assert state.ledger.cash == pytest.approx(5998.5)
    # equity 5,998.5 < maintenance 86 * 1000 * 8% = 6,880: margin call, new positions refused
    assert state.margin_engine.margin_status == MarginStatus.MARGIN_CALL
    risk = _events(res, EventType.RISK_EVENT)[-1]["payload"]
    assert risk["level"] == "MARGIN_CALL" and risk["call_amount"] == pytest.approx(6880 * 1.1 - 5998.5)
    _buy(orders, sid, acct)
    res = svc.step(sid, 1)
    assert any(e["payload"]["reason_code"] == "MARGIN_RESTRICTED" for e in _events(res, EventType.ORDER_EVENT))

    res = svc.step(sid, 1)                                   # 01-08 settlement: the call is still open
    (vm,) = _events(res, EventType.VARIATION_MARGIN)
    assert vm["payload"]["amount"] == pytest.approx(-500.0)
    liq = [e for e in _events(res, EventType.RISK_EVENT) if e["payload"]["level"] == "LIQUIDATION"]
    assert liq and liq[0]["payload"]["action"] == "LIQUIDATE_FUTURES"
    (fill,) = [e for e in _events(res, EventType.TRADE_EVENT) if e["payload"]["order_id"] == "LIQUIDATION"]
    assert fill["payload"]["side"] == "SELL" and fill["payload"]["price"] == 85.5
    assert not state.ledger.future_positions()
    # every dollar of the -4,500 loss went through cash, plus 2 x 1.50 fees
    assert state.ledger.cash == pytest.approx(10_000 - 4500 - 3.0)
    assert state.ledger.realized_pnl == pytest.approx(-4500.0)
    snap = svc.get_full_state(sid)
    assert snap["futures_specs"]["CL"]["multiplier"] == 1000
    assert snap["account"]["margin_status"] == "NORMAL"


@pytest.mark.asyncio
async def test_checkpoint_keeps_futures_basis_and_call_state():
    svc, orders, sid, acct = await _session(cash=50_000)
    _buy(orders, sid, acct)
    svc.step(sid, 3)                                         # settled at 86
    cp = svc.export_checkpoint(sid)
    assert cp["config"]["universe"]["futures"] == ["CL"]
    (pos,) = cp["ledger"]["positions"]
    assert pos["basis_price"] == 86.0 and pos["multiplier"] == 1000 and pos["last_settle_date"] == "2025-01-07"
