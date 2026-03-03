"""Tests for PMB execution engine — domain-level unit tests.

These tests exercise the execution engine and session tick processing
directly, without HTTP or MCP layers.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "infra", "pmb"))

from domain.execution_engine import ExecutionEngine
from domain.ledger import Ledger
from domain.order_manager import OrderManager
from domain.margin_engine import MarginEngine
from models.account import MarginConfig
from models.enums import Side, OrderType, OrderStatus, InstrumentType, TimeInForce
from models.market import StockBar
from models.order import Order
from models.session import FeeModel


# ── Helpers ──────────────────────────────────────────────────────────


def _make_bar(
    symbol: str = "NVDA",
    open: float = 191.76,
    high: float = 193.63,
    low: float = 186.15,
    close: float = 188.12,
    volume: int = 183_000_000,
    ns: int = 1_000_000_000,
) -> StockBar:
    return StockBar(
        symbol=symbol,
        window_start_ns=ns,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _make_order(
    instrument_id: str = "STOCK:NVDA",
    side: Side = Side.BUY,
    order_type: OrderType = OrderType.MARKET,
    qty: int = 100,
    limit_price: float | None = None,
    stop_price: float | None = None,
) -> Order:
    return Order(
        order_id="ord_test",
        session_id="sess_test",
        account_id="acct_test",
        instrument_id=instrument_id,
        side=side,
        order_type=order_type,
        qty=qty,
        remaining_qty=qty,
        limit_price=limit_price,
        stop_price=stop_price,
        time_in_force=TimeInForce.DAY,
        status=OrderStatus.NEW,
    )


def _make_engine(seed: int = 42, slippage_bps: float = 0.0) -> ExecutionEngine:
    return ExecutionEngine(
        seed=seed,
        slippage_bps=slippage_bps,
        fee_model=FeeModel(stock_fee_per_share=0.0, option_fee_per_contract=0.0),
    )


def _make_margin_engine() -> MarginEngine:
    return MarginEngine(config=MarginConfig())


# ═══════════════════════════════════════════════════════════════════
# Bug 2: MARKET order should fill at open price, not close price
# ═══════════════════════════════════════════════════════════════════


class TestMarketOrderFillPrice:
    """MARKET orders should fill at bar.open (+ slippage), not bar.close."""

    def test_market_buy_fills_at_open_price(self):
        """A MARKET BUY should fill at the bar's open price, not close."""
        engine = _make_engine(slippage_bps=0.0)
        bar = _make_bar(open=191.76, close=188.12)

        order = _make_order(side=Side.BUY, order_type=OrderType.MARKET)
        fill_price = engine._calculate_fill_price(bar, order)

        assert fill_price == 191.76, (
            f"MARKET BUY should fill at open ({bar.open}), got {fill_price}"
        )

    def test_market_sell_fills_at_open_price(self):
        """A MARKET SELL should fill at the bar's open price, not close."""
        engine = _make_engine(slippage_bps=0.0)
        bar = _make_bar(open=191.76, close=188.12)

        order = _make_order(side=Side.SELL, order_type=OrderType.MARKET)
        fill_price = engine._calculate_fill_price(bar, order)

        assert fill_price == 191.76, (
            f"MARKET SELL should fill at open ({bar.open}), got {fill_price}"
        )

    def test_market_buy_with_slippage_based_on_open(self):
        """Slippage should be applied on top of open price for MARKET BUY."""
        engine = _make_engine(seed=42, slippage_bps=2.0)
        bar = _make_bar(open=100.00, close=99.00)

        order = _make_order(side=Side.BUY, order_type=OrderType.MARKET)
        fill_price = engine._calculate_fill_price(bar, order)

        # BUY slippage: price * (1 + bps/10000), bps in [0, 2]
        # fill should be >= open and < open * 1.0002
        assert fill_price >= 100.00, "Fill should be >= open for BUY"
        assert fill_price <= 100.02, "Fill should be <= open * 1.0002"

    def test_market_sell_with_slippage_based_on_open(self):
        """Slippage should be applied on top of open price for MARKET SELL."""
        engine = _make_engine(seed=42, slippage_bps=2.0)
        bar = _make_bar(open=100.00, close=99.00)

        order = _make_order(side=Side.SELL, order_type=OrderType.MARKET)
        fill_price = engine._calculate_fill_price(bar, order)

        # SELL slippage: price * (1 - bps/10000), bps in [0, 2]
        assert fill_price <= 100.00, "Fill should be <= open for SELL"
        assert fill_price >= 99.98, "Fill should be >= open * 0.9998"


# ═══════════════════════════════════════════════════════════════════
# Bug 1: mark_price must update to bar close after fill
# ═══════════════════════════════════════════════════════════════════


class TestMarkPriceAfterFill:
    """After execution, positions should be marked to bar close, not fill price."""

    def test_new_position_mark_price_equals_close_after_fill(self):
        """When a fill creates a new position, mark_price should be bar close,
        not the fill price."""
        engine = _make_engine(slippage_bps=0.0)
        ledger = Ledger(initial_cash=100_000.0)
        order_mgr = OrderManager()
        margin_engine = _make_margin_engine()

        bar = _make_bar(open=191.76, close=188.12)
        stock_bars = {"NVDA": bar}

        # Submit a MARKET BUY order
        from models.order import CreateOrderRequest, OrderSpec
        from models.instrument import Instrument

        req = CreateOrderRequest(
            session_id="sess_test",
            account_id="acct_test",
            order=OrderSpec(
                instrument=Instrument(type="STOCK", symbol="NVDA"),
                side=Side.BUY,
                order_type=OrderType.MARKET,
                qty=100,
            ),
        )
        order_mgr.submit(req, ts="2026-01-05T00:00:00+00:00")

        # Execute
        engine.process_step(
            ts="2026-01-05T00:00:00+00:00",
            ts_ns=1_000_000_000,
            stock_bars=stock_bars,
            option_bars={},
            order_manager=order_mgr,
            ledger=ledger,
            margin_engine=margin_engine,
        )

        # After execution, mark-to-market should be applied
        prices = {f"STOCK:{sym}": b.close for sym, b in stock_bars.items()}
        ledger.update_market_prices(prices)

        pos = ledger.positions["STOCK:NVDA"]
        assert pos.mark_price == 188.12, (
            f"mark_price should be bar close (188.12), got {pos.mark_price}"
        )
        expected_pnl = 100 * (188.12 - pos.avg_price)
        assert abs(pos.unrealized_pnl - expected_pnl) < 0.01, (
            f"unrealized_pnl should be {expected_pnl:.2f}, got {pos.unrealized_pnl:.2f}"
        )

    def test_equity_reflects_market_close_not_fill_price(self):
        """Total equity after fill should use bar close for position value,
        not fill price."""
        engine = _make_engine(slippage_bps=0.0)
        ledger = Ledger(initial_cash=100_000.0)
        order_mgr = OrderManager()
        margin_engine = _make_margin_engine()

        # open=191.76, close=188.12 — fill at open (after Bug 2 fix)
        bar = _make_bar(open=191.76, close=188.12)
        stock_bars = {"NVDA": bar}

        from models.order import CreateOrderRequest, OrderSpec
        from models.instrument import Instrument

        req = CreateOrderRequest(
            session_id="sess_test",
            account_id="acct_test",
            order=OrderSpec(
                instrument=Instrument(type="STOCK", symbol="NVDA"),
                side=Side.BUY,
                order_type=OrderType.MARKET,
                qty=100,
            ),
        )
        order_mgr.submit(req, ts="2026-01-05T00:00:00+00:00")

        engine.process_step(
            ts="2026-01-05T00:00:00+00:00",
            ts_ns=1_000_000_000,
            stock_bars=stock_bars,
            option_bars={},
            order_manager=order_mgr,
            ledger=ledger,
            margin_engine=margin_engine,
        )

        # Mark to market after execution
        prices = {f"STOCK:{sym}": b.close for sym, b in stock_bars.items()}
        ledger.update_market_prices(prices)

        # fill at open = 191.76, cash = 100000 - 191.76*100 = 80824
        # position value = 100 * 188.12 = 18812
        # equity = 80824 + 18812 = 99636 (NOT 100000)
        equity = ledger.total_equity()
        expected_equity = 100_000.0 - 100 * 191.76 + 100 * 188.12
        assert abs(equity - expected_equity) < 0.01, (
            f"Equity should be {expected_equity:.2f}, got {equity:.2f}"
        )
        assert equity < 100_000.0, (
            "Equity should be less than initial cash when price drops from open to close"
        )


# ═══════════════════════════════════════════════════════════════════
# Bug 1: mark_price correction after execution (simulates _process_tick flow)
# ═══════════════════════════════════════════════════════════════════


class TestProcessTickMarkToMarket:
    """Simulates the _process_tick flow: pre-mark → execute → re-mark → snapshot.
    Verifies the post-execution re-mark step produces correct mark_price."""

    def test_remark_after_fill_corrects_mark_price(self):
        """Simulates the _process_tick sequence:
        1. update_market_prices (pre-execution)
        2. process_step (fills order, creates position with mark=fill_price)
        3. update_market_prices (post-execution re-mark)
        After step 3, mark_price must equal bar close, not fill price."""
        from domain.market_data_cache import MarketDataCache
        from models.order import CreateOrderRequest, OrderSpec
        from models.instrument import Instrument

        cache = MarketDataCache()
        bar = _make_bar(symbol="NVDA", open=191.76, close=188.12, ns=2_000_000_000)
        cache.load_stock_bars("NVDA", [bar])

        ledger = Ledger(initial_cash=100_000.0)
        order_mgr = OrderManager()
        engine = _make_engine(slippage_bps=0.0)
        margin_engine = _make_margin_engine()

        # Submit order
        req = CreateOrderRequest(
            session_id="sess_test",
            account_id="acct_test",
            order=OrderSpec(
                instrument=Instrument(type="STOCK", symbol="NVDA"),
                side=Side.BUY,
                order_type=OrderType.MARKET,
                qty=100,
            ),
        )
        order_mgr.submit(req, ts="2026-01-02T00:00:00+00:00")

        stock_bars = cache.get_stock_bars_at(2_000_000_000)
        prices = cache.get_prices_at(2_000_000_000)

        # Step 2: Pre-execution mark (no positions yet, no-op)
        ledger.update_market_prices(prices)

        # Step 3: Execution — fills order, creates position
        exec_events, trades = engine.process_step(
            ts="2026-01-05T00:00:00+00:00",
            ts_ns=2_000_000_000,
            stock_bars=stock_bars,
            option_bars={},
            order_manager=order_mgr,
            ledger=ledger,
            margin_engine=margin_engine,
        )
        assert len(trades) == 1, "Should have 1 trade"

        # After execution, mark_price = fill_price (191.76), NOT close (188.12)
        pos_after_fill = ledger.positions["STOCK:NVDA"]
        assert pos_after_fill.mark_price == 191.76, (
            "Before re-mark, mark_price should be fill price"
        )

        # Step 3b: Post-execution re-mark (the fix)
        ledger.update_market_prices(prices)

        pos = ledger.positions["STOCK:NVDA"]
        assert pos.mark_price == 188.12, (
            f"After re-mark, mark_price should be bar close (188.12), got {pos.mark_price}"
        )
        assert pos.unrealized_pnl == 100 * (188.12 - 191.76), (
            f"unrealized_pnl should be {100 * (188.12 - 191.76)}, got {pos.unrealized_pnl}"
        )

        # Equity should reflect market value, not fill value
        equity = ledger.total_equity()
        expected = 100_000.0 - 100 * 191.76 + 100 * 188.12
        assert abs(equity - expected) < 0.01, (
            f"Equity should be {expected:.2f}, got {equity:.2f}"
        )

    def test_no_remark_needed_when_no_fills(self):
        """When no fills happen, a second update_market_prices is harmless."""
        from domain.market_data_cache import MarketDataCache

        cache = MarketDataCache()
        bar = _make_bar(symbol="NVDA", open=191.76, close=188.12, ns=2_000_000_000)
        cache.load_stock_bars("NVDA", [bar])

        ledger = Ledger(initial_cash=100_000.0)
        order_mgr = OrderManager()
        engine = _make_engine(slippage_bps=0.0)
        margin_engine = _make_margin_engine()

        stock_bars = cache.get_stock_bars_at(2_000_000_000)
        prices = cache.get_prices_at(2_000_000_000)

        # Pre-mark
        ledger.update_market_prices(prices)

        # No orders — execution produces no trades
        exec_events, trades = engine.process_step(
            ts="2026-01-05T00:00:00+00:00",
            ts_ns=2_000_000_000,
            stock_bars=stock_bars,
            option_bars={},
            order_manager=order_mgr,
            ledger=ledger,
            margin_engine=margin_engine,
        )
        assert len(trades) == 0

        # Re-mark is harmless (no positions to update)
        ledger.update_market_prices(prices)

        assert ledger.total_equity() == 100_000.0


# ═══════════════════════════════════════════════════════════════════
# Existing behavior that must NOT break
# ═══════════════════════════════════════════════════════════════════


class TestExistingBehavior:
    """Verify LIMIT and STOP fill logic is unchanged."""

    def test_limit_buy_fills_at_limit_or_close(self):
        """LIMIT BUY fills at min(limit_price, close) when low <= limit."""
        engine = _make_engine(slippage_bps=0.0)
        bar = _make_bar(open=191.76, high=193.63, low=186.15, close=188.12)

        order = _make_order(
            side=Side.BUY, order_type=OrderType.LIMIT, limit_price=190.00
        )
        fill_price = engine._calculate_fill_price(bar, order)

        # low (186.15) <= limit (190.00), so fill at min(190.00, 188.12) = 188.12
        assert fill_price == 188.12

    def test_limit_buy_no_fill_when_low_above_limit(self):
        """LIMIT BUY does not fill when low > limit_price."""
        engine = _make_engine(slippage_bps=0.0)
        bar = _make_bar(open=191.76, high=193.63, low=192.00, close=193.00)

        order = _make_order(
            side=Side.BUY, order_type=OrderType.LIMIT, limit_price=190.00
        )
        fill_price = engine._calculate_fill_price(bar, order)

        assert fill_price is None

    def test_stop_buy_fills_at_max_stop_open_with_slippage(self):
        """STOP BUY fills at max(stop_price, open) + slippage."""
        engine = _make_engine(slippage_bps=0.0)
        bar = _make_bar(open=191.76, high=193.63, low=186.15, close=188.12)

        order = _make_order(
            side=Side.BUY, order_type=OrderType.STOP, stop_price=192.00
        )
        fill_price = engine._calculate_fill_price(bar, order)

        # high (193.63) >= stop (192.00), fill at max(192.00, 191.76) = 192.00
        assert fill_price == 192.00

    def test_stop_buy_no_fill_when_high_below_stop(self):
        """STOP BUY does not fill when high < stop_price."""
        engine = _make_engine(slippage_bps=0.0)
        bar = _make_bar(open=191.76, high=193.63, low=186.15, close=188.12)

        order = _make_order(
            side=Side.BUY, order_type=OrderType.STOP, stop_price=195.00
        )
        fill_price = engine._calculate_fill_price(bar, order)

        assert fill_price is None
