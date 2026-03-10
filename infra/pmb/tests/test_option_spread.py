"""Tests for option bid-ask spread modeling in ExecutionEngine."""

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


def _make_engine(option_spread_pct=0.0, slippage_bps=0.0):
    return ExecutionEngine(
        seed=42, slippage_bps=slippage_bps,
        fee_model=FeeModel(), option_spread_pct=option_spread_pct,
    )


def _submit_and_accept(om, instrument, side, qty=1):
    req = CreateOrderRequest(
        session_id="s1", account_id="a1", client_order_id=f"ord_{side.value}_{instrument.contract or instrument.symbol}",
        order=OrderSpec(
            instrument=instrument,
            side=side, order_type=OrderType.MARKET, qty=qty,
        ),
    )
    order, _ = om.submit(req, "2024-01-02")
    om.accept(order.order_id, "2024-01-02")
    return order


def test_option_spread_buy_increases_fill_price():
    """Buying an option with spread should fill above bar.open."""
    engine = _make_engine(option_spread_pct=0.10)  # 10% spread
    ledger = Ledger(initial_cash=100_000.0)
    om = OrderManager()
    me = MarginEngine(MarginConfig())

    option_bars = {
        "O:TEST240119C00100000": OptionBar(
            contract="O:TEST240119C00100000", window_start_ns=0,
            open=2.00, high=2.50, low=1.50, close=2.00, volume=100,
        ),
    }

    order = _submit_and_accept(
        om,
        Instrument(type=InstrumentType.OPTION, contract="O:TEST240119C00100000"),
        Side.BUY,
    )

    events, trades = engine.process_step("2024-01-02", 0, {}, option_bars, om, ledger, me)

    assert len(trades) == 1
    # open=2.00, half_spread = 2.00 * 0.10 / 2 = 0.10
    # fill should be 2.00 + 0.10 = 2.10
    assert trades[0].price == 2.10


def test_option_spread_sell_decreases_fill_price():
    """Selling an option with spread should fill below bar.open."""
    engine = _make_engine(option_spread_pct=0.10)
    ledger = Ledger(initial_cash=100_000.0)
    om = OrderManager()
    me = MarginEngine(MarginConfig())

    # First buy the option so we can sell it (closing trade)
    ledger.apply_fill("OPTION:O:TEST240119C00100000", InstrumentType.OPTION, Side.BUY, 1, 2.00, 0.0)

    option_bars = {
        "O:TEST240119C00100000": OptionBar(
            contract="O:TEST240119C00100000", window_start_ns=0,
            open=2.00, high=2.50, low=1.50, close=2.00, volume=100,
        ),
    }

    order = _submit_and_accept(
        om,
        Instrument(type=InstrumentType.OPTION, contract="O:TEST240119C00100000"),
        Side.SELL,
    )

    events, trades = engine.process_step("2024-01-02", 0, {}, option_bars, om, ledger, me)

    assert len(trades) == 1
    # open=2.00, half_spread = 2.00 * 0.10 / 2 = 0.10
    # fill should be 2.00 - 0.10 = 1.90
    assert trades[0].price == 1.90


def test_option_spread_zero_no_effect():
    """With spread_pct=0, option fill should be bar.open (same as before)."""
    engine = _make_engine(option_spread_pct=0.0)
    ledger = Ledger(initial_cash=100_000.0)
    om = OrderManager()
    me = MarginEngine(MarginConfig())

    option_bars = {
        "O:TEST240119C00100000": OptionBar(
            contract="O:TEST240119C00100000", window_start_ns=0,
            open=3.50, high=4.00, low=3.00, close=3.50, volume=100,
        ),
    }

    order = _submit_and_accept(
        om,
        Instrument(type=InstrumentType.OPTION, contract="O:TEST240119C00100000"),
        Side.BUY,
    )

    events, trades = engine.process_step("2024-01-02", 0, {}, option_bars, om, ledger, me)

    assert len(trades) == 1
    assert trades[0].price == 3.50  # exactly bar.open, no spread


def test_stock_unaffected_by_option_spread():
    """Stock orders should not be affected by option_spread_pct."""
    engine = _make_engine(option_spread_pct=0.10)
    ledger = Ledger(initial_cash=100_000.0)
    om = OrderManager()
    me = MarginEngine(MarginConfig())

    stock_bars = {
        "AAPL": StockBar(
            symbol="AAPL", window_start_ns=0,
            open=150.00, high=155.00, low=148.00, close=152.00, volume=1000,
        ),
    }

    order = _submit_and_accept(
        om,
        Instrument(type=InstrumentType.STOCK, symbol="AAPL"),
        Side.BUY, qty=100,
    )

    events, trades = engine.process_step("2024-01-02", 0, stock_bars, {}, om, ledger, me)

    assert len(trades) == 1
    assert trades[0].price == 150.00  # bar.open, no spread applied


def test_option_spread_cheap_otm():
    """Cheap OTM option ($0.05) with 5% spread: half_spread = $0.00125."""
    engine = _make_engine(option_spread_pct=0.05)
    ledger = Ledger(initial_cash=100_000.0)
    om = OrderManager()
    me = MarginEngine(MarginConfig())

    option_bars = {
        "O:QQQ240119C00500000": OptionBar(
            contract="O:QQQ240119C00500000", window_start_ns=0,
            open=0.05, high=0.06, low=0.04, close=0.05, volume=50,
        ),
    }

    order = _submit_and_accept(
        om,
        Instrument(type=InstrumentType.OPTION, contract="O:QQQ240119C00500000"),
        Side.BUY,
    )

    events, trades = engine.process_step("2024-01-02", 0, {}, option_bars, om, ledger, me)

    assert len(trades) == 1
    # open=0.05, half_spread = 0.05 * 0.05 / 2 = 0.00125
    # fill = 0.05 + 0.00125 = 0.05125 → rounded to 0.0513
    assert trades[0].price == 0.0513


def test_option_spread_combined_with_slippage():
    """Spread and slippage should both apply to option fills."""
    # Use seed=0, slippage_bps=10 (1 bps = 0.01%) for predictable test
    engine = _make_engine(option_spread_pct=0.10, slippage_bps=0.0)
    ledger = Ledger(initial_cash=100_000.0)
    om = OrderManager()
    me = MarginEngine(MarginConfig())

    option_bars = {
        "O:TEST240119C00100000": OptionBar(
            contract="O:TEST240119C00100000", window_start_ns=0,
            open=4.00, high=4.50, low=3.50, close=4.00, volume=100,
        ),
    }

    order = _submit_and_accept(
        om,
        Instrument(type=InstrumentType.OPTION, contract="O:TEST240119C00100000"),
        Side.BUY,
    )

    events, trades = engine.process_step("2024-01-02", 0, {}, option_bars, om, ledger, me)

    assert len(trades) == 1
    # With slippage_bps=0: slippage_price = 4.00
    # half_spread = 4.00 * 0.10 / 2 = 0.20
    # fill = 4.00 + 0.20 = 4.20
    assert trades[0].price == 4.20
