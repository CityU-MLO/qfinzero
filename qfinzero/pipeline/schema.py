"""UPQ on-disk target schemas — the single source of truth for the converter.

These mirror exactly what the UPQ Rust service reads (verified against
``infra/upq/crates/upq-ingest``). The converter casts every source into these
column names and DuckDB types before writing ZSTD parquet.

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
