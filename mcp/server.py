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
from typing import Literal, Optional

# Add project root to path so we can import qfinzero clients without modifying the package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP

from clients.upq.client import UPQClient
from clients.esp.client import ESPClient
from clients.pmb.client import PMBClient
from qfinzero.config import (
    PMB_URL as DEFAULT_PMB_URL,
    ESP_URL as DEFAULT_ESP_URL,
    UPQ_URL as DEFAULT_UPQ_URL,
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

# ── MCP transport (modern: stdio default; streamable-http for remote/HTTP) ────
MCP_TRANSPORT = os.environ.get("QFINZERO_MCP_TRANSPORT", "stdio")
MCP_HOST = os.environ.get("QFINZERO_MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.environ.get("QFINZERO_MCP_PORT", "19360"))

mcp = FastMCP(
    "QFinZero",
    host=MCP_HOST,
    port=MCP_PORT,
    instructions=(
        "QFinZero is a unified trading environment for LLM agents. "
        "It provides three services: UPQ (market data), ESP (news & events), "
        "and PMB (paper trading broker). "
        "Typical workflow: (1) create account via pmb_create_account, "
        "(2) create session via pmb_create_session, "
        "(3) loop pmb_step_session to advance time, "
        "(4) use UPQ/ESP tools to gather context, "
        "(5) place orders via pmb_buy_stock / pmb_sell_stock, "
        "(6) call pmb_get_summary when session ends."
    ),
)


# ════════════════════════════════════════════════════════════════════════════
# UPQ TOOLS — Market Data
# ════════════════════════════════════════════════════════════════════════════


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

    Returns:
        JSON list of daily bar objects with indicator columns appended when requested.
    """
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.stock_daily(
            tickers=tickers, start=start, end=end,
            fields=fields, indicators=indicators,
        ))


@mcp.tool()
def upq_stock_minute(
    tickers: list[str],
    start: str,
    end: str,
    fields: Optional[str] = None,
    limit: int = 10000,
) -> str:
    """Query minute-level OHLCV bars for one or more stocks.

    Args:
        tickers: Stock symbols, e.g. ["AAPL", "NVDA"]
        start: Start datetime in UTC "YYYY-MM-DDTHH:MM:SS", e.g. "2024-01-15T14:30:00" (09:30 ET)
        end: End datetime in UTC "YYYY-MM-DDTHH:MM:SS", e.g. "2024-01-15T21:00:00" (16:00 ET)
        fields: Comma-separated fields, e.g. "ticker,window_start,close,volume"
                Available: ticker, window_start, open, high, low, close, volume, transactions
        limit: Max rows to return (default 10000, max 100000)

    Returns:
        JSON list of minute bar objects. window_start is nanoseconds since epoch.
        Use upq_ns_to_iso to convert timestamps.
    """
    with UPQClient(UPQ_URL) as client:
        return json.dumps(
            client.stock_minute(tickers=tickers, start=start, end=end, fields=fields, limit=limit)
        )


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

    Returns:
        JSON list of option contract objects. When include_greeks=True,
        each row includes iv, delta, gamma, theta, vega, rho, greek_status,
        and greek_meta fields. Check greek_status for computation outcome.

    Notes:
        If `expiry_min` equals `expiry_max` (exact expiry) and no exact rows exist,
        UPQ automatically falls back to nearest available expiry (±7 days first,
        then same calendar month) within the same underlying/type/strike filter context.
    """
    with UPQClient(UPQ_URL) as client:
        return json.dumps(
            client.option_chain(
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

    Returns:
        JSON list of price bars for the contract.
        Day resolution also includes underlying, expiry, strike, type.
        When include_greeks=True, each row includes iv, delta, gamma, theta,
        vega, rho, greek_status, and greek_meta fields.
    """
    with UPQClient(UPQ_URL) as client:
        return json.dumps(
            client.option_contract(
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
) -> str:
    """Query dividend history for stocks/ETFs.

    Args:
        tickers: Stock/ETF symbols, e.g. ["JEPQ", "AAPL"]
        start: Start date "YYYY-MM-DD"
        end: End date "YYYY-MM-DD"

    Returns:
        JSON list of dividend objects with ticker, ex_dividend_date, amount.
    """
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.dividends(tickers=tickers, start=start, end=end))


@mcp.tool()
def upq_rates(
    start: str,
    end: str,
    tenors: Optional[str] = None,
) -> str:
    """Query US Treasury yield rates.

    Args:
        start: Start date "YYYY-MM-DD"
        end: End date "YYYY-MM-DD"
        tenors: Comma-separated tenor codes, e.g. "1M,3M,1Y,2Y,5Y,10Y,30Y"
                Omit for all tenors.

    Returns:
        JSON list of daily rate objects with one field per tenor.
    """
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.rates(start=start, end=end, tenors=tenors))


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

    Returns:
        JSON with: server_time_utc, events[], next_cursor
        Each event has: event_id, event_type, title, time_utc, importance, tickers, snippet
    """
    # Convert start_date/end_date to start_utc/end_utc if provided
    if start_date and not start_utc:
        start_utc = f"{start_date}T00:00:00+00:00"
    if end_date and not end_utc:
        end_utc = f"{end_date}T23:59:59+00:00"

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
def esp_get_event(event_id: str) -> str:
    """Fetch a single event by its ID, including full payload.

    Args:
        event_id: The unique event identifier (from esp_query_events results)

    Returns:
        JSON event object with full payload (earnings data, economic release values, etc.)
    """
    with ESPClient(ESP_URL) as client:
        return json.dumps(client.get_event(event_id))


@mcp.tool()
def esp_stream_events(
    cursor: Optional[str] = None,
    event_types: Optional[list[str]] = None,
    tickers: Optional[list[str]] = None,
    limit: int = 50,
    now_utc: Optional[str] = None,
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

    Returns:
        JSON with: server_time_utc, events[], next_cursor
    """
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
) -> str:
    """Query the US economic events calendar (GDP, CPI, FOMC, jobs data, PMI, etc.).

    Args:
        start_date: Start date "YYYY-MM-DD"
        end_date: End date "YYYY-MM-DD"
        min_importance: "low", "medium", or "high"
        limit: Max events per page (default 100)
        cursor: Pagination cursor
        now_utc: Override current time for backtesting replay (ISO datetime)

    Returns:
        JSON with: server_time_utc, events[], next_cursor
    """
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

    Returns:
        JSON with: server_time_utc, events[], next_cursor
    """
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

    Returns:
        JSON with: server_time_utc, triggers[]
        Each trigger has: trigger_time_utc, event_id, event, reason_codes
    """
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
def esp_news_body(news_id: str) -> str:
    """Fetch the full body of a news article.

    Args:
        news_id: The news article ID (found in event payload from esp_query_events)

    Returns:
        JSON with: news_id, title, description, article_url, published_utc,
                   tickers, author, keywords, image_url, publisher, insights
    """
    with ESPClient(ESP_URL) as client:
        return json.dumps(client.news_body(news_id))


@mcp.tool()
def esp_search_news(
    tickers: Optional[list[str]] = None,
    start_utc: Optional[str] = None,
    end_utc: Optional[str] = None,
    keyword: Optional[str] = None,
    publisher: Optional[str] = None,
    limit: int = 20,
    cursor: Optional[str] = None,
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

    Returns:
        JSON with: server_time_utc, events[], next_cursor
    """
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
            )
        )


@mcp.tool()
def esp_timeline(
    tickers: Optional[list[str]] = None,
    start_utc: Optional[str] = None,
    end_utc: Optional[str] = None,
    bucket_minutes: int = 60,
    now_utc: Optional[str] = None,
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

    Returns:
        JSON with: server_time_utc, buckets[]
        Each bucket has: bucket_start_utc, bucket_end_utc, count, events[]
    """
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
# PMB TOOLS — Paper Money Broker (Trading Simulation)
# ════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def pmb_health() -> str:
    """Check health of the PMB (Paper Money Broker) trading simulation service."""
    with PMBClient(PMB_URL) as client:
        return json.dumps(client.health())


@mcp.tool()
def pmb_create_account(
    initial_cash: float,
    start_date: str,
    market: Literal["us", "cn", "hk"] = "us",
    account_type: Literal["MARGIN", "CASH"] = "MARGIN",
) -> str:
    """Allocate a new paper trading (broker) account.

    Args:
        initial_cash: Starting cash balance, e.g. 100000.0
        start_date: Account open date "YYYY-MM-DD" (required — the first trading day)
        market: Market to trade — "us" (default), "cn", or "hk". Determines the
                account-number prefix, base currency, and exchange timezone.
        account_type: "MARGIN" (default) or "CASH"

    Returns:
        JSON with: account_id (a unique 10-digit number), market, created_at, account.
        Save the account_id — you'll need it for all subsequent calls.
    """
    with PMBClient(PMB_URL) as client:
        return json.dumps(
            client.create_account(
                initial_cash=initial_cash,
                account_type=account_type,
                market=market,
                open_date=start_date,
            )
        )


@mcp.tool()
def pmb_get_account(account_id: str) -> str:
    """Get the current state of a paper trading account.

    Args:
        account_id: The account identifier from pmb_create_account

    Returns:
        JSON with: cash_available, cash_locked, loan, equity, buying_power,
                   margin_status, positions summary
    """
    with PMBClient(PMB_URL) as client:
        return json.dumps(client.get_account(account_id))


@mcp.tool()
def pmb_get_positions(account_id: str) -> str:
    """List all current open positions in a paper trading account.

    Args:
        account_id: The account identifier

    Returns:
        JSON list of position objects with:
        symbol, qty, avg_cost, market_value, unrealized_pnl, side
    """
    with PMBClient(PMB_URL) as client:
        return json.dumps(client.get_positions(account_id))


@mcp.tool()
def pmb_get_orders(
    account_id: str,
    session_id: Optional[str] = None,
) -> str:
    """Query orders for an account, optionally filtered by session.

    Args:
        account_id: The account identifier
        session_id: Optional — filter to orders from a specific session

    Returns:
        JSON list of order objects with: order_id, symbol, side, order_type,
        qty, filled_qty, avg_fill_price, status, created_ts
    """
    with PMBClient(PMB_URL) as client:
        return json.dumps(client.get_orders(account_id=account_id, session_id=session_id))


@mcp.tool()
def pmb_get_trades(
    account_id: str,
    session_id: Optional[str] = None,
) -> str:
    """Query executed trades for an account, optionally filtered by session.

    Args:
        account_id: The account identifier
        session_id: Optional — filter to trades from a specific session

    Returns:
        JSON list of trade objects with execution details and realized P&L
    """
    with PMBClient(PMB_URL) as client:
        return json.dumps(client.get_trades(account_id=account_id, session_id=session_id))


# ── Broker account: day-gated trading -----------------------------------


@mcp.tool()
def pmb_get_status(account_id: str) -> str:
    """Query the broker status of an account by its 10-digit id.

    Args:
        account_id: The 10-digit account number

    Returns:
        JSON with: market, status (ACTIVE/FROZEN/CLOSED), trading_day, current_date,
        cash, equity, realized_pnl, unrealized_pnl, total_return, positions,
        trades_today. When status is FROZEN you must call pmb_next_day before trading.
    """
    with PMBClient(PMB_URL) as client:
        return json.dumps(client.get_status(account_id))


@mcp.tool()
def pmb_get_history(account_id: str, limit: Optional[int] = None) -> str:
    """Get an account's step-by-step trading history (one record per trading day).

    Args:
        account_id: The 10-digit account number
        limit: Optional — return only the most recent N days

    Returns:
        JSON list of day records: trading_day, date, opening_equity, closing_equity,
        realized_pnl, num_trades, fees, trades[], positions[].
    """
    with PMBClient(PMB_URL) as client:
        return json.dumps(client.get_history(account_id, limit=limit))


@mcp.tool()
def pmb_trade(
    account_id: str,
    symbol: str,
    side: Literal["BUY", "SELL"],
    qty: int,
    price: float,
    note: Optional[str] = None,
) -> str:
    """Execute an immediate paper trade against the account's broker book.

    Only allowed while the account is ACTIVE (rejected when FROZEN). The trade
    fills instantly at the supplied price.

    Args:
        account_id: The 10-digit account number
        symbol: Ticker, e.g. "AAPL"
        side: "BUY" or "SELL"
        qty: Number of shares (positive integer)
        price: Execution price per share
        note: Optional free-text note attached to the fill

    Returns:
        JSON with the executed fill and the updated account status.
    """
    with PMBClient(PMB_URL) as client:
        return json.dumps(client.trade(account_id, symbol, side, qty, price, note=note))


@mcp.tool()
def pmb_end_day(account_id: str) -> str:
    """Close the current trading day and FREEZE the account.

    Records the day into the account's trading history. While frozen, trades are
    rejected until pmb_next_day is called.

    Args:
        account_id: The 10-digit account number

    Returns:
        JSON with the closed day record and the updated (frozen) account status.
    """
    with PMBClient(PMB_URL) as client:
        return json.dumps(client.end_day(account_id))


@mcp.tool()
def pmb_next_day(account_id: str, date: Optional[str] = None) -> str:
    """Unfreeze the account and advance to the next trading day.

    If the current day was not explicitly ended, it is auto-closed first so the
    history stays contiguous.

    Args:
        account_id: The 10-digit account number
        date: Optional explicit "YYYY-MM-DD"; otherwise advances to the next weekday.

    Returns:
        JSON with the updated (active) account status on the new trading day.
    """
    with PMBClient(PMB_URL) as client:
        return json.dumps(client.next_day(account_id, date=date))


@mcp.tool()
def pmb_create_session(
    account_id: str,
    frequency: Literal["1m", "1d"],
    start_ts: str,
    end_ts: str,
    stock_universe: Optional[list[str]] = None,
    option_universe: Optional[list[str]] = None,
) -> str:
    """Create a new backtesting / simulation session.

    Args:
        account_id: The account to trade in (from pmb_create_account)
        frequency: Time step size — "1m" (minute bars) or "1d" (daily bars)
        start_ts: Session start "YYYY-MM-DDTHH:MM:SS" or "YYYY-MM-DD"
                  e.g. "2024-01-02T09:30:00" for minute, "2024-01-02" for daily
        end_ts: Session end datetime, same format as start_ts
        stock_universe: Stock symbols to include, e.g. ["AAPL", "NVDA", "SPY"]
        option_universe: Underlying symbols to include options for, e.g. ["SPY"]

    Returns:
        JSON with: session_id, account_id, clock (frequency, current_ts, end_ts, status)
        Save the session_id — you'll need it to step and place orders.
    """
    universe: dict = {}
    if stock_universe:
        universe["stocks"] = stock_universe
    if option_universe:
        universe["options"] = option_universe

    with PMBClient(PMB_URL) as client:
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
    with PMBClient(PMB_URL) as client:
        result = client.step(session_id=session_id, n=n)
        return json.dumps(result._raw)


@mcp.tool()
def pmb_get_market(session_id: str) -> str:
    """Get the current market state for a session (latest prices for all instruments).

    Args:
        session_id: The session identifier

    Returns:
        JSON with current market data for all instruments in the session universe
    """
    with PMBClient(PMB_URL) as client:
        return json.dumps(client.get_market(session_id))


@mcp.tool()
def pmb_stop_session(session_id: str) -> str:
    """Stop a running simulation session early.

    Args:
        session_id: The session identifier

    Returns:
        JSON confirmation of session termination
    """
    with PMBClient(PMB_URL) as client:
        return json.dumps(client.stop_session(session_id))


@mcp.tool()
def pmb_get_summary(session_id: str) -> str:
    """Get backtesting performance summary for a session.

    Args:
        session_id: The session identifier (session should be finished or stopped)

    Returns:
        JSON with: final_equity, total_return, max_drawdown, fees_paid,
                   num_orders, num_trades, sharpe_ratio (and other metrics)
    """
    with PMBClient(PMB_URL) as client:
        return json.dumps(client.get_summary(session_id))


@mcp.tool()
def pmb_export_session(
    session_id: str,
    fmt: str = "json",
) -> str:
    """Export full session data for external analysis.

    Args:
        session_id: The session identifier
        fmt: "json" (default) or "csv"

    Returns:
        Session trade history and performance data in the requested format
    """
    with PMBClient(PMB_URL) as client:
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
    time_in_force: Literal["DAY", "GTC"] = "DAY",
    client_order_id: Optional[str] = None,
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
        time_in_force: "DAY" (default, expires end of day) or "GTC" (Good-Till-Cancel)
        client_order_id: Optional idempotency key to prevent duplicate orders

    Returns:
        JSON order object with: order_id, status, instrument, side, qty, order_type
    """
    with PMBClient(PMB_URL) as client:
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
    time_in_force: Literal["DAY", "GTC"] = "DAY",
    client_order_id: Optional[str] = None,
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
        time_in_force: "DAY" or "GTC"
        client_order_id: Optional idempotency key

    Returns:
        JSON order object with: order_id, status, instrument, side, qty, order_type
    """
    with PMBClient(PMB_URL) as client:
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
            )
        )


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
    with PMBClient(PMB_URL) as client:
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
    with PMBClient(PMB_URL) as client:
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
) -> str:
    """Cancel an open order.

    Args:
        order_id: The order identifier to cancel
        session_id: The session the order belongs to
        account_id: The account the order belongs to

    Returns:
        JSON confirmation of cancellation
    """
    with PMBClient(PMB_URL) as client:
        return json.dumps(
            client.cancel_order(
                order_id=order_id,
                session_id=session_id,
                account_id=account_id,
            )
        )


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
