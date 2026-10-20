"""
QFinZero MCP Server

Exposes all QFinZero tools (UPQ, ESP, PMB) as MCP tools for integration
with Claude and other LLM systems.

Run:
    python mcp/server.py
    # or via MCP CLI:
    mcp run mcp/server.py
"""

import json
import sys
import os
from typing import List, Literal, Optional

# Add project root to path so we can import qfinzero clients without modifying the package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import Context, FastMCP

from clients.upq.client import UPQClient
from clients.esp.client import ESPClient
from clients.pmb.client import PMBClient
from qfinzero import timelock
from qfinzero.config import (
    PMB_URL as DEFAULT_PMB_URL,
    ESP_URL as DEFAULT_ESP_URL,
    UPQ_URL as DEFAULT_UPQ_URL,
    DATA_ADMIN_URL as DEFAULT_DATA_ADMIN_URL,
    DASHBOARD_PORT,
    PMB_PORT,
    ESP_PORT,
    UPQ_PORT,
    PLAYGROUND_PORT,
)

# ── Service URLs (can be overridden via env vars) ────────────────────────────

UPQ_URL = os.environ.get("QFINZERO_UPQ_URL", DEFAULT_UPQ_URL)
ESP_URL = os.environ.get("QFINZERO_ESP_URL", DEFAULT_ESP_URL)
PMB_URL = os.environ.get("QFINZERO_PMB_URL", DEFAULT_PMB_URL)
DATA_ADMIN_URL = os.environ.get("QFINZERO_DATA_ADMIN_URL", DEFAULT_DATA_ADMIN_URL)

# ── MCP transport (modern: stdio default; streamable-http for remote/HTTP) ────
MCP_TRANSPORT = os.environ.get("QFINZERO_MCP_TRANSPORT", "stdio")
MCP_HOST = os.environ.get("QFINZERO_MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.environ.get("QFINZERO_MCP_PORT", "19360"))

def _transport_security():
    """Behind the hub the MCP app sees the public Host header; allow the hosts
    listed in QFZ_PUBLIC_HOSTS (comma-separated) in addition to localhost."""
    hosts = [h.strip() for h in os.environ.get("QFZ_PUBLIC_HOSTS", "").split(",") if h.strip()]
    if not hosts:
        return None
    from mcp.server.transport_security import TransportSecuritySettings
    local = ["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*", "[::1]", "[::1]:*"]
    origins = [f"{scheme}://{h}" for h in hosts for scheme in ("http", "https")]
    return TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                     allowed_hosts=local + hosts, allowed_origins=origins)


mcp = FastMCP(
    "QFinZero",
    host=MCP_HOST,
    port=MCP_PORT,
    transport_security=_transport_security(),
    instructions=(
        "QFinZero is a unified trading environment for LLM agents. "
        "It provides three services: UPQ (market data), ESP (news & events), "
        "and PMB (paper trading broker). "
        "Simple day-based trading (recommended for agents): (1) pmb_create_account "
        "with a start_date, (2) gather context via UPQ/ESP tools, (3) pmb_quote / "
        "pmb_trade — omit the price to fill at the REAL UPQ market price, "
        "(4) pmb_end_day then pmb_next_day to advance the trading calendar, "
        "(5) pmb_get_status / pmb_get_history to review. Tune fills, fees, and "
        "leverage via pmb_get_config. "
        "Bar-stepped backtests (advanced): pmb_create_session over a universe, "
        "loop pmb_step_session, place orders with pmb_buy_stock / pmb_sell_stock, "
        "then pmb_get_summary. "
        "Before querying, data_extent / data_coverage say which dates and data "
        "levels the store has, upq_option_expiries lists an underlying's expiries, "
        "and market_calendar gives trading days and the ET session hours "
        "(overnight 20:00-04:00 on Blue Ocean, pre-market, regular, after-hours)."
    ),
)


# ════════════════════════════════════════════════════════════════════════════
# UPQ TOOLS — Market Data
# ════════════════════════════════════════════════════════════════════════════


# ── Time lock ─────────────────────────────────────────────────────────────
# Data tools take an optional session_id. When a session is bound (by the
# X-QFZ-Session connection header, QFZ_TIME_LOCK_SESSION, or session_id), every
# UPQ query is capped at the close of that session's current bar and ESP
# queries run "as of" that time, so an agent cannot read the future.
# QFZ_REQUIRE_SESSION=1 refuses unbound data queries. See qfinzero/timelock.py.

def _header_session(ctx: Optional[Context]) -> Optional[str]:
    try:
        request = ctx.request_context.request if ctx is not None else None
        return request.headers.get(timelock.HEADER) if request is not None else None
    except Exception:  # noqa: BLE001 - stdio transport / no request context
        return None


_IDENTITY = ("x-qfz-user", "x-qfz-role", "x-qfz-user-id")


def _identity(ctx: Optional[Context]) -> dict:
    """The caller identity the hub verified (empty for stdio / unauthenticated)."""
    try:
        request = ctx.request_context.request if ctx is not None else None
        if request is None:
            return {}
        return {h: request.headers[h] for h in _IDENTITY if request.headers.get(h)}
    except Exception:  # noqa: BLE001
        return {}


def _pmb(ctx: Optional[Context] = None) -> PMBClient:
    """PMB client acting as the MCP caller, so accounts are scoped per user."""
    return PMBClient(PMB_URL, headers=_identity(ctx))


def _lock(ctx: Optional[Context], session_id: Optional[str]) -> Optional[str]:
    """``as_of`` for this call, or None when unlocked (raises TimeLockError)."""
    session = timelock.bound_session(_header_session(ctx), session_id)

    def fetch(sid: str) -> dict:
        with _pmb(ctx) as client:
            return client.get_session_state(sid)["clock"]

    return timelock.resolve(session, fetch)


@mcp.tool()
def upq_health() -> str:
    """Check health of the UPQ (Unified Price Query) market data service."""
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.health())


@mcp.tool()
def upq_freshness() -> str:
    """Check data freshness of the UPQ market data service.

    Returns:
        JSON with latest timestamps, record counts, and partition info per data source.
    """
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.freshness())


@mcp.tool()
def upq_stock_daily(
    tickers: list[str],
    start: str,
    end: str,
    fields: Optional[str] = None,
    indicators: Optional[str] = None,
    adjust: Literal["none", "split", "total"] = "none",
    trading_session: Literal["regular", "overnight"] = "regular",
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Query daily OHLCV bars for one or more stocks, with optional technical indicators.

    Args:
        tickers: Stock symbols, e.g. ["AAPL", "NVDA", "SPY"]
        start: Start date "YYYY-MM-DD"
        end: End date "YYYY-MM-DD"
        fields: Comma-separated fields to return, e.g. "date,close,volume"
                Available: ticker, date, open, high, low, close, volume, transactions
        indicators: Comma-separated technical indicators, e.g. "ma_20,ema_12,macd"
                    Supported: ma_N (Simple Moving Average), ema_N (Exponential Moving Average),
                    macd (MACD 12/26/9 — returns macd, macd_signal, macd_histogram columns).
        adjust: "none" = as traded (default); "split" = split-adjusted;
                "total" = split- and dividend-adjusted (for returns over long windows)
        trading_session: "regular" (default) = the exchange day; "overnight" = one bar
                per Blue Ocean 20:00-04:00 ET session, dated by the trading day it
                precedes (Sunday night + Monday morning = Monday), final at 04:00 ET
        session_id: Optional PMB session to time-lock this query to (data after
            the session's current bar is hidden, enforced server-side).

    Returns:
        JSON list of daily bar objects with indicator columns appended when requested.
    """
    as_of = _lock(ctx, session_id)
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.stock_daily(
            tickers=tickers, start=start, end=end,
            fields=fields, indicators=indicators, as_of=as_of,
            adjust=None if adjust == "none" else adjust,
            session=None if trading_session == "regular" else trading_session,
        ))


@mcp.tool()
def upq_stock_minute(
    tickers: list[str],
    start: str,
    end: str,
    fields: Optional[str] = None,
    limit: int = 10000,
    adjust: Literal["none", "split", "total"] = "none",
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Query minute-level OHLCV bars for one or more stocks.

    Args:
        tickers: Stock symbols, e.g. ["AAPL", "NVDA"]
        start: Start datetime in UTC "YYYY-MM-DDTHH:MM:SS", e.g. "2024-01-15T14:30:00" (09:30 ET)
        end: End datetime in UTC "YYYY-MM-DDTHH:MM:SS", e.g. "2024-01-15T21:00:00" (16:00 ET)
        fields: Comma-separated fields, e.g. "ticker,window_start,close,volume"
                Available: ticker, window_start, open, high, low, close, volume, transactions
        limit: Max rows to return (default 10000, max 100000)
        adjust: "none" = as traded (default); "split" or "total" as in upq_stock_daily
        session_id: Optional PMB session to time-lock this query to (data after
            the session's current bar is hidden, enforced server-side).

    Returns:
        JSON list of minute bar objects. window_start is nanoseconds since epoch.
        Use upq_ns_to_iso to convert timestamps.
    """
    as_of = _lock(ctx, session_id)
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.stock_minute(
            tickers=tickers, start=start, end=end, fields=fields, limit=limit, as_of=as_of,
            adjust=None if adjust == "none" else adjust))


@mcp.tool()
def upq_option_chain(
    underlying: str,
    date: str,
    expiry_min: Optional[str] = None,
    expiry_max: Optional[str] = None,
    strike_min: Optional[float] = None,
    strike_max: Optional[float] = None,
    option_type: Optional[str] = None,
    fields: Optional[str] = None,
    include_greeks: bool = False,
    greek_model: Optional[str] = None,
    greek_price_field: Optional[str] = None,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Query the full option chain for an underlying stock on a given date.

    Args:
        underlying: Stock symbol, e.g. "NVDA"
        date: Trade date "YYYY-MM-DD"
        expiry_min: Min expiry date filter "YYYY-MM-DD"
        expiry_max: Max expiry date filter "YYYY-MM-DD"
        strike_min: Min strike price filter
        strike_max: Max strike price filter
        option_type: "C" for calls, "P" for puts (omit for both)
        fields: Comma-separated fields to return
        include_greeks: When True, append BSM-European Greeks (iv, delta,
            gamma, theta, vega, rho, greek_status, greek_meta) to each row.
            Greeks use European-style approximation for American options.
        greek_model: Pricing model — only "bsm" supported in V1
        greek_price_field: Price field for IV inversion — only "close" in V1
        session_id: Optional PMB session to time-lock this query to (data after
            the session's current bar is hidden, enforced server-side).

    Returns:
        JSON list of option contract objects. When include_greeks=True,
        each row includes iv, delta, gamma, theta, vega, rho, greek_status,
        and greek_meta fields. Check greek_status for computation outcome.

    Notes:
        If `expiry_min` equals `expiry_max` (exact expiry) and no exact rows exist,
        UPQ automatically falls back to nearest available expiry (±7 days first,
        then same calendar month) within the same underlying/type/strike filter context.
    """
    as_of = _lock(ctx, session_id)
    with UPQClient(UPQ_URL) as client:
        return json.dumps(
            client.option_chain(
                as_of=as_of,
                underlying=underlying,
                date=date,
                expiry_min=expiry_min,
                expiry_max=expiry_max,
                strike_min=strike_min,
                strike_max=strike_max,
                type=option_type,
                fields=fields,
                include_greeks=include_greeks,
                greek_model=greek_model,
                greek_price_field=greek_price_field,
            )
        )


@mcp.tool()
def upq_option_contract(
    contract: str,
    start: str,
    end: str,
    resolution: Literal["day", "minute"] = "day",
    fields: Optional[str] = None,
    include_greeks: bool = False,
    greek_model: Optional[str] = None,
    greek_price_field: Optional[str] = None,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Query price history for a specific option contract.

    Args:
        contract: OPRA contract string, e.g. "O:NVDA250117C00136000"
                  Use upq_make_opra() to build the contract string.
        start: Start date/datetime in UTC, e.g. "2024-01-15" or "2024-01-15T14:30:00" (09:30 ET)
        end: End date/datetime in UTC, e.g. "2024-01-17" or "2024-01-15T21:00:00" (16:00 ET)
        resolution: "day" (default) or "minute"
        fields: Comma-separated fields to return
        include_greeks: When True, append BSM-European Greeks (iv, delta,
            gamma, theta, vega, rho, greek_status, greek_meta) to each row.
            Greeks use European-style approximation for American options.
        greek_model: Pricing model — only "bsm" supported in V1
        greek_price_field: Price field for IV inversion — only "close" in V1
        session_id: Optional PMB session to time-lock this query to (data after
            the session's current bar is hidden, enforced server-side).

    Returns:
        JSON list of price bars for the contract.
        Day resolution also includes underlying, expiry, strike, type.
        When include_greeks=True, each row includes iv, delta, gamma, theta,
        vega, rho, greek_status, and greek_meta fields.
    """
    as_of = _lock(ctx, session_id)
    with UPQClient(UPQ_URL) as client:
        return json.dumps(
            client.option_contract(
                as_of=as_of,
                contract=contract,
                start=start,
                end=end,
                resolution=resolution,
                fields=fields,
                include_greeks=include_greeks,
                greek_model=greek_model,
                greek_price_field=greek_price_field,
            )
        )


@mcp.tool()
def upq_dividends(
    tickers: list[str],
    start: str,
    end: str,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Query dividend history for stocks/ETFs.

    Args:
        tickers: Stock/ETF symbols, e.g. ["JEPQ", "AAPL"]
        start: Start date "YYYY-MM-DD"
        end: End date "YYYY-MM-DD"
        session_id: Optional PMB session to time-lock this query to (data after
            the session's current bar is hidden, enforced server-side).

    Returns:
        JSON list of dividend objects with ticker, ex_dividend_date, amount.
    """
    as_of = _lock(ctx, session_id)
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.dividends(tickers=tickers, start=start, end=end, as_of=as_of))


@mcp.tool()
def upq_rates(
    start: str,
    end: str,
    tenors: Optional[str] = None,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Query US Treasury yield rates.

    Args:
        start: Start date "YYYY-MM-DD"
        end: End date "YYYY-MM-DD"
        tenors: Comma-separated tenor codes, e.g. "1M,3M,1Y,2Y,5Y,10Y,30Y"
                Omit for all tenors.
        session_id: Optional PMB session to time-lock this query to (data after
            the session's current bar is hidden, enforced server-side).

    Returns:
        JSON list of daily rate objects with one field per tenor.
    """
    as_of = _lock(ctx, session_id)
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.rates(start=start, end=end, tenors=tenors, as_of=as_of))


@mcp.tool()
def upq_stock_quote(
    tickers: list[str],
    start: str,
    end: str,
    limit: int = 10000,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Minute NBBO (bid/ask price and size) for stocks.

    Each row is the book at the end of the minute ``window_start`` (ns since
    epoch); minutes without a change are absent, so carry the previous row
    forward.

    Args:
        tickers: Symbols, e.g. ["AAPL"]
        start: ISO datetime (UTC), e.g. "2026-01-07T14:30:00"
        end: ISO datetime (UTC)
        limit: Max rows (default 10000)
        session_id: Optional PMB session to time-lock this query to (data after
            the session's current bar is hidden, enforced server-side).
    """
    as_of = _lock(ctx, session_id)
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.stock_quote(tickers, start, end, limit=limit, as_of=as_of))


@mcp.tool()
def upq_future_minute(
    start: str,
    end: str,
    tickers: Optional[list[str]] = None,
    roots: Optional[list[str]] = None,
    limit: int = 10000,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Futures minute bars (CME Globex and other futures venues).

    A ticker is a contract (``ZNZ6``, ``CLX6``) or, for front-month continuous
    data, the product root (``ZN``, ``CL``, ``GC``); ``roots`` returns every
    series of a product. Rows: ticker, root, window_start (ns since epoch),
    open, high, low, close, volume, transactions. Sessions run 18:00 ET the
    evening before to 17:00 ET.

    Args:
        start: ISO datetime (UTC), e.g. "2026-09-02T13:00:00"
        end: ISO datetime (UTC)
        tickers: Contracts or roots, e.g. ["ZN"]
        roots: Products, e.g. ["ZN", "CL"] (all their contracts)
        limit: Max rows (default 10000)
        session_id: Optional PMB session to time-lock this query to.
    """
    as_of = _lock(ctx, session_id)
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.future_minute(tickers, start, end, roots=roots, limit=limit, as_of=as_of))


@mcp.tool()
def upq_future_daily(
    start: str,
    end: str,
    tickers: Optional[list[str]] = None,
    roots: Optional[list[str]] = None,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Futures daily bars per CME session with ``settle``, the price daily
    variation margin marks to. Session D (18:00 ET on D-1 to 17:00 ET on D) is
    final at 17:00 ET on D.

    Args:
        start: Date, e.g. "2026-09-01"
        end: Date
        tickers: Contracts or roots, e.g. ["CL"]
        roots: Products (all their contracts)
        session_id: Optional PMB session to time-lock this query to.
    """
    as_of = _lock(ctx, session_id)
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.future_daily(tickers, start, end, roots=roots, as_of=as_of))


@mcp.tool()
def upq_future_quote(
    start: str,
    end: str,
    tickers: Optional[list[str]] = None,
    roots: Optional[list[str]] = None,
    limit: int = 10000,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Futures top of book (bid/ask price and size). Each row is the book at the
    end of the minute ``window_start``; minutes without a row keep the previous
    book (the store may also be sampled every 5-60 minutes).

    Args:
        start: ISO datetime (UTC)
        end: ISO datetime (UTC)
        tickers: Contracts or roots, e.g. ["ZN"]
        roots: Products (all their contracts)
        limit: Max rows (default 10000)
        session_id: Optional PMB session to time-lock this query to.
    """
    as_of = _lock(ctx, session_id)
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.future_quote(tickers, start, end, roots=roots, limit=limit, as_of=as_of))



@mcp.tool()
def upq_crypto_minute(
    tickers: list[str],
    start: str,
    end: str,
    limit: int = 10000,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Crypto minute bars (massive global crypto, e.g. BTC-USD, ETH-USD, SOL-USD).

    Rows: ticker, base, quote, window_start (ns since epoch), open, high, low,
    close, volume (in the base coin), transactions.

    Args:
        tickers: Pairs, e.g. ["BTC-USD", "ETH-USD"]
        start: ISO datetime (UTC), e.g. "2026-02-24T00:00:00"
        end: ISO datetime (UTC)
        limit: Max rows (default 10000)
        session_id: Optional PMB session to time-lock this query to.
    """
    as_of = _lock(ctx, session_id)
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.crypto_minute(tickers, start, end, limit=limit, as_of=as_of))


@mcp.tool()
def upq_crypto_daily(
    tickers: list[str],
    start: str,
    end: str,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Crypto daily bars by UTC day; day D is final at 00:00 UTC on D+1.

    Args:
        tickers: Pairs, e.g. ["BTC-USD"]
        start: Date "YYYY-MM-DD"
        end: Date "YYYY-MM-DD"
        session_id: Optional PMB session to time-lock this query to.
    """
    as_of = _lock(ctx, session_id)
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.crypto_daily(tickers, start, end, as_of=as_of))


@mcp.tool()
def upq_fx_minute(
    tickers: list[str],
    start: str,
    end: str,
    limit: int = 10000,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """FX minute bars (massive global forex, about 1,200 pairs: EUR-USD, USD-JPY, ...).

    Rows: ticker, base, quote, window_start (ns), open, high, low, close,
    volume (the number of quotes in the minute), transactions.

    Args:
        tickers: Pairs, e.g. ["EUR-USD", "USD-JPY"]
        start: ISO datetime (UTC)
        end: ISO datetime (UTC)
        limit: Max rows (default 10000)
        session_id: Optional PMB session to time-lock this query to.
    """
    as_of = _lock(ctx, session_id)
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.fx_minute(tickers, start, end, limit=limit, as_of=as_of))


@mcp.tool()
def upq_fx_daily(
    tickers: list[str],
    start: str,
    end: str,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """FX daily bars by UTC day; day D is final at 00:00 UTC on D+1.

    Args:
        tickers: Pairs, e.g. ["EUR-USD"]
        start: Date "YYYY-MM-DD"
        end: Date "YYYY-MM-DD"
        session_id: Optional PMB session to time-lock this query to.
    """
    as_of = _lock(ctx, session_id)
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.fx_daily(tickers, start, end, as_of=as_of))


@mcp.tool()
def upq_fx_quote(
    tickers: list[str],
    start: str,
    end: str,
    limit: int = 10000,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """FX bid and ask. Each row is the last quote of the minute ``window_start``;
    minutes without a row keep the previous quote (the store may also be sampled
    every 5-60 minutes). massive FX quotes carry no sizes.

    Args:
        tickers: Pairs, e.g. ["EUR-USD"]
        start: ISO datetime (UTC)
        end: ISO datetime (UTC)
        limit: Max rows (default 10000)
        session_id: Optional PMB session to time-lock this query to.
    """
    as_of = _lock(ctx, session_id)
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.fx_quote(tickers, start, end, limit=limit, as_of=as_of))


@mcp.tool()
def upq_option_quote(
    contract: str,
    start: str,
    end: str,
    limit: int = 10000,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Minute NBBO for one option contract (rows as in upq_stock_quote).

    Args:
        contract: OPRA contract, e.g. "O:SPY260107C00690000"
        start: ISO datetime (UTC)
        end: ISO datetime (UTC)
        limit: Max rows (default 10000)
        session_id: Optional PMB session to time-lock this query to (data after
            the session's current bar is hidden, enforced server-side).
    """
    as_of = _lock(ctx, session_id)
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.option_quote(contract, start, end, limit=limit, as_of=as_of))


@mcp.tool()
def upq_chain_snapshot(
    underlying: str,
    at: Optional[str] = None,
    expiry_min: Optional[str] = None,
    expiry_max: Optional[str] = None,
    strike_min: Optional[float] = None,
    strike_max: Optional[float] = None,
    option_type: Optional[str] = None,
    include_greeks: bool = False,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """The intraday option chain as it stood at a moment.

    Per contract: last trade price and time, volume so far today, latest
    bid/ask/size and mid, and (include_greeks) IV and Greeks priced off the
    mid with the underlying's minute close. Use this instead of
    upq_option_chain (end-of-day) during a trading session.

    Args:
        underlying: e.g. "SPY"
        at: ISO datetime (UTC). Defaults to the locked session's current time.
        expiry_min / expiry_max: YYYY-MM-DD bounds
        strike_min / strike_max: strike bounds
        option_type: "C" or "P"
        include_greeks: add iv, delta, gamma, theta, vega, rho
        session_id: Optional PMB session to time-lock this query to (data after
            the session's current bar is hidden, enforced server-side).
    """
    as_of = _lock(ctx, session_id)
    at = at or as_of
    if not at:
        raise ValueError("pass at (ISO datetime) or a session_id")
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.chain_snapshot(
            underlying, timelock.utc_iso(at), expiry_min=expiry_min, expiry_max=expiry_max,
            strike_min=strike_min, strike_max=strike_max, type=option_type,
            include_greeks=include_greeks, as_of=as_of))


@mcp.tool()
def upq_make_opra(
    underlying: str,
    expiry: str,
    right: str,
    strike: float,
) -> str:
    """Build an OPRA option contract identifier string.

    Args:
        underlying: Stock symbol, e.g. "NVDA"
        expiry: Expiry date "YYYY-MM-DD", e.g. "2025-01-17"
        right: "C" for call or "P" for put
        strike: Strike price, e.g. 136.0

    Returns:
        OPRA contract string, e.g. "O:NVDA250117C00136000"
        Pass this to upq_option_contract or pmb_buy_option / pmb_sell_option.
    """
    return json.dumps(UPQClient.make_opra(underlying=underlying, expiry=expiry, right=right, strike=strike))


@mcp.tool()
def upq_ns_to_iso(ns: int) -> str:
    """Convert a nanosecond Unix timestamp to an ISO 8601 UTC datetime string.

    Args:
        ns: Nanosecond timestamp (as returned in window_start from upq_stock_minute)

    Returns:
        ISO 8601 datetime string in UTC, e.g. "2024-01-15T09:30:00+00:00"
    """
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ns / 1_000_000_000, tz=timezone.utc).isoformat()


# ════════════════════════════════════════════════════════════════════════════
# ESP TOOLS — News & Events
# ════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def esp_health() -> str:
    """Check health of the ESP (News Pushing Pipeline) service and data freshness."""
    with ESPClient(ESP_URL) as client:
        return json.dumps(client.health())


@mcp.tool()
def esp_query_events(
    mode: str = "window",
    start_utc: Optional[str] = None,
    end_utc: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    horizon_minutes: int = 60,
    event_types: Optional[list[str]] = None,
    tickers: Optional[list[str]] = None,
    min_importance: Optional[str] = None,
    limit: int = 50,
    cursor: Optional[str] = None,
    view: Literal["compact", "full"] = "full",
    now_utc: Optional[str] = None,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Query unified events from all sources (news, earnings, economic calendar).

    Args:
        mode: Query mode (default "window"):
              "upcoming"      — events after now (set horizon_minutes)
              "just_happened" — events that recently occurred (set horizon_minutes)
              "window"        — events in a specific range (set start_utc + end_utc)
        start_utc: Window start ISO datetime (required for "window" mode)
        end_utc: Window end ISO datetime (required for "window" mode)
        start_date: Alternative to start_utc — date string "YYYY-MM-DD"
        end_date: Alternative to end_utc — date string "YYYY-MM-DD"
        horizon_minutes: Lookahead/lookback in minutes for upcoming/just_happened (default 60)
        event_types: Filter by type — any subset of:
                     ["macro_calendar", "earnings", "breaking_news", "daily_news"]
        tickers: Filter to events related to these stock symbols, e.g. ["AAPL", "NVDA"]
        min_importance: "low", "medium", or "high"
        limit: Max events to return per page (default 50)
        cursor: Pagination cursor from a previous response's next_cursor field
        view: "compact" (no payload, faster) or "full" (includes event payload, default "full")
        now_utc: Override current time for backtesting replay (ISO datetime)
        session_id: Optional PMB session to time-lock this query to (data after
            the session's current bar is hidden, enforced server-side).

    Returns:
        JSON with: server_time_utc, events[], next_cursor
        Each event has: event_id, event_type, title, time_utc, importance, tickers, snippet
    """
    # Convert start_date/end_date to start_utc/end_utc if provided
    if start_date and not start_utc:
        start_utc = f"{start_date}T00:00:00+00:00"
    if end_date and not end_utc:
        end_utc = f"{end_date}T23:59:59+00:00"

    as_of = _lock(ctx, session_id)
    if as_of:
        now_utc = as_of
        if mode == "window":
            end_utc = timelock.clamp_end(end_utc, as_of)
    with ESPClient(ESP_URL) as client:
        return json.dumps(
            client.query_events(
                mode=mode,
                start_utc=start_utc,
                end_utc=end_utc,
                horizon_minutes=horizon_minutes,
                event_types=event_types,
                tickers=tickers,
                min_importance=min_importance,
                limit=limit,
                cursor=cursor,
                view=view,
                now_utc=now_utc,
            )
        )


@mcp.tool()
def esp_get_event(
    event_id: str,
    now_utc: Optional[str] = None,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Fetch a single event by its ID, including full payload.

    Args:
        event_id: The unique event identifier (from esp_query_events results)
        now_utc: Replay time (ISO); results not yet released at that time are blanked
        session_id: Optional PMB session to time-lock this lookup to

    Returns:
        JSON event object with full payload (earnings data, economic release values, etc.)
    """
    as_of = _lock(ctx, session_id)
    if as_of:
        now_utc = as_of
    with ESPClient(ESP_URL) as client:
        return json.dumps(client.get_event(event_id, now_utc=now_utc))


@mcp.tool()
def esp_stream_events(
    cursor: Optional[str] = None,
    event_types: Optional[list[str]] = None,
    tickers: Optional[list[str]] = None,
    limit: int = 50,
    now_utc: Optional[str] = None,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Incrementally poll for new events since a cursor position.

    Use this for continuous monitoring — call with the next_cursor from the
    previous response to get only new events that arrived since then.

    Args:
        cursor: Cursor string from a previous query_events or stream response
        event_types: Filter by event types
        tickers: Filter by stock tickers
        limit: Max events per batch (default 50)
        now_utc: Override current time for backtesting replay (ISO datetime)
        session_id: Optional PMB session to time-lock this query to (data after
            the session's current bar is hidden, enforced server-side).

    Returns:
        JSON with: server_time_utc, events[], next_cursor
    """
    as_of = _lock(ctx, session_id)
    if as_of:
        now_utc = as_of
    with ESPClient(ESP_URL) as client:
        return json.dumps(
            client.stream(
                cursor=cursor,
                event_types=event_types,
                tickers=tickers,
                limit=limit,
                now_utc=now_utc,
            )
        )


@mcp.tool()
def esp_econ_calendar(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    min_importance: Optional[str] = None,
    limit: int = 100,
    cursor: Optional[str] = None,
    now_utc: Optional[str] = None,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Query the US economic events calendar (GDP, CPI, FOMC, jobs data, PMI, etc.).

    Args:
        start_date: Start date "YYYY-MM-DD"
        end_date: End date "YYYY-MM-DD"
        min_importance: "low", "medium", or "high"
        limit: Max events per page (default 100)
        cursor: Pagination cursor
        now_utc: Override current time for backtesting replay (ISO datetime)
        session_id: Optional PMB session to time-lock this query to (data after
            the session's current bar is hidden, enforced server-side).

    Returns:
        JSON with: server_time_utc, events[], next_cursor
    """
    as_of = _lock(ctx, session_id)
    if as_of:
        now_utc = as_of
    with ESPClient(ESP_URL) as client:
        return json.dumps(
            client.econ_calendar(
                start_date=start_date,
                end_date=end_date,
                min_importance=min_importance,
                limit=limit,
                cursor=cursor,
                now_utc=now_utc,
            )
        )


@mcp.tool()
def esp_earnings_calendar(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tickers: Optional[list[str]] = None,
    min_importance: int = 0,
    limit: int = 100,
    cursor: Optional[str] = None,
    now_utc: Optional[str] = None,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Query the earnings release calendar.

    Args:
        start_date: Start date "YYYY-MM-DD"
        end_date: End date "YYYY-MM-DD"
        tickers: Filter by stock symbols, e.g. ["AAPL", "NVDA", "MSFT"]
        min_importance: Minimum importance score 0-5 (5 = most important)
        limit: Max events per page (default 100)
        cursor: Pagination cursor
        now_utc: Override current time for backtesting replay (ISO datetime)
        session_id: Optional PMB session to time-lock this query to (data after
            the session's current bar is hidden, enforced server-side).

    Returns:
        JSON with: server_time_utc, events[], next_cursor
    """
    as_of = _lock(ctx, session_id)
    if as_of:
        now_utc = as_of
    with ESPClient(ESP_URL) as client:
        return json.dumps(
            client.earnings_calendar(
                start_date=start_date,
                end_date=end_date,
                tickers=tickers,
                min_importance=min_importance,
                limit=limit,
                cursor=cursor,
                now_utc=now_utc,
            )
        )


@mcp.tool()
def esp_next_triggers(
    tickers: Optional[list[str]] = None,
    min_importance: Optional[str] = None,
    horizon_minutes: int = 1440,
    limit: int = 5,
    now_utc: Optional[str] = None,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Get the next high-importance events to use as agent wakeup triggers.

    Use this to schedule when the agent should next run — it returns upcoming
    market-moving events (earnings releases, FOMC meetings, major economic data).

    Args:
        tickers: Watchlist stocks to monitor, e.g. ["AAPL", "NVDA"]
        min_importance: "low", "medium" (default), or "high"
        horizon_minutes: How far ahead to look in minutes (default 1440 = 24h)
        limit: Max triggers to return (default 5)
        now_utc: Override current time for backtesting replay (ISO datetime)
        session_id: Optional PMB session to time-lock this query to (data after
            the session's current bar is hidden, enforced server-side).

    Returns:
        JSON with: server_time_utc, triggers[]
        Each trigger has: trigger_time_utc, event_id, event, reason_codes
    """
    as_of = _lock(ctx, session_id)
    if as_of:
        now_utc = as_of
    with ESPClient(ESP_URL) as client:
        return json.dumps(
            client.next_triggers(
                tickers=tickers,
                min_importance=min_importance,
                horizon_minutes=horizon_minutes,
                limit=limit,
                now_utc=now_utc,
            )
        )


@mcp.tool()
def esp_news_body(
    news_id: str,
    now_utc: Optional[str] = None,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Fetch the full body of a news article.

    Args:
        news_id: The news article ID (found in event payload from esp_query_events)
        now_utc: Replay time (ISO); articles published later are reported as not found
        session_id: Optional PMB session to time-lock this lookup to

    Returns:
        JSON with: news_id, title, description, article_url, published_utc,
                   tickers, author, keywords, image_url, publisher, insights
    """
    as_of = _lock(ctx, session_id)
    if as_of:
        now_utc = as_of
    with ESPClient(ESP_URL) as client:
        return json.dumps(client.news_body(news_id, now_utc=now_utc))


@mcp.tool()
def esp_search_news(
    tickers: Optional[list[str]] = None,
    start_utc: Optional[str] = None,
    end_utc: Optional[str] = None,
    keyword: Optional[str] = None,
    publisher: Optional[str] = None,
    limit: int = 20,
    cursor: Optional[str] = None,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Search news articles with keyword and publisher filtering.

    Args:
        tickers: Filter by stock symbols, e.g. ["AAPL", "NVDA"]
        start_utc: Window start ISO datetime (default: now - 7 days)
        end_utc: Window end ISO datetime (default: now)
        keyword: Case-insensitive substring search in article title
        publisher: Case-insensitive substring search in publisher name
        limit: Max articles per page (1-500, default 50)
        cursor: Pagination cursor from previous response's next_cursor field
        session_id: Optional PMB session to time-lock this query to (data after
            the session's current bar is hidden, enforced server-side).

    Returns:
        JSON with: server_time_utc, events[], next_cursor
    """
    as_of = _lock(ctx, session_id)
    now_utc = None
    if as_of:
        end_utc = timelock.clamp_end(end_utc, as_of)
        now_utc = as_of
    with ESPClient(ESP_URL) as client:
        return json.dumps(
            client.search_news(
                tickers=tickers,
                start_utc=start_utc,
                end_utc=end_utc,
                keyword=keyword,
                publisher=publisher,
                limit=limit,
                cursor=cursor,
                now_utc=now_utc,
            )
        )


@mcp.tool()
def esp_timeline(
    tickers: Optional[list[str]] = None,
    start_utc: Optional[str] = None,
    end_utc: Optional[str] = None,
    bucket_minutes: int = 60,
    now_utc: Optional[str] = None,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Get a compact time-bucketed summary of events for specific tickers.

    Useful for scanning what happened to a stock over a period without
    fetching every individual event.

    Args:
        tickers: Stock symbols to fetch timeline for, e.g. ["AAPL", "NVDA"]
        start_utc: Start datetime ISO format
        end_utc: End datetime ISO format
        bucket_minutes: Bucket size in minutes (default 60 = hourly buckets)
        now_utc: Override current time for backtesting replay (ISO datetime)
        session_id: Optional PMB session to time-lock this query to (data after
            the session's current bar is hidden, enforced server-side).

    Returns:
        JSON with: server_time_utc, buckets[]
        Each bucket has: bucket_start_utc, bucket_end_utc, count, events[]
    """
    as_of = _lock(ctx, session_id)
    if as_of:
        now_utc = as_of
        end_utc = timelock.clamp_end(end_utc, as_of)
    with ESPClient(ESP_URL) as client:
        return json.dumps(
            client.timeline(
                tickers=tickers,
                start_utc=start_utc,
                end_utc=end_utc,
                bucket_minutes=bucket_minutes,
                now_utc=now_utc,
            )
        )


# ════════════════════════════════════════════════════════════════════════════
# RESEARCH TOOLS — intraday factor mining over UPQ storage
# ════════════════════════════════════════════════════════════════════════════

RESEARCH_MAX_DAYS = int(os.environ.get("QFZ_RESEARCH_MAX_DAYS", "40"))
RESEARCH_MAX_UNIVERSE = int(os.environ.get("QFZ_RESEARCH_MAX_UNIVERSE", "1000"))


def _research_window(start: str, end: str, universe, as_of: Optional[str]):
    """Validate limits and apply the time lock (end capped at as_of's date)."""
    from datetime import date as _date
    from qfinzero.research.data import valid_symbol
    end = timelock.clamp_date(end, as_of) or end
    if (_date.fromisoformat(end) - _date.fromisoformat(start)).days > RESEARCH_MAX_DAYS * 7 // 5 + 3:
        raise ValueError(f"window too long (max ~{RESEARCH_MAX_DAYS} trading days)")
    if isinstance(universe, list):
        bad = [t for t in universe if not valid_symbol(t)]
        if bad or len(universe) > RESEARCH_MAX_UNIVERSE:
            raise ValueError(f"universe must be <= {RESEARCH_MAX_UNIVERSE} valid tickers")
    elif not 1 <= int(universe) <= RESEARCH_MAX_UNIVERSE:
        raise ValueError(f"universe size must be 1..{RESEARCH_MAX_UNIVERSE}")
    as_of_ns = None
    if as_of:
        from datetime import datetime as _dt
        as_of_ns = int(_dt.fromisoformat(as_of.replace("Z", "+00:00")).timestamp() * 1e9)
    return end, as_of_ns


@mcp.tool()
def research_eval_factor(
    expression: str,
    start: str,
    end: str,
    universe: Optional[List[str]] = None,
    top_n: int = 500,
    horizons: Optional[List[int]] = None,
    bar_minutes: int = 1,
    session: Literal["regular", "extended"] = "regular",
    cross_day: bool = False,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Evaluate an intraday factor: IC, rank IC, ICIR, t-stats, quantile returns,
    long-short spread, turnover and IC by hour, for each forward horizon.

    The factor is one expression over per-minute fields, e.g.
    "cs_rank(-pct(close, 15))" or "ts_zscore(close - vwap, 60) * cs_rank(volume)".
    Fields: open high low close volume transactions vwap ret minute
    (+ bid ask mid spread imbalance when stock quotes exist).
    Functions: ts_mean ts_sum ts_std ts_min ts_max ts_zscore (x, n);
    ts_corr ts_cov (x, y, n); delay delta pct (x, n>=1); cs_rank cs_zscore
    cs_demean (x); abs log sign sqrt; max min (a, b). Windows only look back and
    reset each day unless cross_day. Signals trade at the next bar's open.

    Args:
        expression: the factor
        start / end: YYYY-MM-DD trading-day range
        universe: explicit tickers; default is top_n by prior-day dollar volume
        top_n: size of the default universe (default 500)
        horizons: forward horizons in bars (default [5, 15, 30])
        bar_minutes: bar size (1, 5, 15, ...)
        session: "regular" (default) or "extended" hours
        cross_day: let time-series windows span days
        session_id: Optional PMB session to time-lock this query to (data after
            the session's current bar is hidden, enforced server-side).
    """
    from qfinzero.research import EvalConfig, evaluate_factor
    as_of = _lock(ctx, session_id)
    uni = universe or top_n
    end, as_of_ns = _research_window(start, end, uni, as_of)
    res = evaluate_factor(EvalConfig(
        expression=expression, start=start, end=end, universe=uni,
        horizons=horizons or [5, 15, 30], bar_minutes=bar_minutes, session=session,
        cross_day=cross_day, as_of_ns=as_of_ns))
    return json.dumps(res, default=str)


@mcp.tool()
def research_backtest(
    expression: str,
    start: str,
    end: str,
    universe: Optional[List[str]] = None,
    top_n: int = 500,
    rebalance: int = 15,
    fraction: float = 0.1,
    long_short: bool = True,
    cost_bps: float = 0.5,
    bar_minutes: int = 1,
    session: Literal["regular", "extended"] = "regular",
    cross_day: bool = False,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Backtest a factor as an intraday portfolio: every `rebalance` bars hold the
    top (and short the bottom) `fraction` of names equal-weighted, enter at the
    next bar's open, flat at the close. Costs: cost_bps per unit traded plus
    half the quoted spread (2 bps assumed without quotes).

    Returns total return, Sharpe (daily, annualised), max drawdown, hit rate,
    turnover, gross vs cost, and the daily equity curve. Same expression
    language as research_eval_factor.

    Args:
        expression: the factor
        start / end: YYYY-MM-DD trading-day range
        universe: explicit tickers; default is top_n by prior-day dollar volume
        top_n: size of the default universe (default 500)
        rebalance: bars between rebalances (default 15)
        fraction: share of names held per side (default 0.1)
        long_short: short the bottom fraction too (default true)
        cost_bps: per-unit trading cost on top of the half-spread
        bar_minutes: bar size (1, 5, 15, ...)
        session: "regular" (default) or "extended" hours
        cross_day: let time-series windows span days
        session_id: Optional PMB session to time-lock this query to (data after
            the session's current bar is hidden, enforced server-side).
    """
    from qfinzero.research import BacktestConfig, backtest_factor
    as_of = _lock(ctx, session_id)
    uni = universe or top_n
    end, as_of_ns = _research_window(start, end, uni, as_of)
    res = backtest_factor(BacktestConfig(
        expression=expression, start=start, end=end, universe=uni, rebalance=rebalance,
        fraction=fraction, long_short=long_short, cost_bps=cost_bps, bar_minutes=bar_minutes,
        session=session, cross_day=cross_day, as_of_ns=as_of_ns))
    return json.dumps(res, default=str)


# ════════════════════════════════════════════════════════════════════════════
# PMB TOOLS — Paper Money Broker (Trading Simulation)
# ════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def pmb_health(ctx: Context = None) -> str:
    """Check health of the PMB (Paper Money Broker) trading simulation service."""
    with _pmb(ctx) as client:
        return json.dumps(client.health())


@mcp.tool()
def pmb_create_account(
    start_date: str,
    initial_cash: Optional[float] = None,
    market: Optional[Literal["us", "cn", "hk"]] = None,
    account_type: Literal["MARGIN", "CASH"] = "MARGIN",
    ctx: Context = None,
) -> str:
    """Allocate a new paper trading (broker) account.

    Args:
        start_date: Account open date "YYYY-MM-DD" (required — the first trading day)
        initial_cash: Starting cash; omit to use the broker default (pmb_get_config)
        market: "us", "cn", or "hk"; omit to use the broker default. Determines the
                account-number prefix, base currency, and exchange timezone.
        account_type: "MARGIN" (default) or "CASH"

    Returns:
        JSON with: account_id (a unique 10-digit number), market, created_at, account.
        Save the account_id — you'll need it for all subsequent calls.
    """
    with _pmb(ctx) as client:
        return json.dumps(
            client.create_account(
                initial_cash=initial_cash,
                account_type=account_type,
                market=market,
                open_date=start_date,
            )
        )


@mcp.tool()
def pmb_get_account(account_id: str,
    ctx: Context = None,
) -> str:
    """Get the current state of a paper trading account.

    Args:
        account_id: The account identifier from pmb_create_account

    Returns:
        JSON with: cash_available, cash_locked, loan, equity, buying_power,
                   margin_status, positions summary
    """
    with _pmb(ctx) as client:
        return json.dumps(client.get_account(account_id))


@mcp.tool()
def pmb_get_positions(account_id: str,
    ctx: Context = None,
) -> str:
    """List all current open positions in a paper trading account.

    Args:
        account_id: The account identifier

    Returns:
        JSON list of position objects with:
        symbol, qty, avg_cost, market_value, unrealized_pnl, side
    """
    with _pmb(ctx) as client:
        return json.dumps(client.get_positions(account_id))


@mcp.tool()
def pmb_get_orders(
    account_id: str,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Query orders for an account, optionally filtered by session.

    Args:
        account_id: The account identifier
        session_id: Optional — filter to orders from a specific session

    Returns:
        JSON list of order objects with: order_id, symbol, side, order_type,
        qty, filled_qty, avg_fill_price, status, created_ts
    """
    with _pmb(ctx) as client:
        return json.dumps(client.get_orders(account_id=account_id, session_id=session_id))


@mcp.tool()
def pmb_get_trades(
    account_id: str,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Query executed trades for an account, optionally filtered by session.

    Args:
        account_id: The account identifier
        session_id: Optional — filter to trades from a specific session

    Returns:
        JSON list of trade objects with execution details and realized P&L
    """
    with _pmb(ctx) as client:
        return json.dumps(client.get_trades(account_id=account_id, session_id=session_id))


# ── Broker account: day-gated trading -----------------------------------


@mcp.tool()
def pmb_get_status(account_id: str,
    ctx: Context = None,
) -> str:
    """Query the broker status of an account by its 10-digit id.

    Args:
        account_id: The 10-digit account number

    Returns:
        JSON with: market, status (ACTIVE/FROZEN/CLOSED), trading_day, current_date,
        cash, equity, realized_pnl, unrealized_pnl, total_return, positions,
        trades_today. When status is FROZEN you must call pmb_next_day before trading.
    """
    with _pmb(ctx) as client:
        return json.dumps(client.get_status(account_id))


@mcp.tool()
def pmb_get_history(account_id: str, limit: Optional[int] = None,
    ctx: Context = None,
) -> str:
    """Get an account's step-by-step trading history (one record per trading day).

    Args:
        account_id: The 10-digit account number
        limit: Optional — return only the most recent N days

    Returns:
        JSON list of day records: trading_day, date, opening_equity, closing_equity,
        realized_pnl, num_trades, fees, trades[], positions[].
    """
    with _pmb(ctx) as client:
        return json.dumps(client.get_history(account_id, limit=limit))


@mcp.tool()
def pmb_trade(
    account_id: str,
    symbol: str,
    side: Literal["BUY", "SELL"],
    qty: int,
    price: Optional[float] = None,
    note: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Execute an immediate paper trade against the account's broker book.

    Only allowed while the account is ACTIVE (rejected when FROZEN). Leave
    ``price`` unset to fill at the REAL UPQ market price for the account's
    current trading day (recommended — the response's ``price_source`` shows
    ``upq:close``). Use ``pmb_quote`` first if you want to see the price.

    Args:
        account_id: The 10-digit account number
        symbol: Ticker, e.g. "AAPL"
        side: "BUY" or "SELL"
        qty: Number of shares (positive integer)
        price: Optional override; omit to fill at the real market price
        note: Optional free-text note attached to the fill

    Returns:
        JSON with the executed fill (incl. price_source) and updated account status.
    """
    with _pmb(ctx) as client:
        return json.dumps(client.trade(account_id, symbol, side, qty, price, note=note))


@mcp.tool()
def pmb_quote(account_id: str, symbols: str,
    ctx: Context = None,
) -> str:
    """Get the real UPQ market price for symbols at the account's trading day.

    This is the exact price a no-price ``pmb_trade`` would fill at.

    Args:
        account_id: The 10-digit account number
        symbols: Comma-separated tickers, e.g. "AAPL,MSFT"

    Returns:
        JSON with as_of date, the price rule, prices per symbol, and any missing.
    """
    with _pmb(ctx) as client:
        return json.dumps(client.quote(account_id, symbols))


@mcp.tool()
def pmb_get_config(ctx: Context = None) -> str:
    """Get the broker settings that govern fills, fees, leverage, and defaults.

    Returns fees (per share / per option contract), slippage, buying-power
    leverage, initial cash, default market/frequency, and the fill price rule.
    """
    with _pmb(ctx) as client:
        return json.dumps(client.get_config())


@mcp.tool()
def pmb_end_day(account_id: str,
    ctx: Context = None,
) -> str:
    """Close the current trading day and FREEZE the account.

    Records the day into the account's trading history. While frozen, trades are
    rejected until pmb_next_day is called.

    Args:
        account_id: The 10-digit account number

    Returns:
        JSON with the closed day record and the updated (frozen) account status.
    """
    with _pmb(ctx) as client:
        return json.dumps(client.end_day(account_id))


@mcp.tool()
def pmb_next_day(account_id: str, date: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Unfreeze the account and advance to the next trading day.

    If the current day was not explicitly ended, it is auto-closed first so the
    history stays contiguous.

    Args:
        account_id: The 10-digit account number
        date: Optional explicit "YYYY-MM-DD"; otherwise advances to the next weekday.

    Returns:
        JSON with the updated (active) account status on the new trading day.
    """
    with _pmb(ctx) as client:
        return json.dumps(client.next_day(account_id, date=date))


@mcp.tool()
def pmb_create_session(
    account_id: str,
    frequency: Literal["1m", "1d"],
    start_ts: str,
    end_ts: str,
    stock_universe: Optional[list[str]] = None,
    option_universe: Optional[list[str]] = None,
    future_universe: Optional[list[str]] = None,
    ctx: Context = None,
) -> str:
    """Create a new backtesting / simulation session.

    Args:
        account_id: The account to trade in (from pmb_create_account)
        frequency: Time step size — "1m" (minute bars) or "1d" (daily bars)
        start_ts: Session start "YYYY-MM-DDTHH:MM:SS" (UTC) or "YYYY-MM-DD"
                  e.g. "2024-01-02T09:30:00" for minute, "2024-01-02" for daily.
                  A minute session from "YYYY-MM-DDT00:00:00" (20:00 ET the evening
                  before) starts with that day's overnight session where the store
                  has Blue Ocean bars; see market_calendar for the session hours
        end_ts: Session end datetime, same format as start_ts
        stock_universe: Stock symbols to include, e.g. ["AAPL", "NVDA", "SPY"]
        option_universe: Option contracts to include, e.g. ["O:SPY250117C00500000"]
                         (use upq_make_opra or a chain query to get symbols)
        future_universe: Futures to include: contracts ("ZNZ6") or front-month
                         roots ("ZN", "CL", "GC"); they trade around the clock
                         (CME 18:00-17:00 ET) and settle daily

    Returns:
        JSON with: session_id, account_id, clock (frequency, current_ts, end_ts, status)
        Save the session_id — you'll need it to step and place orders.
    """
    universe: dict = {}
    if stock_universe:
        universe["stocks"] = stock_universe
    if option_universe:
        universe["options"] = option_universe
    if future_universe:
        universe["futures"] = future_universe

    with _pmb(ctx) as client:
        return json.dumps(
            client.create_session(
                account_id=account_id,
                frequency=frequency,
                start_ts=start_ts,
                end_ts=end_ts,
                universe=universe,
            )
        )


@mcp.tool()
def pmb_step_session(
    session_id: str,
    n: int = 1,
    ctx: Context = None,
) -> str:
    """Advance the simulation clock by n time steps.

    Each step moves time forward by one period (1 minute or 1 day).
    The response contains market prices, order fills, account snapshots.

    Args:
        session_id: The session identifier from pmb_create_session
        n: Number of steps to advance (default 1)

    Returns:
        JSON with:
          is_running  — false when session has ended (stop looping)
          current_ts  — current simulation timestamp
          status      — "RUNNING", "FINISHED", or "STOPPED"
          clock       — full clock state
          events[]    — list of events this step:
            MARKET_TICK      — stocks[] and options[] with OHLCV bars
            ORDER_EVENT      — order status changes (FILLED, CANCELLED, etc.)
            TRADE_EVENT      — individual trade executions
            ACCOUNT_SNAPSHOT — cash, equity, positions snapshot
            RISK_EVENT       — margin calls or risk alerts
    """
    with _pmb(ctx) as client:
        result = client.step(session_id=session_id, n=n)
        return json.dumps(result._raw)


@mcp.tool()
def pmb_step_until(
    session_id: str,
    until_ts: Optional[str] = None,
    max_steps: int = 390,
    stop_on_fill: bool = True,
    price_triggers: Optional[List[dict]] = None,
    stop_on_segment: Optional[Literal["REGULAR", "PRE", "POST", "OVERNIGHT"]] = None,
    ctx: Context = None,
) -> str:
    """Advance the clock until something worth deciding on happens.

    Prefer this over many pmb_step_session calls in minute sessions: one call
    covers up to ``max_steps`` bars and stops at the first of
      - ``until_ts`` reached (ISO time),
      - an order fill (``stop_on_fill``, default true),
      - a price trigger, e.g. [{"symbol": "SPY", "op": ">=", "price": 600}],
      - entering a session segment (``stop_on_segment``, e.g. "REGULAR" to
        skip to the next open),
      - the session ending.

    Returns:
        JSON with steps, reason, clock (incl. segment and trading_date), the
        order/trade/risk events seen, last_tick (latest bars) and account.
    """
    with _pmb(ctx) as client:
        return json.dumps(client.step_until(
            session_id, until_ts=until_ts, max_steps=max_steps, stop_on_fill=stop_on_fill,
            price_triggers=price_triggers, stop_on_segment=stop_on_segment))


@mcp.tool()
def pmb_get_market(session_id: str,
    ctx: Context = None,
) -> str:
    """Get the current market state for a session (latest prices for all instruments).

    Args:
        session_id: The session identifier

    Returns:
        JSON with current market data for all instruments in the session universe
    """
    with _pmb(ctx) as client:
        return json.dumps(client.get_market(session_id))


@mcp.tool()
def pmb_session_state(session_id: str,
    ctx: Context = None,
) -> str:
    """Get the full consolidated state of a session in one call.

    Returns clock (current bar, index, total bars, status, segment OVERNIGHT /
    PRE / REGULAR / POST and the trading date), the account snapshot
    (cash, equity, buying power, margin), open positions, working orders, recent
    trades, and the current market quotes — everything an agent needs each step.

    Args:
        session_id: The session identifier

    Returns:
        JSON with clock, account, positions, open_orders, trades, and market.
    """
    with _pmb(ctx) as client:
        return json.dumps(client.get_session_state(session_id))


@mcp.tool()
def pmb_rewind(session_id: str, target_ts: str,
    ctx: Context = None,
) -> str:
    """Time-travel a session back to target_ts, undoing every order placed after it.

    The session is deterministically replayed to the target bar; any orders/fills
    that happened after target_ts are undone. Useful to explore alternate actions
    from an earlier point without recreating the session.

    Args:
        session_id: The session identifier
        target_ts: ISO timestamp of the bar to return to (e.g. "2024-03-22T14:00:00+00:00").
            The latest bar at or before this time becomes the new current bar.

    Returns:
        JSON with the rewound consolidated session state (same shape as pmb_session_state).
    """
    with _pmb(ctx) as client:
        return json.dumps(client.rewind(session_id, target_ts))


@mcp.tool()
def pmb_add_stocks(session_id: str, symbols: List[str],
    ctx: Context = None,
) -> str:
    """Add stock symbols to a running session (grow the watchlist / tradable universe).

    The new symbols are priced and tradable from the current bar onward.

    Args:
        session_id: The session identifier
        symbols: Stock tickers to add, e.g. ["MSFT", "NVDA"]

    Returns:
        JSON with {ok, loaded, skipped}.
    """
    with _pmb(ctx) as client:
        return json.dumps(client.add_stocks(session_id, symbols))


@mcp.tool()
def pmb_add_contracts(session_id: str, contracts: List[str],
    ctx: Context = None,
) -> str:
    """Load option contracts into a running session so they can be traded and marked.

    Use upq_option_chain to discover contract identifiers (e.g. O:AAPL240328C00170000),
    then add them here before placing option orders.

    Args:
        session_id: The session identifier
        contracts: OPRA option contract ids, e.g. ["O:AAPL240328C00170000"]

    Returns:
        JSON with {ok, loaded, skipped}.
    """
    with _pmb(ctx) as client:
        return json.dumps(client.add_contracts(session_id, contracts))


@mcp.tool()
def pmb_stop_session(session_id: str,
    ctx: Context = None,
) -> str:
    """Stop a running simulation session early.

    Args:
        session_id: The session identifier

    Returns:
        JSON confirmation of session termination
    """
    with _pmb(ctx) as client:
        return json.dumps(client.stop_session(session_id))


@mcp.tool()
def pmb_get_summary(session_id: str,
    ctx: Context = None,
) -> str:
    """Get backtesting performance summary for a session.

    Args:
        session_id: The session identifier (session should be finished or stopped)

    Returns:
        JSON with: final_equity, total_return, max_drawdown, fees_paid,
                   num_orders, num_trades, sharpe_ratio (and other metrics)
    """
    with _pmb(ctx) as client:
        return json.dumps(client.get_summary(session_id))


@mcp.tool()
def pmb_export_session(
    session_id: str,
    fmt: str = "json",
    ctx: Context = None,
) -> str:
    """Export full session data for external analysis.

    Args:
        session_id: The session identifier
        fmt: "json" (default) or "csv"

    Returns:
        Session trade history and performance data in the requested format
    """
    with _pmb(ctx) as client:
        result = client.export(session_id=session_id, fmt=fmt)
        if isinstance(result, str):
            return result
        return json.dumps(result)


@mcp.tool()
def pmb_buy_stock(
    session_id: str,
    account_id: str,
    symbol: str,
    qty: int,
    order_type: Literal["MARKET", "LIMIT", "STOP", "STOP_LIMIT"] = "MARKET",
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    time_in_force: Literal["DAY", "GTC", "GTD"] = "DAY",
    client_order_id: Optional[str] = None,
    trading_hours: Literal["REGULAR", "EXTENDED", "OVERNIGHT"] = "REGULAR",
    expire_ts: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Place a BUY order for a stock.

    Args:
        session_id: The active session identifier
        account_id: The account identifier
        symbol: Stock symbol, e.g. "AAPL"
        qty: Number of shares (integer)
        order_type: "MARKET" (default), "LIMIT", "STOP", or "STOP_LIMIT"
        limit_price: Required for LIMIT and STOP_LIMIT orders
        stop_price: Required for STOP and STOP_LIMIT orders
        time_in_force: "DAY" (default, expires at the end of the trading date it
            first becomes eligible on), "GTC" (good till cancel) or "GTD" (needs expire_ts)
        client_order_id: Optional idempotency key to prevent duplicate orders
        trading_hours: "REGULAR" (09:30-16:00 ET, default), "EXTENDED"
            (04:00-20:00 ET) or "OVERNIGHT" (24/5 incl. 20:00-04:00 ET).
            Outside REGULAR only LIMIT orders are accepted.
        expire_ts: ISO time a GTD order expires

    Returns:
        JSON order object with: order_id, status, instrument, side, qty, order_type
    """
    with _pmb(ctx) as client:
        return json.dumps(
            client.buy(
                session_id=session_id,
                account_id=account_id,
                symbol=symbol,
                qty=qty,
                order_type=order_type,
                limit_price=limit_price,
                stop_price=stop_price,
                time_in_force=time_in_force,
                client_order_id=client_order_id,
                trading_hours=trading_hours,
                expire_ts=expire_ts,
            )
        )


@mcp.tool()
def pmb_sell_stock(
    session_id: str,
    account_id: str,
    symbol: str,
    qty: int,
    order_type: Literal["MARKET", "LIMIT", "STOP", "STOP_LIMIT"] = "MARKET",
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    time_in_force: Literal["DAY", "GTC", "GTD"] = "DAY",
    client_order_id: Optional[str] = None,
    trading_hours: Literal["REGULAR", "EXTENDED", "OVERNIGHT"] = "REGULAR",
    expire_ts: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Place a SELL order for a stock.

    Args:
        session_id: The active session identifier
        account_id: The account identifier
        symbol: Stock symbol, e.g. "AAPL"
        qty: Number of shares to sell (integer)
        order_type: "MARKET" (default), "LIMIT", "STOP", or "STOP_LIMIT"
        limit_price: Required for LIMIT and STOP_LIMIT orders
        stop_price: Required for STOP and STOP_LIMIT orders
        time_in_force: "DAY", "GTC" or "GTD" (needs expire_ts)
        client_order_id: Optional idempotency key
        trading_hours: "REGULAR" (default), "EXTENDED" or "OVERNIGHT"; outside
            REGULAR only LIMIT orders are accepted
        expire_ts: ISO time a GTD order expires

    Returns:
        JSON order object with: order_id, status, instrument, side, qty, order_type
    """
    with _pmb(ctx) as client:
        return json.dumps(
            client.sell(
                session_id=session_id,
                account_id=account_id,
                symbol=symbol,
                qty=qty,
                order_type=order_type,
                limit_price=limit_price,
                stop_price=stop_price,
                time_in_force=time_in_force,
                client_order_id=client_order_id,
                trading_hours=trading_hours,
                expire_ts=expire_ts,
            )
        )


@mcp.tool()
def pmb_trade_future(
    session_id: str,
    account_id: str,
    symbol: str,
    side: Literal["BUY", "SELL"],
    qty: int,
    order_type: Literal["MARKET", "LIMIT", "STOP", "STOP_LIMIT"] = "MARKET",
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    time_in_force: Literal["DAY", "GTC"] = "DAY",
    client_order_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Place a futures order (BUY or SELL; selling with no position opens a short).

    Futures are margined, not paid for: opening contracts need their initial
    margin free (equity minus the initial margin already in use), fills cost
    only fees, and each position settles daily at the session's settlement
    price (VARIATION_MARGIN events move the gain or loss into cash). When
    equity falls below maintenance margin the account is in a margin call
    (no new positions) until equity is back at initial margin; an unmet call
    is liquidated at a later settlement. The session state lists each
    contract's multiplier, tick size and margin per contract.

    Args:
        session_id: The active session (futures must be in its future_universe)
        account_id: The account identifier
        symbol: Contract ("ZNZ6") or front-month root ("ZN")
        side: "BUY" or "SELL"
        qty: Number of contracts
        order_type: "MARKET" (default), "LIMIT", "STOP" or "STOP_LIMIT"
        limit_price / stop_price: Prices in the contract's quote units
        time_in_force: "DAY" (default) or "GTC"
        client_order_id: Optional idempotency key
    """
    with _pmb(ctx) as client:
        return json.dumps(client.trade_future(
            session_id=session_id, account_id=account_id, symbol=symbol, side=side, qty=qty,
            order_type=order_type, limit_price=limit_price, stop_price=stop_price,
            time_in_force=time_in_force, client_order_id=client_order_id,
        ))


@mcp.tool()
def pmb_buy_option(
    session_id: str,
    account_id: str,
    contract: str,
    qty: int,
    order_type: Literal["MARKET", "LIMIT"] = "MARKET",
    limit_price: Optional[float] = None,
    time_in_force: Literal["GTC", "DAY"] = "GTC",
    client_order_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Place a BUY order for an option contract.

    Args:
        session_id: The active session identifier
        account_id: The account identifier
        contract: OPRA contract string, e.g. "O:NVDA250117C00136000"
                  Use upq_make_opra() to build this string.
        qty: Number of contracts (integer; 1 contract = 100 shares)
        order_type: "MARKET" (default) or "LIMIT"
        limit_price: Per-share price (not per contract) for LIMIT orders
        time_in_force: "GTC" (default) or "DAY"
        client_order_id: Optional idempotency key

    Returns:
        JSON order object with order_id and initial status
    """
    with _pmb(ctx) as client:
        return json.dumps(
            client.buy_option(
                session_id=session_id,
                account_id=account_id,
                contract=contract,
                qty=qty,
                order_type=order_type,
                limit_price=limit_price,
                time_in_force=time_in_force,
                client_order_id=client_order_id,
            )
        )


@mcp.tool()
def pmb_sell_option(
    session_id: str,
    account_id: str,
    contract: str,
    qty: int,
    order_type: Literal["MARKET", "LIMIT"] = "MARKET",
    limit_price: Optional[float] = None,
    time_in_force: Literal["GTC", "DAY"] = "GTC",
    client_order_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Place a SELL order for an option contract.

    Args:
        session_id: The active session identifier
        account_id: The account identifier
        contract: OPRA contract string, e.g. "O:NVDA250117C00136000"
        qty: Number of contracts to sell (integer)
        order_type: "MARKET" (default) or "LIMIT"
        limit_price: Per-share price for LIMIT orders
        time_in_force: "GTC" (default) or "DAY"
        client_order_id: Optional idempotency key

    Returns:
        JSON order object with order_id and initial status
    """
    with _pmb(ctx) as client:
        return json.dumps(
            client.sell_option(
                session_id=session_id,
                account_id=account_id,
                contract=contract,
                qty=qty,
                order_type=order_type,
                limit_price=limit_price,
                time_in_force=time_in_force,
                client_order_id=client_order_id,
            )
        )


@mcp.tool()
def pmb_cancel_order(
    order_id: str,
    session_id: str,
    account_id: str,
    ctx: Context = None,
) -> str:
    """Cancel an open order.

    Args:
        order_id: The order identifier to cancel
        session_id: The session the order belongs to
        account_id: The account the order belongs to

    Returns:
        JSON confirmation of cancellation
    """
    with _pmb(ctx) as client:
        return json.dumps(
            client.cancel_order(
                order_id=order_id,
                session_id=session_id,
                account_id=account_id,
            )
        )


# ════════════════════════════════════════════════════════════════════════════
# DATA COVERAGE & CALENDAR — what the store holds, and when markets trade
# ════════════════════════════════════════════════════════════════════════════


def _data_admin(path: str, params: Optional[dict] = None) -> dict:
    """GET from the data-admin service (coverage map, raw-data index); no proxy."""
    import requests
    with requests.Session() as s:
        s.trust_env = False
        r = s.get(f"{DATA_ADMIN_URL}{path}", params=params, timeout=120)
        if r.status_code >= 400:
            raise ValueError(f"data-admin {path}: {r.status_code} {r.text[:300]}")
        return r.json()


def _spans(days: list[str]) -> list[list[str]]:
    """Sorted trading days -> runs of consecutive trading days ``[[first, last], ...]``."""
    from datetime import date as _date
    from qfinzero.market_calendar import next_trading_day
    out: list[list[str]] = []
    for d in sorted(days):
        if out and next_trading_day(_date.fromisoformat(out[-1][1])).isoformat() >= d:
            out[-1][1] = d
        else:
            out.append([d, d])
    return out


@mcp.tool()
def data_extent() -> str:
    """Which data the store holds: first and last date (and number of days) of each level.

    Levels: daily, minute, quotes, overnight_daily (Blue Ocean sessions) for US
    stocks; options_eod, options_minute, options_quotes; futures_daily,
    futures_minute, futures_quotes; crypto_daily, crypto_minute; fx_daily,
    fx_minute, fx_quotes. Ranges are per store: a symbol may cover less (use
    data_coverage for one symbol). Also lists frequently traded symbols.

    Returns:
        JSON with stores {level: {start, end, days} | null} and suggested symbols.
    """
    d = _data_admin("/coverage/extent")
    return json.dumps({"stores": d.get("stores"), "default_range": d.get("default"),
                       "suggested": [x.get("ticker") for x in d.get("suggested") or []],
                       "suggested_futures": d.get("suggested_futures"), "suggested_crypto": d.get("suggested_crypto"),
                       "suggested_fx": d.get("suggested_fx")})


@mcp.tool()
def data_coverage(tickers: list[str], start: str, end: str) -> str:
    """Which data levels each symbol has, as runs of consecutive trading days.

    Use it before a query or a session to pick dates that have data: e.g. the
    days SPY has option minutes, or whether NVDA has overnight bars.

    Args:
        tickers: Symbols in coverage form: stocks "SPY", futures "/CL",
                 crypto "X:BTC-USD", FX "C:EUR-USD" (up to 50)
        start: First date "YYYY-MM-DD"
        end: Last date "YYYY-MM-DD"

    Returns:
        JSON {ticker: {"kind": ..., "levels": {level: [[first, last], ...]}}}
        with levels as in data_extent (stock minute bars also by session:
        minute:overnight, minute:pre, minute:regular, minute:post).
    """
    m = _data_admin("/coverage/matrix", {"tickers": ",".join(tickers), "start": start, "end": end,
                                         "events": "false"})
    out: dict = {}
    for tk, days in (m.get("cells") or {}).items():
        levels: dict[str, list[str]] = {}
        for d, cell in days.items():
            for k, v in (cell or {}).items():
                if isinstance(v, dict):
                    for seg, n in v.items():
                        if n:
                            levels.setdefault(f"minute:{seg}", []).append(d)
                elif v:
                    levels.setdefault(k, []).append(d)
        out[tk] = {"kind": (m.get("kinds") or {}).get(tk), "levels": {k: _spans(v) for k, v in sorted(levels.items())}}
    return json.dumps(out)


@mcp.tool()
def data_day(ticker: str, date: str) -> str:
    """What the store has for one symbol on one day.

    Rows per level and session, the first and last quote, the option expiries
    that traded, corporate actions and the day's news/earnings events.

    Args:
        ticker: Coverage-form symbol, e.g. "SPY", "/CL", "X:BTC-USD"
        date: "YYYY-MM-DD"
    """
    return json.dumps(_data_admin("/coverage/cell", {"ticker": ticker, "date": date}))


@mcp.tool()
def upq_option_expiries(
    underlying: str,
    date: str,
    session_id: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """Expiries of an underlying's options that traded on a day, with their strike range.

    Use it to pick an expiry before upq_chain_snapshot / upq_option_chain.

    Args:
        underlying: e.g. "SPY"
        date: Trade date "YYYY-MM-DD"
        session_id: Optional PMB session to time-lock this query to.

    Returns:
        JSON list [{expiry, days_to_expiry, contracts, strike_min, strike_max, volume}],
        nearest expiry first.
    """
    from datetime import date as _date
    as_of = _lock(ctx, session_id)
    with UPQClient(UPQ_URL) as client:
        rows = client.option_chain(underlying=underlying, date=date, fields="expiry,strike,volume", as_of=as_of)
    by: dict[str, dict] = {}
    for r in rows:
        e = str(r.get("expiry"))
        g = by.setdefault(e, {"expiry": e, "contracts": 0, "strike_min": None, "strike_max": None, "volume": 0})
        k = r.get("strike")
        g["contracts"] += 1
        g["volume"] += int(r.get("volume") or 0)
        if k is not None:
            g["strike_min"] = k if g["strike_min"] is None else min(g["strike_min"], k)
            g["strike_max"] = k if g["strike_max"] is None else max(g["strike_max"], k)
    d0 = _date.fromisoformat(date)
    out = sorted(by.values(), key=lambda g: g["expiry"])
    for g in out:
        g["days_to_expiry"] = (_date.fromisoformat(g["expiry"]) - d0).days
    return json.dumps(out)


@mcp.tool()
def market_calendar(start: str, end: str) -> str:
    """US trading days in a range with each day's session hours (ET and UTC).

    A trading day's sessions, in order: overnight (Blue Ocean, 20:00 ET the
    evening before to 04:00), pre-market (04:00-09:30), regular (09:30-16:00,
    13:00 on early-close days) and after-hours (to 20:00, 17:00 on early-close
    days). The overnight session belongs to the trading day it precedes
    (Sunday night is Monday's). PMB orders use these: trading_hours REGULAR,
    EXTENDED (pre + regular + after-hours) or OVERNIGHT (all four).

    Args:
        start: First date "YYYY-MM-DD"
        end: Last date "YYYY-MM-DD" (at most 400 days after start)

    Returns:
        JSON {trading_days: [{date, early_close, sessions: {overnight|pre|regular|post:
        {start_et, end_et, start_utc, end_utc}}}], holidays: [...]}
    """
    from datetime import date as _date, datetime as _dt, timedelta as _td, timezone as _tz
    from zoneinfo import ZoneInfo
    from qfinzero import market_calendar as cal
    a, b = _date.fromisoformat(start), _date.fromisoformat(end)
    if b < a or (b - a).days > 400:
        raise ValueError("end must be on or after start and at most 400 days later")
    et = ZoneInfo("America/New_York")

    def at(d: _date, minutes: int) -> dict:
        t = _dt(d.year, d.month, d.day, tzinfo=et) + _td(minutes=minutes)
        return {"et": t.strftime("%Y-%m-%d %H:%M"), "utc": t.astimezone(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

    def span(d0: _date, m0: int, d1: _date, m1: int) -> dict:
        x, y = at(d0, m0), at(d1, m1)
        return {"start_et": x["et"], "end_et": y["et"], "start_utc": x["utc"], "end_utc": y["utc"]}

    days = []
    for d in cal.trading_days(a, b):
        close, post = cal.regular_close(d), cal.post_close(d)
        days.append({"date": d.isoformat(), "early_close": cal.is_early_close(d), "sessions": {
            "overnight": span(d - _td(days=1), 20 * 60, d, 4 * 60),
            "pre": span(d, 4 * 60, d, 9 * 60 + 30),
            "regular": span(d, 9 * 60 + 30, d, close),
            "post": span(d, close, d, post)}})
    hol = sorted(h.isoformat() for y in range(a.year, b.year + 1) for h in cal.holidays(y) if a <= h <= b)
    return json.dumps({"trading_days": days, "holidays": hol})


@mcp.tool()
def admin_data_catalog() -> str:
    """The raw-data index: every market-data dataset found in the raw libraries.

    One row per (vendor, dataset, schema): kind, asset class, resolution, file
    count, size, first and last date, index levels (L0 read whole, L1 indexed,
    L2 fast) and scope (in, or out for data QFinZero does not use such as MBO).
    From the last scan (Data setup -> Scan & index, or `qfz-data index`).
    Needs the admin scope.
    """
    rep = (_data_admin("/setup/index") or {}).get("report") or {}
    groups = [{k: g.get(k) for k in ("vendor", "dataset", "schema", "kind", "asset_class", "resolution", "files",
                                     "bytes", "first", "last", "levels", "scope")} for g in rep.get("groups") or []]
    return json.dumps({"last_scanned": rep.get("scanned"), "roots": rep.get("roots"), "files": rep.get("files"),
                       "groups": groups, "unknown": rep.get("unknown")})


# ════════════════════════════════════════════════════════════════════════════
# RESOURCES — read-only reference data agents can pull on demand
# ════════════════════════════════════════════════════════════════════════════


@mcp.resource("qfinzero://ports")
def resource_ports() -> str:
    """Canonical QFinZero service port map (193xx block)."""
    return json.dumps(
        {
            "dashboard": DASHBOARD_PORT,
            "esp": ESP_PORT,
            "upq": UPQ_PORT,
            "pmb": PMB_PORT,
            "playground": PLAYGROUND_PORT,
            "service_urls": {"upq": UPQ_URL, "esp": ESP_URL, "pmb": PMB_URL},
        },
        indent=2,
    )


@mcp.resource("qfinzero://data/freshness")
def resource_data_freshness() -> str:
    """Live UPQ market-data freshness (latest dates, record counts per store)."""
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.freshness(), indent=2)


@mcp.resource("qfinzero://health")
def resource_health() -> str:
    """Combined health of UPQ, ESP, and PMB services."""
    out = {}
    try:
        with UPQClient(UPQ_URL) as c:
            out["upq"] = c.health()
    except Exception as e:  # noqa: BLE001
        out["upq"] = {"status": "down", "error": str(e)}
    try:
        with ESPClient(ESP_URL) as c:
            out["esp"] = c.health()
    except Exception as e:  # noqa: BLE001
        out["esp"] = {"status": "down", "error": str(e)}
    try:
        with PMBClient(PMB_URL) as c:
            out["pmb"] = c.health()
    except Exception as e:  # noqa: BLE001
        out["pmb"] = {"status": "down", "error": str(e)}
    return json.dumps(out, indent=2)


# ════════════════════════════════════════════════════════════════════════════
# PROMPTS — reusable agent workflow templates
# ════════════════════════════════════════════════════════════════════════════


@mcp.prompt()
def trading_session(
    universe: str = "AAPL,NVDA",
    frequency: Literal["1d", "1m"] = "1d",
    start_date: str = "2025-01-06",
    end_date: str = "2025-01-31",
) -> str:
    """Scaffold a complete QFinZero paper-trading session loop."""
    return (
        f"Run a paper-trading session over {universe} at {frequency} frequency "
        f"from {start_date} to {end_date}.\n\n"
        "Steps:\n"
        "1. pmb_create_account(initial_cash=100000, start_date=...).\n"
        "2. pmb_create_session(account_id, frequency, start_ts, end_ts, universe).\n"
        "3. Loop while the session is running:\n"
        "   a. pmb_step_session to advance time and read MARKET_TICK / events.\n"
        "   b. esp_query_events / upq_stock_daily for context at the current time.\n"
        "   c. pmb_buy_stock / pmb_sell_stock to act.\n"
        "4. pmb_get_summary for performance (return, drawdown, Sharpe).\n\n"
        "Use adjust=none for raw prints; adjust=split or adjust=total when you need "
        "split/dividend-adjusted history."
    )


# ════════════════════════════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════════════════════════════


def main() -> None:
    """Run the MCP server.

    Transport via QFINZERO_MCP_TRANSPORT:
      * ``stdio``           (default) — local Claude Desktop / Claude Code.
      * ``streamable-http`` — modern HTTP transport for remote/multi-client use
                              (listens on QFINZERO_MCP_HOST:QFINZERO_MCP_PORT).
      * ``sse``             — legacy HTTP+SSE transport.
    """
    transport = MCP_TRANSPORT.strip().lower()
    if transport in ("http", "streamable-http", "streamable_http"):
        mcp.run(transport="streamable-http")
    elif transport == "sse":
        mcp.run(transport="sse")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
