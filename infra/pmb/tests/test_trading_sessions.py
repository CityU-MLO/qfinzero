"""Trading-session model: segments, trading dates, order eligibility, TIF expiry,
partial fills."""
from domain.execution_engine import ExecutionEngine
from domain.history_store import HistoryStore
from domain.ledger import Ledger
from domain.margin_engine import MarginEngine
from domain.market_data_cache import MarketDataCache
from domain.order_manager import OrderManager
from domain.session_clock import SessionClock, iso_to_ns
from domain.trading_sessions import Segment, segment_of, trading_date_of
from models.account import MarginConfig
from models.enums import (Frequency, InstrumentType, OrderStatus, OrderType, Side,
                          TimeInForce, TradingHours)
from models.instrument import Instrument
from models.market import StockBar
from models.order import CreateOrderRequest, OrderSpec
from models.session import (CreateSessionRequest, ExecutionConfig, FeeModel,
                            PartialFillConfig, Universe)
from services.order_service import OrderService
from services.session_service import SessionService, SessionState


def ns(iso: str) -> int:
    return iso_to_ns(iso)


# ── classification ──────────────────────────────────────────────────────

def test_segments_in_winter_and_summer():
    # 2025-01-02 is EST (UTC-5); 2025-06-02 is EDT (UTC-4)
    assert segment_of(ns("2025-01-02T14:30:00Z")) == Segment.REGULAR    # 09:30 EST
    assert segment_of(ns("2025-01-02T14:29:00Z")) == Segment.PRE
    assert segment_of(ns("2025-01-02T21:00:00Z")) == Segment.POST       # 16:00 EST
    assert segment_of(ns("2025-01-03T00:30:00Z")) == Segment.POST       # 19:30 EST
    assert segment_of(ns("2025-01-03T01:00:00Z")) == Segment.OVERNIGHT  # 20:00 EST
    assert segment_of(ns("2025-06-02T13:30:00Z")) == Segment.REGULAR    # 09:30 EDT
    assert segment_of(ns("2025-06-03T00:00:00Z")) == Segment.OVERNIGHT  # 20:00 EDT
    assert segment_of(ns("2025-01-02T00:00:00Z"), Frequency.DAILY) == Segment.REGULAR


def test_trading_dates():
    # 19:30 EST is still the same trading date (the old UTC rule said "next day")
    assert trading_date_of(ns("2025-01-03T00:30:00Z")) == "2025-01-02"
    # overnight from 20:00 belongs to the next trading date
    assert trading_date_of(ns("2025-01-03T01:00:00Z")) == "2025-01-03"
    assert trading_date_of(ns("2025-01-03T06:00:00Z")) == "2025-01-03"   # 01:00 EST
    # Friday night and Sunday night both belong to Monday
    assert trading_date_of(ns("2025-01-04T02:00:00Z")) == "2025-01-06"   # Fri 21:00
    assert trading_date_of(ns("2025-01-06T02:00:00Z")) == "2025-01-06"   # Sun 21:00
    assert trading_date_of(ns("2025-01-02T00:00:00Z"), Frequency.DAILY) == "2025-01-02"


def test_clock_eod_uses_trading_dates():
    ts = [ns("2025-01-02T20:59:00Z"),   # 15:59 EST
          ns("2025-01-03T00:30:00Z"),   # 19:30 EST, same trading date
          ns("2025-01-03T01:30:00Z")]   # 20:30 EST, next trading date (overnight)
    clock = SessionClock(ts, Frequency.MINUTE, "2025-01-03T02:00:00Z")
    assert clock.is_last_bar_of_date(ts[0]) is False
    assert clock.is_last_bar_of_date(ts[1]) is True
    assert clock.is_last_bar_of_date(ts[2]) is True


# ── session harness ─────────────────────────────────────────────────────

BARS = {   # minute bars for FOO; (iso, open, high, low, close, volume)
    "pre":   ("2025-01-02T14:00:00Z", 100.0, 100.5, 99.5, 100.0, 50),   # 09:00 EST
    "open":  ("2025-01-02T14:30:00Z", 101.0, 102.0, 100.5, 101.5, 1000),
    "post":  ("2025-01-02T22:00:00Z", 103.0, 103.5, 102.5, 103.0, 40),  # 17:00 EST
    "night": ("2025-01-03T02:00:00Z", 104.0, 104.5, 103.5, 104.0, 30),  # 21:00 EST
    "next":  ("2025-01-03T14:30:00Z", 105.0, 105.5, 104.5, 105.0, 900),
}


def make_session(execution: ExecutionConfig | None = None, bars=BARS):
    cache = MarketDataCache()
    cache._stock_bars["FOO"] = {}
    for iso, o, h, low, c, v in bars.values():
        t = ns(iso)
        cache._stock_bars["FOO"][t] = StockBar(symbol="FOO", window_start_ns=t, open=o, high=h,
                                               low=low, close=c, volume=v)
    cache._rebuild_timestamps()
    stamps = sorted(ns(b[0]) for b in bars.values())
    execution = execution or ExecutionConfig(slippage_bps=0.0, fee_model=FeeModel())
    req = CreateSessionRequest(account_id="acct", frequency=Frequency.MINUTE,
                               start_ts=bars[next(iter(bars))][0], end_ts="2025-01-04T00:00:00Z",
                               universe=Universe(stocks=["FOO"]), execution_config=execution)
    state = SessionState(
        session_id="s", account_id="acct", config=req,
        clock=SessionClock(stamps, Frequency.MINUTE, req.end_ts), cache=cache,
        ledger=Ledger(1_000_000.0), order_manager=OrderManager(),
        execution_engine=ExecutionEngine(
            seed=1, slippage_bps=0.0, fee_model=FeeModel(),
            partial_fill=execution.partial_fill,
            enforce_trading_hours=execution.enforce_trading_hours),
        margin_engine=MarginEngine(MarginConfig()), history=HistoryStore(),
    )
    svc = SessionService.__new__(SessionService)
    svc._sessions = {"s": state}
    svc._action_log = {}
    return svc, state


def place(svc, order_type=OrderType.MARKET, qty=10, limit=None, hours=TradingHours.REGULAR,
          tif=TimeInForce.DAY, expire_ts=None, instrument=None):
    spec = OrderSpec(instrument=instrument or Instrument(type=InstrumentType.STOCK, symbol="FOO"),
                     side=Side.BUY, order_type=order_type, qty=qty, limit_price=limit,
                     time_in_force=tif, expire_ts=expire_ts, trading_hours=hours)
    return OrderService(svc).place_order(CreateOrderRequest(session_id="s", account_id="acct",
                                                            order=spec))


def order(state, oid):
    return state.order_manager.get_order(oid)


# ── eligibility ─────────────────────────────────────────────────────────

def test_regular_market_order_waits_for_the_open():
    svc, state = make_session()
    oid = place(svc)["order_id"]                 # sent before the first (pre-market) bar
    svc.step("s", 1)                             # 09:00 pre-market bar: no fill
    assert order(state, oid).status == OrderStatus.ACCEPTED
    svc.step("s", 1)                             # 09:30 regular bar: fills at its open
    assert order(state, oid).status == OrderStatus.FILLED
    assert order(state, oid).avg_fill_price == 101.0


def test_extended_limit_fills_after_hours_and_overnight_needs_overnight():
    svc, state = make_session()
    svc.step("s", 2)                             # now at 09:30
    ext = place(svc, OrderType.LIMIT, limit=103.2, hours=TradingHours.EXTENDED,
                tif=TimeInForce.GTC)["order_id"]
    night = place(svc, OrderType.LIMIT, limit=104.2, hours=TradingHours.OVERNIGHT,
                  tif=TimeInForce.GTC)["order_id"]
    ext_night = place(svc, OrderType.LIMIT, limit=104.2, hours=TradingHours.EXTENDED,
                      tif=TimeInForce.GTC)["order_id"]
    svc.step("s", 1)                             # 17:00 post bar (low 102.5)
    assert order(state, ext).status == OrderStatus.FILLED
    assert order(state, ext_night).status == OrderStatus.FILLED   # 103.5 <= 104.2 in POST too
    svc.step("s", 1)                             # 21:00 overnight bar
    assert order(state, night).status == OrderStatus.FILLED


def test_overnight_only_reaches_night_bar():
    bars = {k: BARS[k] for k in ("open", "night", "next")}
    svc, state = make_session(bars=bars)
    svc.step("s", 1)                             # at 09:30 (bar consumed)
    ext = place(svc, OrderType.LIMIT, limit=104.1, hours=TradingHours.EXTENDED,
                tif=TimeInForce.GTC)["order_id"]
    night = place(svc, OrderType.LIMIT, limit=104.1, hours=TradingHours.OVERNIGHT,
                  tif=TimeInForce.GTC)["order_id"]
    svc.step("s", 1)                             # 21:00 overnight bar
    assert order(state, night).status == OrderStatus.FILLED
    assert order(state, ext).status == OrderStatus.ACCEPTED       # not allowed overnight


def test_submission_rules():
    svc, _ = make_session()
    r = place(svc, OrderType.MARKET, hours=TradingHours.EXTENDED)
    assert r["ok"] is False and "LIMIT" in r["error"]
    opt = Instrument(type=InstrumentType.OPTION, contract="O:FOO250117C00100000")
    r = place(svc, OrderType.LIMIT, limit=1.0, hours=TradingHours.OVERNIGHT, instrument=opt)
    assert r["ok"] is False and "regular hours" in r["error"]
    r = place(svc, OrderType.LIMIT, limit=1.0, tif=TimeInForce.GTD)
    assert r["ok"] is False and "expire_ts" in r["error"]


# ── time in force ───────────────────────────────────────────────────────

def test_day_order_expires_at_end_of_its_trading_date():
    svc, state = make_session()
    svc.step("s", 1)                                         # 09:00
    oid = place(svc, OrderType.LIMIT, limit=50.0)["order_id"]  # never marketable
    svc.step("s", 2)                                         # 09:30, 17:00 (last bar of 01-02)
    assert order(state, oid).status == OrderStatus.EXPIRED
    assert order(state, oid).session_date == "2025-01-02"


def test_day_order_sent_after_close_carries_to_next_day():
    svc, state = make_session()
    svc.step("s", 3)                                         # at 17:00 post bar
    oid = place(svc, OrderType.LIMIT, limit=50.0)["order_id"]  # REGULAR, not eligible tonight
    svc.step("s", 1)                                         # 21:00 overnight (trading date 01-03)
    assert order(state, oid).status == OrderStatus.ACCEPTED
    svc.step("s", 1)                                         # 01-03 09:30, last bar
    assert order(state, oid).session_date == "2025-01-03"
    assert order(state, oid).status == OrderStatus.EXPIRED


def test_gtd_and_gtc():
    svc, state = make_session()
    gtd = place(svc, OrderType.LIMIT, limit=50.0, tif=TimeInForce.GTD,
                expire_ts="2025-01-02T15:00:00Z")["order_id"]
    gtc = place(svc, OrderType.LIMIT, limit=50.0, tif=TimeInForce.GTC)["order_id"]
    svc.step("s", 2)                                         # 09:00, 09:30
    assert order(state, gtd).status == OrderStatus.ACCEPTED
    svc.step("s", 1)                                         # 17:00 > expire_ts
    assert order(state, gtd).status == OrderStatus.EXPIRED
    svc.step("s", 2)
    assert order(state, gtc).status == OrderStatus.ACCEPTED


def test_legacy_mode_trades_every_bar_and_never_expires():
    svc, state = make_session(ExecutionConfig(slippage_bps=0.0, enforce_trading_hours=False))
    oid = place(svc)["order_id"]
    svc.step("s", 1)                                         # pre-market bar fills
    assert order(state, oid).avg_fill_price == 100.0
    lim = place(svc, OrderType.LIMIT, limit=50.0)["order_id"]
    svc.step("s", 4)
    assert order(state, lim).status == OrderStatus.ACCEPTED


# ── partial fills ───────────────────────────────────────────────────────

def test_partial_fill_caps_at_share_of_bar_volume():
    cfg = ExecutionConfig(slippage_bps=0.0,
                          partial_fill=PartialFillConfig(enabled=True, max_fill_ratio_per_tick=0.1))
    svc, state = make_session(cfg)
    svc.step("s", 1)                                         # at 09:00
    oid = place(svc, qty=150, tif=TimeInForce.GTC)["order_id"]
    svc.step("s", 1)                                         # 09:30 bar volume 1000 -> 100
    o = order(state, oid)
    assert (o.status, o.filled_qty) == (OrderStatus.PARTIALLY_FILLED, 100)
    svc.step("s", 3)                                         # REGULAR only: next-day 09:30
    assert order(state, oid).status == OrderStatus.FILLED


# ── step_until ──────────────────────────────────────────────────────────

def test_step_until_stops_on_fill_price_and_segment():
    from models.session import PriceTrigger, StepUntilRequest
    svc, state = make_session()
    svc.get_full_state = lambda sid: {"account": {"cash": 1}}
    place(svc, OrderType.LIMIT, limit=101.0, tif=TimeInForce.GTC)
    r = svc.step_until("s", StepUntilRequest())
    assert (r["reason"], r["steps"]) == ("fill", 2)          # pre bar ineligible, fills at 09:30
    assert all(e["type"] != "MARKET_TICK" for e in r["events"]) and r["last_tick"]
    r = svc.step_until("s", StepUntilRequest(price_triggers=[PriceTrigger(symbol="FOO", op=">=",
                                                                          price=104.0)]))
    assert r["reason"].startswith("price_trigger") and r["clock"]["segment"] == "OVERNIGHT"
    r = svc.step_until("s", StepUntilRequest(stop_on_segment="REGULAR"))
    assert r["reason"] in ("segment:REGULAR", "finished")
    assert r["clock"]["trading_date"] == "2025-01-03"
