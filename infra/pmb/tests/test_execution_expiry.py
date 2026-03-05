import pytest
from domain.execution_engine import ExecutionEngine
from domain.option_lifecycle import ExpiryAction
from domain.ledger import Ledger
from domain.order_manager import OrderManager
from domain.margin_engine import MarginEngine
from models.enums import InstrumentType, Side, EventType
from models.position import Position
from models.session import FeeModel
from models.account import MarginConfig


def _engine():
    return ExecutionEngine(seed=42, slippage_bps=0.0, fee_model=FeeModel())


def _make_short_option_pos(contract: str, qty: int, avg_price: float) -> Position:
    return Position(
        instrument_id=f"OPTION:{contract}",
        type=InstrumentType.OPTION,
        qty=qty,
        avg_price=avg_price,
        mark_price=0.05,
    )


def test_process_expiries_otm_closes_option():
    engine = _engine()
    ledger = Ledger(initial_cash=50000.0)
    contract = "O:NVDA250117C00150000"
    ledger._positions[f"OPTION:{contract}"] = _make_short_option_pos(contract, -1, 3.50)

    action = ExpiryAction(
        contract=contract,
        instrument_id=f"OPTION:{contract}",
        option_pos=ledger._positions[f"OPTION:{contract}"],
        is_itm=False,
        intrinsic_value=0.0,
        underlying="NVDA",
        stock_side=None,
        strike=150.0,
        stock_qty=100,
    )

    order_manager = OrderManager()
    margin_engine = MarginEngine(MarginConfig())
    events = engine.process_expiries("2025-01-17T16:00:00+00:00", [action], ledger, order_manager, margin_engine)

    # Option position should be closed
    opt_pos = ledger.positions.get(f"OPTION:{contract}")
    assert opt_pos is None or opt_pos.qty == 0
    # Realized PnL = 3.50 (short closed at 0, premium kept)
    assert ledger.realized_pnl == pytest.approx(3.50, abs=0.01)
    # One OPTION_EXPIRY_EVENT emitted
    assert len(events) == 1
    assert events[0].type == EventType.OPTION_EXPIRY_EVENT


def test_process_expiries_itm_call_triggers_stock_sell():
    engine = _engine()
    ledger = Ledger(initial_cash=50000.0)
    contract = "O:NVDA250117C00136000"
    ledger._positions[f"OPTION:{contract}"] = _make_short_option_pos(contract, -2, 3.50)
    ledger._positions["STOCK:NVDA"] = Position(
        instrument_id="STOCK:NVDA",
        type=InstrumentType.STOCK,
        qty=200,
        avg_price=130.0,
        mark_price=145.0,
    )
    cash_before = ledger.cash

    action = ExpiryAction(
        contract=contract,
        instrument_id=f"OPTION:{contract}",
        option_pos=ledger._positions[f"OPTION:{contract}"],
        is_itm=True,
        intrinsic_value=9.0,
        underlying="NVDA",
        stock_side=Side.SELL,
        strike=136.0,
        stock_qty=200,
    )

    order_manager = OrderManager()
    margin_engine = MarginEngine(MarginConfig())
    events = engine.process_expiries("2025-01-17T16:00:00+00:00", [action], ledger, order_manager, margin_engine)

    # Option closed
    opt_pos = ledger.positions.get(f"OPTION:{contract}")
    assert opt_pos is None or opt_pos.qty == 0
    # 200 shares sold at 136
    stock_pos = ledger.positions.get("STOCK:NVDA")
    assert stock_pos is None or stock_pos.qty == 0
    # Cash increased by ~200 * 136 = 27200
    assert ledger.cash == pytest.approx(cash_before + 200 * 136.0, abs=1.0)
    assert any(e.type == EventType.OPTION_EXPIRY_EVENT for e in events)


def test_process_expiries_itm_put_triggers_stock_buy():
    engine = _engine()
    ledger = Ledger(initial_cash=50000.0)
    contract = "O:NVDA250117P00130000"
    ledger._positions[f"OPTION:{contract}"] = _make_short_option_pos(contract, -1, 4.0)
    cash_before = ledger.cash

    action = ExpiryAction(
        contract=contract,
        instrument_id=f"OPTION:{contract}",
        option_pos=ledger._positions[f"OPTION:{contract}"],
        is_itm=True,
        intrinsic_value=5.0,
        underlying="NVDA",
        stock_side=Side.BUY,
        strike=130.0,
        stock_qty=100,
    )

    order_manager = OrderManager()
    margin_engine = MarginEngine(MarginConfig())
    events = engine.process_expiries("2025-01-17T16:00:00+00:00", [action], ledger, order_manager, margin_engine)

    # Option closed
    opt_pos = ledger.positions.get(f"OPTION:{contract}")
    assert opt_pos is None or opt_pos.qty == 0
    # 100 shares bought at 130
    stock_pos = ledger.positions.get("STOCK:NVDA")
    assert stock_pos is not None and stock_pos.qty == 100
    assert ledger.cash == pytest.approx(cash_before - 100 * 130.0, abs=1.0)
    assert any(e.type == EventType.OPTION_EXPIRY_EVENT for e in events)


def test_process_expiries_long_itm_realizes_intrinsic():
    """Long call expires ITM: option closed at intrinsic value, no stock transaction."""
    engine = _engine()
    ledger = Ledger(initial_cash=50000.0)
    contract = "O:NVDA250117C00136000"
    # Long 1 call, bought at 3.50, now ITM with intrinsic = 9.0
    ledger._positions[f"OPTION:{contract}"] = Position(
        instrument_id=f"OPTION:{contract}",
        type=InstrumentType.OPTION,
        qty=1,  # long
        avg_price=3.50,
        mark_price=9.0,
    )
    cash_before = ledger.cash

    action = ExpiryAction(
        contract=contract,
        instrument_id=f"OPTION:{contract}",
        option_pos=ledger._positions[f"OPTION:{contract}"],
        is_itm=True,
        intrinsic_value=9.0,
        underlying="NVDA",
        stock_side=None,   # no assignment for long
        strike=136.0,
        stock_qty=100,
    )

    order_manager = OrderManager()
    margin_engine = MarginEngine(MarginConfig())
    events = engine.process_expiries("2025-01-17T16:00:00+00:00", [action], ledger, order_manager, margin_engine)

    # Option closed
    opt_pos = ledger.positions.get(f"OPTION:{contract}")
    assert opt_pos is None or opt_pos.qty == 0
    # No stock position created
    assert "STOCK:NVDA" not in ledger.positions
    # Cash increases by intrinsic value (9.0 per contract, 1 contract)
    assert ledger.cash == pytest.approx(cash_before + 9.0, abs=0.01)
    # Realized PnL = intrinsic - avg_price = 9.0 - 3.50 = 5.50
    assert ledger.realized_pnl == pytest.approx(5.50, abs=0.01)
    # One event
    assert len(events) == 1
    assert events[0].type == EventType.OPTION_EXPIRY_EVENT


def test_process_expiries_event_payload_has_assignment():
    """ITM call expiry event payload should contain assignment details."""
    engine = _engine()
    ledger = Ledger(initial_cash=50000.0)
    contract = "O:NVDA250117C00136000"
    ledger._positions[f"OPTION:{contract}"] = _make_short_option_pos(contract, -1, 3.50)
    ledger._positions["STOCK:NVDA"] = Position(
        instrument_id="STOCK:NVDA",
        type=InstrumentType.STOCK,
        qty=100,
        avg_price=130.0,
        mark_price=145.0,
    )

    action = ExpiryAction(
        contract=contract,
        instrument_id=f"OPTION:{contract}",
        option_pos=ledger._positions[f"OPTION:{contract}"],
        is_itm=True,
        intrinsic_value=9.0,
        underlying="NVDA",
        stock_side=Side.SELL,
        strike=136.0,
        stock_qty=100,
    )

    order_manager = OrderManager()
    margin_engine = MarginEngine(MarginConfig())
    events = engine.process_expiries("2025-01-17T16:00:00+00:00", [action], ledger, order_manager, margin_engine)

    assert len(events) == 1
    payload = events[0].payload
    assert payload["is_itm"] is True
    assert payload["assignment"] is not None
    assert payload["assignment"]["underlying"] == "NVDA"
    assert payload["assignment"]["side"] == "SELL"
    assert payload["assignment"]["qty"] == 100
    assert payload["assignment"]["strike"] == 136.0


def test_process_expiries_option_qty_preserves_pre_close_signed_qty():
    """Regression: option_qty in payload must reflect the original signed qty, not 0 after close."""
    engine = _engine()
    ledger = Ledger(initial_cash=50000.0)
    contract = "O:NVDA250117C00150000"
    # Short 3 contracts
    ledger._positions[f"OPTION:{contract}"] = _make_short_option_pos(contract, -3, 2.0)

    action = ExpiryAction(
        contract=contract,
        instrument_id=f"OPTION:{contract}",
        option_pos=ledger._positions[f"OPTION:{contract}"],
        is_itm=False,
        intrinsic_value=0.0,
        underlying="NVDA",
        stock_side=None,
        strike=150.0,
        stock_qty=300,
    )

    order_manager = OrderManager()
    margin_engine = MarginEngine(MarginConfig())
    events = engine.process_expiries("2025-01-17T16:00:00+00:00", [action], ledger, order_manager, margin_engine)

    assert len(events) == 1
    payload = events[0].payload
    # Must be -3 (original signed qty), not 0 (post-close qty)
    assert payload["option_qty"] == -3
