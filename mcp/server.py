"""
QFinZero MCP Server

Exposes all QFinZero tools (UPQ, NPP, PMB) as MCP tools for integration
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
from clients.npp.client import NPPClient
from clients.pmb.client import PMBClient

# ── Service URLs (can be overridden via env vars) ────────────────────────────

UPQ_URL = os.environ.get("QFINZERO_UPQ_URL", "http://127.0.0.1:19350")
NPP_URL = os.environ.get("QFINZERO_NPP_URL", "http://127.0.0.1:19330")
PMB_URL = os.environ.get("QFINZERO_PMB_URL", "http://127.0.0.1:19320")

mcp = FastMCP(
    "QFinZero",
    instructions=(
        "QFinZero is a unified trading environment for LLM agents. "
        "It provides three services: UPQ (market data), NPP (news & events), "
        "and PMB (paper trading broker). "
        "Typical workflow: (1) create account via pmb_create_account, "
        "(2) create session via pmb_create_session, "
        "(3) loop pmb_step_session to advance time, "
        "(4) use UPQ/NPP tools to gather context, "
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
) -> str:
    """Query daily OHLCV bars for one or more stocks.

    Args:
        tickers: Stock symbols, e.g. ["AAPL", "NVDA", "SPY"]
        start: Start date "YYYY-MM-DD"
        end: End date "YYYY-MM-DD"
        fields: Comma-separated fields to return, e.g. "date,close,volume"
                Available: ticker, date, open, high, low, close, volume, transactions

    Returns:
        JSON list of daily bar objects, one per ticker per day.
    """
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.stock_daily(tickers=tickers, start=start, end=end, fields=fields))


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
        start: Start datetime "YYYY-MM-DDTHH:MM:SS", e.g. "2024-01-15T09:30:00"
        end: End datetime "YYYY-MM-DDTHH:MM:SS", e.g. "2024-01-15T16:00:00"
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

    Returns:
        JSON list of option contract objects with pricing and Greeks.
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
            )
        )


@mcp.tool()
def upq_option_contract(
    contract: str,
    start: str,
    end: str,
    resolution: Literal["day", "minute"] = "day",
    fields: Optional[str] = None,
) -> str:
    """Query price history for a specific option contract.

    Args:
        contract: OPRA contract string, e.g. "O:NVDA250117C00136000"
                  Use upq_make_opra() to build the contract string.
        start: Start date/datetime string
        end: End date/datetime string
        resolution: "day" (default) or "minute"
        fields: Comma-separated fields to return

    Returns:
        JSON list of price bars for the contract.
        Day resolution also includes underlying, expiry, strike, type.
    """
    with UPQClient(UPQ_URL) as client:
        return json.dumps(
            client.option_contract(
                contract=contract, start=start, end=end, resolution=resolution, fields=fields
            )
        )


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
    return UPQClient.make_opra(underlying=underlying, expiry=expiry, right=right, strike=strike)


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
# NPP TOOLS — News & Events
# ════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def npp_health() -> str:
    """Check health of the NPP (News Pushing Pipeline) service and data freshness."""
    with NPPClient(NPP_URL) as client:
        return json.dumps(client.health())


@mcp.tool()
def npp_query_events(
    mode: str,
    start_utc: Optional[str] = None,
    end_utc: Optional[str] = None,
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
        mode: Query mode:
              "upcoming"      — events after now (set horizon_minutes)
              "just_happened" — events that recently occurred (set horizon_minutes)
              "window"        — events in a specific range (set start_utc + end_utc)
        start_utc: Window start ISO datetime (required for "window" mode)
        end_utc: Window end ISO datetime (required for "window" mode)
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
    with NPPClient(NPP_URL) as client:
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
def npp_get_event(event_id: str) -> str:
    """Fetch a single event by its ID, including full payload.

    Args:
        event_id: The unique event identifier (from npp_query_events results)

    Returns:
        JSON event object with full payload (earnings data, economic release values, etc.)
    """
    with NPPClient(NPP_URL) as client:
        return json.dumps(client.get_event(event_id))


@mcp.tool()
def npp_stream_events(
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
    with NPPClient(NPP_URL) as client:
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
def npp_econ_calendar(
    start_date: str,
    end_date: str,
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
    with NPPClient(NPP_URL) as client:
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
def npp_earnings_calendar(
    start_date: str,
    end_date: str,
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
    with NPPClient(NPP_URL) as client:
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
def npp_next_triggers(
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
    with NPPClient(NPP_URL) as client:
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
def npp_news_body(news_id: str) -> str:
    """Fetch the full body of a news article.

    Args:
        news_id: The news article ID (found in event payload from npp_query_events)

    Returns:
        JSON with: news_id, title, description, article_url, published_utc,
                   tickers, author, keywords, image_url, publisher, insights
    """
    with NPPClient(NPP_URL) as client:
        return json.dumps(client.news_body(news_id))


@mcp.tool()
def npp_search_news(
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
    with NPPClient(NPP_URL) as client:
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
def npp_timeline(
    tickers: Optional[list[str]] = None,
    start_utc: str = None,
    end_utc: str = None,
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
    with NPPClient(NPP_URL) as client:
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
    account_type: Literal["MARGIN", "CASH"] = "MARGIN",
) -> str:
    """Create a new paper trading account.

    Args:
        initial_cash: Starting cash balance, e.g. 100000.0
        start_date: Account start date "YYYY-MM-DD" (required — use the earliest date you will trade)
        account_type: "MARGIN" (default) or "CASH"

    Returns:
        JSON with: account_id, created_at, account_state
        Save the account_id — you'll need it for all subsequent calls.
    """
    with PMBClient(PMB_URL) as client:
        return json.dumps(
            client.create_account(
                initial_cash=initial_cash,
                account_type=account_type,
                start_date=start_date,
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
# Entry point
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    mcp.run()
