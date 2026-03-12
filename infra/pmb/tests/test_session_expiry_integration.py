"""Integration test: full session tick with option expiry."""
import pytest
from domain.session_clock import iso_to_ns, ns_to_iso
from domain.ledger import Ledger
from domain.order_manager import OrderManager
from domain.execution_engine import ExecutionEngine
from domain.margin_engine import MarginEngine
from domain.history_store import HistoryStore
from domain.market_data_cache import MarketDataCache
from models.enums import InstrumentType, EventType, Frequency
from models.market import StockBar, OptionBar
from models.position import Position
from models.session import FeeModel, ExecutionConfig, CreateSessionRequest, Universe
from models.account import MarginConfig
from services.session_service import SessionService, SessionState
from domain.session_clock import SessionClock


def _make_state(expiry_date: str, stock_price: float, option_avg_price: float) -> SessionState:
    """Build a minimal SessionState with one short call expiring on expiry_date."""
    contract = f"O:NVDA{expiry_date[2:4]}{expiry_date[5:7]}{expiry_date[8:10]}C00136000"
    ts_ns = iso_to_ns(f"{expiry_date}T16:00:00+00:00")

    cache = MarketDataCache()
    stock_bar = StockBar(
        symbol="NVDA", window_start_ns=ts_ns,
        open=stock_price, high=stock_price, low=stock_price, close=stock_price, volume=1000
    )
    cache._stock_bars["NVDA"] = {ts_ns: stock_bar}
    opt_bar = OptionBar(
        contract=contract, window_start_ns=ts_ns,
        open=0.01, high=0.01, low=0.0, close=0.0, volume=10,
        underlying="NVDA", expiry=expiry_date, strike=136.0, right="C"
    )
    cache._option_bars[contract] = {ts_ns: opt_bar}
    cache._rebuild_timestamps()

    clock = SessionClock([ts_ns], Frequency.DAILY, f"{expiry_date}T23:59:59+00:00")

    ledger = Ledger(50000.0)
    ledger._positions[f"OPTION:{contract}"] = Position(
        instrument_id=f"OPTION:{contract}",
        type=InstrumentType.OPTION,
        qty=-1,
        avg_price=option_avg_price,
        mark_price=0.01,
    )
    ledger._positions["STOCK:NVDA"] = Position(
        instrument_id="STOCK:NVDA",
        type=InstrumentType.STOCK,
        qty=100,
        avg_price=130.0,
        mark_price=stock_price,
    )

    exec_config = ExecutionConfig(fee_model=FeeModel())
    req = CreateSessionRequest(
        account_id="acct_test",
        frequency=Frequency.DAILY,
        start_ts=f"{expiry_date}T00:00:00+00:00",
        end_ts=f"{expiry_date}T23:59:59+00:00",
        universe=Universe(stocks=["NVDA"], options=[contract]),
        execution_config=exec_config,
    )

    return SessionState(
        session_id="sess_test",
        account_id="acct_test",
        config=req,
        clock=clock,
        cache=cache,
        ledger=ledger,
        order_manager=OrderManager(),
        execution_engine=ExecutionEngine(seed=42, slippage_bps=0.0, fee_model=FeeModel()),
        margin_engine=MarginEngine(MarginConfig()),
        history=HistoryStore(),
    )


def test_otm_expiry_closes_option_position():
    """Short call expires OTM: option removed, stock position unchanged."""
    state = _make_state("2025-01-17", stock_price=125.0, option_avg_price=3.50)
    contract = list(state.cache._option_bars.keys())[0]
    ts_ns = state.clock._timestamps[0]

    svc = SessionService.__new__(SessionService)
    svc._sessions = {"sess_test": state}

    ts = ns_to_iso(ts_ns)
    events = svc._process_tick(state, ts_ns, ts)

    # Option position should be gone
    opt_pos = state.ledger.positions.get(f"OPTION:{contract}")
    assert opt_pos is None or opt_pos.qty == 0

    # OPTION_EXPIRY_EVENT in events
    types = [e["type"] for e in events]
    assert EventType.OPTION_EXPIRY_EVENT.value in types

    # Stock position unchanged (OTM = no assignment)
    stock_pos = state.ledger.positions.get("STOCK:NVDA")
    assert stock_pos is not None and stock_pos.qty == 100


def test_itm_expiry_triggers_call_away():
    """Short call expires ITM: option closed, stock sold at strike."""
    state = _make_state("2025-01-17", stock_price=145.0, option_avg_price=3.50)
    contract = list(state.cache._option_bars.keys())[0]
    ts_ns = state.clock._timestamps[0]
    cash_before = state.ledger.cash

    svc = SessionService.__new__(SessionService)
    svc._sessions = {"sess_test": state}

    ts = ns_to_iso(ts_ns)
    events = svc._process_tick(state, ts_ns, ts)

    # Option should be closed
    opt_pos = state.ledger.positions.get(f"OPTION:{contract}")
    assert opt_pos is None or opt_pos.qty == 0

    # Stock should be sold (100 shares at strike 136)
    stock_pos = state.ledger.positions.get("STOCK:NVDA")
    assert stock_pos is None or stock_pos.qty == 0

    # Cash increases by ~100 * 136 = 13600
    assert state.ledger.cash > cash_before + 13500

    # Expiry event present
    types = [e["type"] for e in events]
    assert EventType.OPTION_EXPIRY_EVENT.value in types


def test_open_order_on_expiring_contract_is_cancelled():
    """Regression [2]: a MARKET order placed on an expiring contract must be cancelled,
    not filled and left as an open expired position."""
    from models.enums import OrderType, Side as OrderSide, TimeInForce
    from models.order import Order, OrderStatus

    state = _make_state("2025-01-17", stock_price=125.0, option_avg_price=3.50)
    contract = list(state.cache._option_bars.keys())[0]
    ts_ns = state.clock._timestamps[0]

    # Inject an open MARKET BUY order on the expiring contract (no prior position)
    order = Order(
        order_id="ord_test01",
        session_id="sess_test",
        account_id="acct_test",
        instrument_id=f"OPTION:{contract}",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        qty=1,
        remaining_qty=1,
        status=OrderStatus.ACCEPTED,
        time_in_force=TimeInForce.DAY,
        created_ts=ns_to_iso(ts_ns),
        last_update_ts=ns_to_iso(ts_ns),
    )
    state.order_manager._orders["ord_test01"] = order

    svc = SessionService.__new__(SessionService)
    svc._sessions = {"sess_test": state}

    ts = ns_to_iso(ts_ns)
    svc._process_tick(state, ts_ns, ts)

    # The order must be cancelled, not left open or filled
    result_order = state.order_manager.get_order("ord_test01")
    assert result_order is not None
    assert result_order.status == OrderStatus.CANCELLED, (
        f"Expected CANCELLED, got {result_order.status}: open order on expired contract survived the tick"
    )


def test_minute_session_expiry_fires_only_at_last_bar():
    """Regression [4]: for MINUTE sessions, expiry must not fire at 09:31 on the expiry date.
    It should fire only at the last bar of the expiry date."""
    expiry_date = "2025-01-17"
    contract = f"O:NVDA{expiry_date[2:4]}{expiry_date[5:7]}{expiry_date[8:10]}C00136000"
    stock_price = 125.0  # OTM call (strike 136 > spot 125)

    # Two minute bars on expiry date: 09:31 and 15:59
    ts_morning = iso_to_ns(f"{expiry_date}T14:31:00+00:00")  # 09:31 ET
    ts_close = iso_to_ns(f"{expiry_date}T20:59:00+00:00")   # 15:59 ET

    cache = MarketDataCache()
    for ts_ns in (ts_morning, ts_close):
        cache._stock_bars.setdefault("NVDA", {})[ts_ns] = StockBar(
            symbol="NVDA", window_start_ns=ts_ns,
            open=stock_price, high=stock_price, low=stock_price, close=stock_price, volume=1000,
        )
        cache._option_bars.setdefault(contract, {})[ts_ns] = OptionBar(
            contract=contract, window_start_ns=ts_ns,
            open=0.01, high=0.01, low=0.0, close=0.0, volume=5,
            underlying="NVDA", expiry=expiry_date, strike=136.0, right="C",
        )
    cache._rebuild_timestamps()

    clock = SessionClock([ts_morning, ts_close], Frequency.MINUTE, f"{expiry_date}T21:00:00+00:00")

    ledger = Ledger(50000.0)
    ledger._positions[f"OPTION:{contract}"] = Position(
        instrument_id=f"OPTION:{contract}",
        type=InstrumentType.OPTION,
        qty=-1,
        avg_price=3.50,
        mark_price=0.01,
    )

    exec_config = ExecutionConfig(fee_model=FeeModel())
    req = CreateSessionRequest(
        account_id="acct_test",
        frequency=Frequency.MINUTE,
        start_ts=f"{expiry_date}T14:31:00+00:00",
        end_ts=f"{expiry_date}T21:00:00+00:00",
        universe=Universe(stocks=["NVDA"], options=[contract]),
        execution_config=exec_config,
    )
    state = SessionState(
        session_id="sess_min",
        account_id="acct_test",
        config=req,
        clock=clock,
        cache=cache,
        ledger=ledger,
        order_manager=OrderManager(),
        execution_engine=ExecutionEngine(seed=42, slippage_bps=0.0, fee_model=FeeModel()),
        margin_engine=MarginEngine(MarginConfig()),
        history=HistoryStore(),
    )

    svc = SessionService.__new__(SessionService)
    svc._sessions = {"sess_min": state}

    # --- First tick (09:31): expiry must NOT fire ---
    ts_str = ns_to_iso(ts_morning)
    events_morning = svc._process_tick(state, ts_morning, ts_str)

    morning_types = [e["type"] for e in events_morning]
    assert EventType.OPTION_EXPIRY_EVENT.value not in morning_types, (
        "Expiry fired at 09:31 on expiry date — should only fire at last bar"
    )
    # Option position still intact
    assert state.ledger.positions.get(f"OPTION:{contract}") is not None

    # --- Second tick (15:59): expiry MUST fire (last bar of the day) ---
    ts_str = ns_to_iso(ts_close)
    events_close = svc._process_tick(state, ts_close, ts_str)

    close_types = [e["type"] for e in events_close]
    assert EventType.OPTION_EXPIRY_EVENT.value in close_types, (
        "Expiry did not fire at last bar of expiry date"
    )
    # OTM — option position gone
    opt_pos = state.ledger.positions.get(f"OPTION:{contract}")
    assert opt_pos is None or opt_pos.qty == 0
