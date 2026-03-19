"""Tests for atomic spread execution in ExecutionEngine."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from domain.execution_engine import ExecutionEngine
from domain.ledger import Ledger
from domain.order_manager import OrderManager
from domain.margin_engine import MarginEngine
from models.order import CreateOrderRequest, OrderSpec
from models.instrument import Instrument
from models.enums import Side, OrderType, InstrumentType, OrderStatus
from models.session import FeeModel
from models.account import MarginConfig
from models.market import StockBar, OptionBar


def _make_engine():
    return ExecutionEngine(seed=42, slippage_bps=0.0, fee_model=FeeModel())


def test_spread_execution_fills_both_legs_atomically():
    """Both legs of a spread should fill in the same tick."""
    engine = _make_engine()
    ledger = Ledger(initial_cash=100_000.0)
    om = OrderManager()
    me = MarginEngine(MarginConfig())

    option_bars = {
        "O:QQQ240119P00390000": OptionBar(contract="O:QQQ240119P00390000", window_start_ns=0, open=5.0, high=5.5, low=4.5, close=5.0, volume=100),
        "O:QQQ240119P00380000": OptionBar(contract="O:QQQ240119P00380000", window_start_ns=0, open=2.0, high=2.5, low=1.5, close=2.0, volume=100),
    }

    # Submit two linked orders (buy long put, sell short put)
    req1 = CreateOrderRequest(
        session_id="s1", account_id="a1", client_order_id="spread_leg1",
        order=OrderSpec(
            instrument=Instrument(type=InstrumentType.OPTION, contract="O:QQQ240119P00390000"),
            side=Side.BUY, order_type=OrderType.MARKET, qty=1,
        ),
        spread_id="spread_001",
    )
    req2 = CreateOrderRequest(
        session_id="s1", account_id="a1", client_order_id="spread_leg2",
        order=OrderSpec(
            instrument=Instrument(type=InstrumentType.OPTION, contract="O:QQQ240119P00380000"),
            side=Side.SELL, order_type=OrderType.MARKET, qty=1,
        ),
        spread_id="spread_001",
    )
    o1, _ = om.submit(req1, "2024-01-02")
    om.accept(o1.order_id, "2024-01-02")
    o2, _ = om.submit(req2, "2024-01-02")
    om.accept(o2.order_id, "2024-01-02")

    events, trades = engine.process_step(
        "2024-01-02", 0, {}, option_bars, om, ledger, me)

    # Both should be filled
    assert om.get_order(o1.order_id).status == OrderStatus.FILLED
    assert om.get_order(o2.order_id).status == OrderStatus.FILLED
    assert len(trades) == 2

    # Net cash impact: bought put at $5×100 (-$500), sold put at $2×100 (+$200) = -$300 net debit
    # Plus fees: 1×$0.65 buy + 1×$0.65 sell = $1.30
    # Cash = 100000 - 500 + 200 - 1.30 = 99698.70
    assert ledger.cash < 100_000.0
    assert abs(ledger.cash - 99698.70) < 1.0


def test_spread_and_individual_orders_process_together():
    """Spread orders and individual orders should both be processed in one step."""
    engine = _make_engine()
    ledger = Ledger(initial_cash=200_000.0)
    om = OrderManager()
    me = MarginEngine(MarginConfig())

    stock_bars = {"AAPL": StockBar(symbol="AAPL", window_start_ns=0, open=150.0, high=155.0, low=148.0, close=152.0, volume=1000)}
    option_bars = {
        "O:QQQ240119P00390000": OptionBar(contract="O:QQQ240119P00390000", window_start_ns=0, open=5.0, high=5.5, low=4.5, close=5.0, volume=100),
        "O:QQQ240119P00380000": OptionBar(contract="O:QQQ240119P00380000", window_start_ns=0, open=2.0, high=2.5, low=1.5, close=2.0, volume=100),
    }

    # Individual stock order
    req_stock = CreateOrderRequest(
        session_id="s1", account_id="a1", client_order_id="stock_buy",
        order=OrderSpec(
            instrument=Instrument(type=InstrumentType.STOCK, symbol="AAPL"),
            side=Side.BUY, order_type=OrderType.MARKET, qty=10,
        ),
    )
    o_stock, _ = om.submit(req_stock, "2024-01-02")
    om.accept(o_stock.order_id, "2024-01-02")

    # Spread orders
    req1 = CreateOrderRequest(
        session_id="s1", account_id="a1", client_order_id="spread_leg1",
        order=OrderSpec(
            instrument=Instrument(type=InstrumentType.OPTION, contract="O:QQQ240119P00390000"),
            side=Side.BUY, order_type=OrderType.MARKET, qty=1,
        ),
        spread_id="spread_002",
    )
    req2 = CreateOrderRequest(
        session_id="s1", account_id="a1", client_order_id="spread_leg2",
        order=OrderSpec(
            instrument=Instrument(type=InstrumentType.OPTION, contract="O:QQQ240119P00380000"),
            side=Side.SELL, order_type=OrderType.MARKET, qty=1,
        ),
        spread_id="spread_002",
    )
    o1, _ = om.submit(req1, "2024-01-02")
    om.accept(o1.order_id, "2024-01-02")
    o2, _ = om.submit(req2, "2024-01-02")
    om.accept(o2.order_id, "2024-01-02")

    events, trades = engine.process_step(
        "2024-01-02", 0, stock_bars, option_bars, om, ledger, me)

    # All 3 orders should fill
    assert om.get_order(o_stock.order_id).status == OrderStatus.FILLED
    assert om.get_order(o1.order_id).status == OrderStatus.FILLED
    assert om.get_order(o2.order_id).status == OrderStatus.FILLED
    assert len(trades) == 3


def test_spread_skipped_if_one_leg_has_no_bar():
    """If one leg has no market data, entire spread is skipped (not rejected)."""
    engine = _make_engine()
    ledger = Ledger(initial_cash=100_000.0)
    om = OrderManager()
    me = MarginEngine(MarginConfig())

    # Only provide bar for one leg
    option_bars = {
        "O:QQQ240119P00390000": OptionBar(contract="O:QQQ240119P00390000", window_start_ns=0, open=5.0, high=5.5, low=4.5, close=5.0, volume=100),
        # Missing: O:QQQ240119P00380000
    }

    req1 = CreateOrderRequest(
        session_id="s1", account_id="a1", client_order_id="leg1",
        order=OrderSpec(
            instrument=Instrument(type=InstrumentType.OPTION, contract="O:QQQ240119P00390000"),
            side=Side.BUY, order_type=OrderType.MARKET, qty=1,
        ),
        spread_id="spread_003",
    )
    req2 = CreateOrderRequest(
        session_id="s1", account_id="a1", client_order_id="leg2",
        order=OrderSpec(
            instrument=Instrument(type=InstrumentType.OPTION, contract="O:QQQ240119P00380000"),
            side=Side.SELL, order_type=OrderType.MARKET, qty=1,
        ),
        spread_id="spread_003",
    )
    o1, _ = om.submit(req1, "2024-01-02")
    om.accept(o1.order_id, "2024-01-02")
    o2, _ = om.submit(req2, "2024-01-02")
    om.accept(o2.order_id, "2024-01-02")

    events, trades = engine.process_step(
        "2024-01-02", 0, {}, option_bars, om, ledger, me)

    # Both should still be open (not rejected, not filled)
    assert om.get_order(o1.order_id).status == OrderStatus.ACCEPTED
    assert om.get_order(o2.order_id).status == OrderStatus.ACCEPTED
    assert len(trades) == 0
    assert ledger.cash == 100_000.0  # No change
