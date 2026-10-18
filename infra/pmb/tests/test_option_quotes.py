"""Option fills and marks against the minute NBBO (option_fill_model="quote")."""
from domain.execution_engine import ExecutionEngine
from domain.history_store import HistoryStore
from domain.ledger import Ledger
from domain.margin_engine import MarginEngine
from domain.market_data_cache import MarketDataCache
from domain.order_manager import OrderManager
from domain.session_clock import SessionClock, iso_to_ns
from models.account import MarginConfig
from models.enums import (Frequency, InstrumentType, OrderStatus, OrderType, Side,
                          TimeInForce)
from models.instrument import Instrument
from models.market import OptionBar, Quote, StockBar
from models.order import CreateOrderRequest, OrderSpec
from models.session import (CreateSessionRequest, ExecutionConfig, FeeModel,
                            PartialFillConfig, Universe)
from services.order_service import OrderService
from services.session_service import SessionService, SessionState

C = "O:FOO250117C00100000"
MIN = 60_000_000_000
T = iso_to_ns("2025-01-02T14:30:00Z")          # 09:30 ET


def make(model="quote", partial=None, option_bars=(), quotes=()):
    cache = MarketDataCache()
    cache._stock_bars["FOO"] = {
        T + i * MIN: StockBar(symbol="FOO", window_start_ns=T + i * MIN, open=100, high=100,
                              low=100, close=100, volume=1000) for i in range(6)}
    cache._option_bars[C] = {
        T + i * MIN: OptionBar(contract=C, window_start_ns=T + i * MIN, open=o, high=h, low=lo,
                               close=c, volume=v) for i, o, h, lo, c, v in option_bars}
    cache._rebuild_timestamps()
    cache.load_option_quotes(C, [Quote(window_start_ns=T + i * MIN, bid=b, ask=a, bid_size=bs,
                                       ask_size=as_) for i, b, a, bs, as_ in quotes])
    cfg = ExecutionConfig(slippage_bps=0.0, fee_model=FeeModel(option_fee_per_contract=0.0),
                          option_fill_model=model,
                          partial_fill=partial or PartialFillConfig())
    req = CreateSessionRequest(account_id="a", frequency=Frequency.MINUTE,
                               start_ts="2025-01-02T14:30:00Z", end_ts="2025-01-02T15:00:00Z",
                               universe=Universe(stocks=["FOO"], options=[C]), execution_config=cfg)
    state = SessionState(
        session_id="s", account_id="a", config=req,
        clock=SessionClock(cache.get_all_timestamps(), Frequency.MINUTE, req.end_ts), cache=cache,
        ledger=Ledger(100_000.0), order_manager=OrderManager(),
        execution_engine=ExecutionEngine(seed=1, slippage_bps=0.0, fee_model=cfg.fee_model,
                                         partial_fill=cfg.partial_fill, enforce_trading_hours=True,
                                         option_fill_model=model),
        margin_engine=MarginEngine(MarginConfig()), history=HistoryStore(),
    )
    svc = SessionService.__new__(SessionService)
    svc._sessions = {"s": state}
    return svc, state


def buy(svc, qty=1, order_type=OrderType.MARKET, limit=None):
    spec = OrderSpec(instrument=Instrument(type=InstrumentType.OPTION, contract=C), side=Side.BUY,
                     order_type=order_type, qty=qty, limit_price=limit, time_in_force=TimeInForce.GTC)
    r = OrderService(svc).place_order(CreateOrderRequest(session_id="s", account_id="a", order=spec))
    return r["order_id"]


def test_market_buy_takes_the_ask_without_a_trade_print():
    svc, state = make(quotes=[(0, 1.00, 1.20, 10, 10)])        # book at end of 09:30
    svc.step("s", 1)                                            # 09:30 bar: no quote known yet
    oid = buy(svc)
    svc.step("s", 1)                                            # 09:31: book from 09:30 applies
    o = state.order_manager.get_order(oid)
    assert (o.status, o.avg_fill_price) == (OrderStatus.FILLED, 1.20)


def test_limit_marketable_at_quote_resting_needs_a_print_through():
    svc, state = make(option_bars=[(2, 1.05, 1.06, 1.04, 1.05, 3)],
                      quotes=[(0, 1.00, 1.20, 10, 10)])
    svc.step("s", 1)
    marketable = buy(svc, order_type=OrderType.LIMIT, limit=1.25)
    resting = buy(svc, order_type=OrderType.LIMIT, limit=1.05)
    svc.step("s", 1)                                            # 09:31: no print
    assert state.order_manager.get_order(marketable).avg_fill_price == 1.20
    assert state.order_manager.get_order(resting).status == OrderStatus.ACCEPTED
    svc.step("s", 1)                                            # 09:32: printed 1.04-1.06
    r = state.order_manager.get_order(resting)
    assert (r.status, r.avg_fill_price) == (OrderStatus.FILLED, 1.05)


def test_partial_fill_caps_at_displayed_size():
    svc, state = make(partial=PartialFillConfig(enabled=True),
                      quotes=[(0, 1.00, 1.20, 10, 4), (1, 1.00, 1.30, 10, 4)])
    svc.step("s", 1)
    oid = buy(svc, qty=6)
    svc.step("s", 1)
    o = state.order_manager.get_order(oid)
    assert (o.status, o.filled_qty) == (OrderStatus.PARTIALLY_FILLED, 4)
    svc.step("s", 1)
    o = state.order_manager.get_order(oid)
    assert (o.status, o.filled_qty) == (OrderStatus.FILLED, 6)
    assert round(o.avg_fill_price, 4) == round((4 * 1.20 + 2 * 1.30) / 6, 4)


def test_positions_mark_at_mid():
    svc, state = make(quotes=[(0, 1.00, 1.20, 10, 10), (1, 2.00, 2.20, 10, 10)])
    svc.step("s", 1)
    buy(svc)
    svc.step("s", 1)                                            # fills at 1.20; book at 09:31 close
    pos = state.ledger.positions[f"OPTION:{C}"]
    assert pos.mark_price == 2.10


def test_bar_model_ignores_quotes():
    svc, state = make(model="bar", option_bars=[(1, 1.10, 1.10, 1.10, 1.10, 2)],
                      quotes=[(0, 1.00, 1.20, 10, 10)])
    svc.step("s", 1)
    oid = buy(svc)
    svc.step("s", 1)
    assert state.order_manager.get_order(oid).avg_fill_price == 1.10   # bar open
