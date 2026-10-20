"""UPQ on-disk target schemas — the single source of truth for the converter.

These mirror exactly what the UPQ Rust service reads, and they are the standard
fields of the raw-data index (``docs/plans/2026-10-20-raw-index-design.md``):
the converter casts every source into these column names and DuckDB types, and
in-place readers project raw files onto them.

Time conventions:
  * ``window_start`` — BIGINT nanoseconds since the Unix epoch, UTC (minute bars).
  * ``trade_date``   — DATE, also the Hive partition key for the OHLCV stores.
"""

from __future__ import annotations

# column name -> DuckDB type. Order is the written column order.
STOCK_DAILY = {
    "ticker": "VARCHAR",
    "trade_date": "DATE",
    "open": "DOUBLE",
    "high": "DOUBLE",
    "low": "DOUBLE",
    "close": "DOUBLE",
    "volume": "BIGINT",
    "transactions": "BIGINT",
}

STOCK_MINUTE = {
    "ticker": "VARCHAR",
    "window_start": "BIGINT",
    "open": "DOUBLE",
    "high": "DOUBLE",
    "low": "DOUBLE",
    "close": "DOUBLE",
    "volume": "BIGINT",
    "transactions": "BIGINT",
    "trade_date": "DATE",
}

OPTION_DAY = {
    "ticker": "VARCHAR",
    "contract": "VARCHAR",
    "underlying": "VARCHAR",
    "expiry": "DATE",
    "strike": "DOUBLE",
    "right": "VARCHAR",
    "window_start": "BIGINT",
    "open": "DOUBLE",
    "high": "DOUBLE",
    "low": "DOUBLE",
    "close": "DOUBLE",
    "volume": "BIGINT",
    "transactions": "BIGINT",
    "trade_date": "DATE",
}

OPTION_MINUTE = dict(OPTION_DAY)  # identical shape; minute window_start resolution

# Top of book at the end of each minute ``[window_start, window_start + 60s)``.
# Minutes without an update are not stored; readers carry the last quote forward.
STOCK_QUOTE_MINUTE = {
    "ticker": "VARCHAR",
    "window_start": "BIGINT",
    "bid_price": "DOUBLE",
    "ask_price": "DOUBLE",
    "bid_size": "BIGINT",
    "ask_size": "BIGINT",
    "trade_date": "DATE",
}

OPTION_QUOTE_MINUTE = {
    "ticker": "VARCHAR",
    "contract": "VARCHAR",
    "underlying": "VARCHAR",
    "expiry": "DATE",
    "strike": "DOUBLE",
    "right": "VARCHAR",
    "window_start": "BIGINT",
    "bid_price": "DOUBLE",
    "ask_price": "DOUBLE",
    "bid_size": "BIGINT",
    "ask_size": "BIGINT",
    "trade_date": "DATE",
}

# Futures. ``ticker`` is the contract (``ZNZ6``) or, for front-month continuous
# data, the root (``ZN``); ``root`` is always the product. ``trade_date`` is the
# CME session (18:00 ET the evening before to 17:00 ET).
FUTURE_MINUTE = {
    "ticker": "VARCHAR",
    "root": "VARCHAR",
    "instrument_id": "BIGINT",     # the contract a continuous series pointed to (rolls change it)
    "window_start": "BIGINT",
    "open": "DOUBLE",
    "high": "DOUBLE",
    "low": "DOUBLE",
    "close": "DOUBLE",
    "volume": "BIGINT",
    "transactions": "BIGINT",
    "trade_date": "DATE",
}

# ``settle`` is the price daily variation margin marks to: the exchange
# settlement (``settle_source = 'exchange'``, from Databento statistics) or the
# last trade of the session (``'last'``).
FUTURE_DAILY = {
    "ticker": "VARCHAR",
    "root": "VARCHAR",
    "instrument_id": "BIGINT",
    "trade_date": "DATE",
    "open": "DOUBLE",
    "high": "DOUBLE",
    "low": "DOUBLE",
    "close": "DOUBLE",
    "settle": "DOUBLE",
    "settle_source": "VARCHAR",
    "volume": "BIGINT",
    "transactions": "BIGINT",
}

FUTURE_QUOTE_MINUTE = {
    "ticker": "VARCHAR",
    "root": "VARCHAR",
    "window_start": "BIGINT",
    "bid_price": "DOUBLE",
    "ask_price": "DOUBLE",
    "bid_size": "BIGINT",
    "ask_size": "BIGINT",
    "trade_date": "DATE",
}

# Crypto and FX pairs (massive ``X:BTC-USD`` / ``C:EUR-USD``) are stored as
# ``BTC-USD`` / ``EUR-USD`` with the two legs split out. Both trade around the
# clock: ``trade_date`` is the UTC day of ``window_start``. Volume is
# fractional (coins, or the number of FX quotes for massive's FX bars).
PAIR_DAILY = {
    "ticker": "VARCHAR",
    "base": "VARCHAR",
    "quote": "VARCHAR",
    "trade_date": "DATE",
    "open": "DOUBLE",
    "high": "DOUBLE",
    "low": "DOUBLE",
    "close": "DOUBLE",
    "volume": "DOUBLE",
    "transactions": "BIGINT",
}

PAIR_MINUTE = {
    "ticker": "VARCHAR",
    "base": "VARCHAR",
    "quote": "VARCHAR",
    "window_start": "BIGINT",
    "open": "DOUBLE",
    "high": "DOUBLE",
    "low": "DOUBLE",
    "close": "DOUBLE",
    "volume": "DOUBLE",
    "transactions": "BIGINT",
    "trade_date": "DATE",
}

CRYPTO_DAILY = dict(PAIR_DAILY)
CRYPTO_MINUTE = dict(PAIR_MINUTE)
FX_DAILY = dict(PAIR_DAILY)
FX_MINUTE = dict(PAIR_MINUTE)

# Last FX quote of each minute (massive FX quotes carry no sizes).
FX_QUOTE_MINUTE = {
    "ticker": "VARCHAR",
    "base": "VARCHAR",
    "quote": "VARCHAR",
    "window_start": "BIGINT",
    "bid_price": "DOUBLE",
    "ask_price": "DOUBLE",
    "trade_date": "DATE",
}

RATES = {
    "date": "DATE",
    "yield_1_month": "DOUBLE",
    "yield_3_month": "DOUBLE",
    "yield_1_year": "DOUBLE",
    "yield_2_year": "DOUBLE",
    "yield_5_year": "DOUBLE",
    "yield_10_year": "DOUBLE",
    "yield_30_year": "DOUBLE",
}

# Unified corporate actions (NEW). One row per (symbol, ex_date) event.
#   split_ratio      forward share ratio (1.0 = no split). e.g. 7:1 -> 7.0, 10转15 -> 1.5
#   dividend_cash    cash per share in local currency (0.0 = none)
#   div_price_ratio  PRECOMPUTED (1 - cash/close_prev) so UPQ's on-read adjustment
#                    stays purely multiplicative (1.0 = no dividend effect)
CORPORATE_ACTIONS = {
    "symbol": "VARCHAR",
    "ex_date": "DATE",
    "split_ratio": "DOUBLE",
    "dividend_cash": "DOUBLE",
    "div_price_ratio": "DOUBLE",
    "currency": "VARCHAR",
    "source": "VARCHAR",
}

# Back-compat dividends store (option Greeks + /dividends/query) derived from
# the unified table.
DIVIDENDS = {
    "ticker": "VARCHAR",
    "ex_dividend_date": "DATE",
    "amount": "DOUBLE",
}


def select_list(schema: dict[str, str]) -> str:
    """Render ``CAST(col AS TYPE) AS col`` for every column, in order."""
    return ",\n    ".join(f"CAST({c} AS {t}) AS {c}" for c, t in schema.items())
