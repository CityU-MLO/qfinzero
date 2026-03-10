"""Tests for daily bar open patching with minute bar prices."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import AsyncMock, MagicMock

from models.market import StockBar, OptionBar
from models.session import CreateSessionRequest, Universe
from models.account import Account, MarginConfig
from models.enums import Frequency
from domain.market_data_cache import MarketDataCache
from domain.session_clock import iso_to_ns
from services.session_service import SessionService


def _make_service():
    upq = AsyncMock()
    return SessionService(upq)


def _ns(time_str: str) -> int:
    """Convert 'YYYY-MM-DDTHH:MM:SS' to nanoseconds (UTC)."""
    return iso_to_ns(time_str + "+00:00")


# --- Stock patching ---

@pytest.mark.asyncio
async def test_stock_open_patched_with_1550_bar():
    """Daily stock bar.open should be replaced with 15:50 ET minute bar open."""
    svc = _make_service()
    cache = MarketDataCache()

    daily_ns = _ns("2024-01-02T00:00:00")
    cache.load_stock_bars("AAPL", [
        StockBar(symbol="AAPL", window_start_ns=daily_ns,
                 open=100.0, high=110.0, low=95.0, close=105.0, volume=1000),
    ])

    # 15:50 ET = 20:50 UTC (January = EST)
    minute_bars = [
        StockBar(symbol="AAPL", window_start_ns=_ns("2024-01-02T20:50:00"),
                 open=104.50, high=105.0, low=104.0, close=104.80, volume=500),
    ]
    svc._upq.get_stock_minute_bars.return_value = minute_bars

    req = MagicMock()
    req.universe.stocks = ["AAPL"]
    req.universe.options = []
    req.start_ts = "2024-01-02T00:00:00+00:00"
    req.end_ts = "2024-01-02T23:59:59+00:00"

    await svc._patch_daily_open_with_minute_price(req, cache)

    patched_bar = cache._stock_bars["AAPL"][daily_ns]
    assert patched_bar.open == 104.50
    assert patched_bar.close == 105.0
    assert patched_bar.high == 110.0


@pytest.mark.asyncio
async def test_stock_fallback_to_earlier_minute_bar():
    """When 15:50 is missing, use nearest bar in 15:40-15:49 window."""
    svc = _make_service()
    cache = MarketDataCache()

    daily_ns = _ns("2024-01-02T00:00:00")
    cache.load_stock_bars("AAPL", [
        StockBar(symbol="AAPL", window_start_ns=daily_ns,
                 open=100.0, high=110.0, low=95.0, close=105.0, volume=1000),
    ])

    # Only 15:45 ET = 20:45 UTC
    minute_bars = [
        StockBar(symbol="AAPL", window_start_ns=_ns("2024-01-02T20:45:00"),
                 open=104.20, high=104.50, low=104.00, close=104.30, volume=300),
    ]
    svc._upq.get_stock_minute_bars.return_value = minute_bars

    req = MagicMock()
    req.universe.stocks = ["AAPL"]
    req.universe.options = []
    req.start_ts = "2024-01-02T00:00:00+00:00"
    req.end_ts = "2024-01-02T23:59:59+00:00"

    await svc._patch_daily_open_with_minute_price(req, cache)

    patched_bar = cache._stock_bars["AAPL"][daily_ns]
    assert patched_bar.open == 104.20


@pytest.mark.asyncio
async def test_stock_fallback_to_daily_close():
    """When no minute bar in 15:40-15:50 window, fall back to daily close."""
    svc = _make_service()
    cache = MarketDataCache()

    daily_ns = _ns("2024-01-02T00:00:00")
    cache.load_stock_bars("AAPL", [
        StockBar(symbol="AAPL", window_start_ns=daily_ns,
                 open=100.0, high=110.0, low=95.0, close=105.0, volume=1000),
    ])

    svc._upq.get_stock_minute_bars.return_value = []

    req = MagicMock()
    req.universe.stocks = ["AAPL"]
    req.universe.options = []
    req.start_ts = "2024-01-02T00:00:00+00:00"
    req.end_ts = "2024-01-02T23:59:59+00:00"

    await svc._patch_daily_open_with_minute_price(req, cache)

    patched_bar = cache._stock_bars["AAPL"][daily_ns]
    assert patched_bar.open == 105.0  # fell back to daily close


@pytest.mark.asyncio
async def test_stock_prefers_latest_minute_bar():
    """When multiple bars in 15:40-15:49, prefer the latest."""
    svc = _make_service()
    cache = MarketDataCache()

    daily_ns = _ns("2024-01-02T00:00:00")
    cache.load_stock_bars("AAPL", [
        StockBar(symbol="AAPL", window_start_ns=daily_ns,
                 open=100.0, high=110.0, low=95.0, close=105.0, volume=1000),
    ])

    # Bars at 15:42 and 15:48 — should pick 15:48
    minute_bars = [
        StockBar(symbol="AAPL", window_start_ns=_ns("2024-01-02T20:42:00"),
                 open=103.00, high=103.50, low=102.50, close=103.20, volume=200),
        StockBar(symbol="AAPL", window_start_ns=_ns("2024-01-02T20:48:00"),
                 open=104.10, high=104.50, low=103.80, close=104.30, volume=400),
    ]
    svc._upq.get_stock_minute_bars.return_value = minute_bars

    req = MagicMock()
    req.universe.stocks = ["AAPL"]
    req.universe.options = []
    req.start_ts = "2024-01-02T00:00:00+00:00"
    req.end_ts = "2024-01-02T23:59:59+00:00"

    await svc._patch_daily_open_with_minute_price(req, cache)

    patched_bar = cache._stock_bars["AAPL"][daily_ns]
    assert patched_bar.open == 104.10


# --- Option patching ---

@pytest.mark.asyncio
async def test_option_open_patched_with_1550_bar():
    """Daily option bar.open should be replaced with 15:50 ET minute bar open."""
    svc = _make_service()
    cache = MarketDataCache()

    contract = "O:AAPL240119C00150000"
    daily_ns = _ns("2024-01-02T00:00:00")
    cache.load_option_bars(contract, [
        OptionBar(contract=contract, window_start_ns=daily_ns,
                  open=3.00, high=3.50, low=2.50, close=3.20, volume=100),
    ])

    minute_bars = [
        OptionBar(contract=contract, window_start_ns=_ns("2024-01-02T20:50:00"),
                  open=3.15, high=3.20, low=3.10, close=3.18, volume=50),
    ]
    svc._upq.get_option_minute_bars.return_value = minute_bars

    req = MagicMock()
    req.universe.stocks = []
    req.universe.options = [contract]
    req.start_ts = "2024-01-02T00:00:00+00:00"
    req.end_ts = "2024-01-02T23:59:59+00:00"

    await svc._patch_daily_open_with_minute_price(req, cache)

    patched_bar = cache._option_bars[contract][daily_ns]
    assert patched_bar.open == 3.15
    assert patched_bar.close == 3.20


@pytest.mark.asyncio
async def test_option_fallback_to_daily_close():
    """Illiquid option with no minute bars falls back to daily close."""
    svc = _make_service()
    cache = MarketDataCache()

    contract = "O:QQQ240311C00466000"
    daily_ns = _ns("2024-01-02T00:00:00")
    cache.load_option_bars(contract, [
        OptionBar(contract=contract, window_start_ns=daily_ns,
                  open=0.06, high=0.08, low=0.04, close=0.05, volume=10),
    ])

    svc._upq.get_option_minute_bars.return_value = []

    req = MagicMock()
    req.universe.stocks = []
    req.universe.options = [contract]
    req.start_ts = "2024-01-02T00:00:00+00:00"
    req.end_ts = "2024-01-02T23:59:59+00:00"

    await svc._patch_daily_open_with_minute_price(req, cache)

    patched_bar = cache._option_bars[contract][daily_ns]
    assert patched_bar.open == 0.05


# --- Multi-day ---

@pytest.mark.asyncio
async def test_multi_day_each_day_patched_independently():
    """Each daily bar gets its own day's 15:50 minute bar."""
    svc = _make_service()
    cache = MarketDataCache()

    ns_day1 = _ns("2024-01-02T00:00:00")
    ns_day2 = _ns("2024-01-03T00:00:00")
    cache.load_stock_bars("AAPL", [
        StockBar(symbol="AAPL", window_start_ns=ns_day1,
                 open=100.0, high=105.0, low=98.0, close=103.0, volume=1000),
        StockBar(symbol="AAPL", window_start_ns=ns_day2,
                 open=103.0, high=108.0, low=101.0, close=106.0, volume=1200),
    ])

    minute_bars = [
        StockBar(symbol="AAPL", window_start_ns=_ns("2024-01-02T20:50:00"),
                 open=102.50, high=103.0, low=102.0, close=102.80, volume=500),
        StockBar(symbol="AAPL", window_start_ns=_ns("2024-01-03T20:50:00"),
                 open=105.80, high=106.0, low=105.5, close=105.90, volume=600),
    ]
    svc._upq.get_stock_minute_bars.return_value = minute_bars

    req = MagicMock()
    req.universe.stocks = ["AAPL"]
    req.universe.options = []
    req.start_ts = "2024-01-02T00:00:00+00:00"
    req.end_ts = "2024-01-03T23:59:59+00:00"

    await svc._patch_daily_open_with_minute_price(req, cache)

    assert cache._stock_bars["AAPL"][ns_day1].open == 102.50
    assert cache._stock_bars["AAPL"][ns_day2].open == 105.80


# --- DST ---

@pytest.mark.asyncio
async def test_stock_patched_during_edt_summer():
    """During EDT (summer), 15:50 ET = 19:50 UTC."""
    svc = _make_service()
    cache = MarketDataCache()

    # July 15 is during EDT (UTC-4)
    daily_ns = _ns("2024-07-15T00:00:00")
    cache.load_stock_bars("AAPL", [
        StockBar(symbol="AAPL", window_start_ns=daily_ns,
                 open=200.0, high=210.0, low=195.0, close=205.0, volume=1000),
    ])

    # 15:50 EDT = 19:50 UTC
    minute_bars = [
        StockBar(symbol="AAPL", window_start_ns=_ns("2024-07-15T19:50:00"),
                 open=204.50, high=205.0, low=204.0, close=204.80, volume=500),
    ]
    svc._upq.get_stock_minute_bars.return_value = minute_bars

    req = MagicMock()
    req.universe.stocks = ["AAPL"]
    req.universe.options = []
    req.start_ts = "2024-07-15T00:00:00+00:00"
    req.end_ts = "2024-07-15T23:59:59+00:00"

    await svc._patch_daily_open_with_minute_price(req, cache)

    patched_bar = cache._stock_bars["AAPL"][daily_ns]
    assert patched_bar.open == 204.50


# --- Integration: create_session ---

@pytest.mark.asyncio
async def test_create_session_calls_patch_for_daily():
    """Verify create_session invokes patching for daily frequency."""
    upq = AsyncMock()
    upq.get_stock_daily_bars.return_value = [
        StockBar(symbol="AAPL", window_start_ns=_ns("2024-01-02T00:00:00"),
                 open=100.0, high=105.0, low=98.0, close=103.0, volume=1000),
    ]
    upq.get_stock_minute_bars.return_value = [
        StockBar(symbol="AAPL", window_start_ns=_ns("2024-01-02T20:50:00"),
                 open=102.50, high=103.0, low=102.0, close=102.80, volume=500),
    ]

    svc = SessionService(upq)
    req = CreateSessionRequest(
        account_id="test",
        frequency=Frequency.DAILY,
        start_ts="2024-01-02T00:00:00+00:00",
        end_ts="2024-01-02T23:59:59+00:00",
        universe=Universe(stocks=["AAPL"]),
    )
    account = Account(
        account_id="test", initial_cash=100000.0, margin_config=MarginConfig(),
        start_date="2024-01-02", created_at="2024-01-02T00:00:00+00:00",
    )

    session_id, clock = await svc.create_session(req, account)

    state = svc.get_session(session_id)
    daily_ns = _ns("2024-01-02T00:00:00")
    assert state.cache._stock_bars["AAPL"][daily_ns].open == 102.50
