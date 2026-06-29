"""Unified corporate-actions table builder.

Produces ``corporate_actions/corporate_actions.parquet`` with one row per
(symbol, ex_date) event and columns (see :mod:`schema`):

    symbol, ex_date, split_ratio, dividend_cash, div_price_ratio, currency, source

The forward-split / cash-dividend math follows Assay (``adjust.py``/``ingest.py``)
but is simplified for streaming quotes: instead of recomputing dividend factors at
query time, we **precompute** ``div_price_ratio = 1 - cash/close_prev`` here, where
``close_prev`` is the last trading close strictly before ``ex_date`` (ASOF join to
the converted stock_daily store). UPQ then only multiplies ratios on read.

Sources:
  * massive splits   : split_ratio = split_to / split_from   (supports fractional)
  * massive dividends: dividend_cash = cash_amount (USD)
  * tushare dividends: 实施 only; split_ratio = 1 + stk_div (送转); cash = cash_div_tax|cash_div (CNY)
"""

from __future__ import annotations

from .engine import _lit
from .paths import PipelinePaths

# A dividend's price ratio is only applied when the prior trading close is within
# this many calendar days of the ex-date (matches Assay's gap guard, widened to
# tolerate long CN holidays like Spring Festival). Beyond it, the prior close is
# treated as a data gap (stale/partial history) and no dividend adjustment is made.
MAX_PRIOR_GAP_DAYS = 15


def _massive_splits_sql(p: PipelinePaths) -> str:
    glob = _lit(p.massive_splits / "*.jsonl")
    return f"""
        SELECT
            CAST(ticker AS VARCHAR) AS symbol,
            CAST(execution_date AS DATE) AS ex_date,
            CAST(split_to AS DOUBLE) / CAST(split_from AS DOUBLE) AS split_ratio,
            0.0 AS dividend_cash,
            'USD' AS currency,
            'massive:split' AS source
        FROM read_json_auto('{glob}', format='newline_delimited', union_by_name=true)
        WHERE split_from > 0 AND split_to > 0 AND execution_date IS NOT NULL
    """


def _massive_dividends_sql(p: PipelinePaths) -> str:
    glob = _lit(p.massive_dividends / "*.jsonl")
    return f"""
        SELECT
            CAST(ticker AS VARCHAR) AS symbol,
            CAST(ex_dividend_date AS DATE) AS ex_date,
            1.0 AS split_ratio,
            CAST(cash_amount AS DOUBLE) AS dividend_cash,
            COALESCE(CAST(currency AS VARCHAR), 'USD') AS currency,
            'massive:dividend' AS source
        FROM read_json_auto('{glob}', format='newline_delimited', union_by_name=true)
        WHERE cash_amount > 0 AND ex_dividend_date IS NOT NULL
    """


def _tushare_dividends_sql(p: PipelinePaths) -> str:
    glob = _lit(p.tushare_cn_dividend / "*.parquet")
    return f"""
        SELECT
            CAST(ts_code AS VARCHAR) AS symbol,
            strptime(ex_date, '%Y%m%d')::DATE AS ex_date,
            1.0 + COALESCE(CAST(stk_div AS DOUBLE), 0.0) AS split_ratio,
            CASE WHEN COALESCE(CAST(cash_div_tax AS DOUBLE), 0.0) > 0
                 THEN CAST(cash_div_tax AS DOUBLE)
                 ELSE COALESCE(CAST(cash_div AS DOUBLE), 0.0) END AS dividend_cash,
            'CNY' AS currency,
            'tushare:dividend' AS source
        FROM read_parquet('{glob}', union_by_name=true)
        WHERE div_proc = '实施'
          AND ex_date IS NOT NULL AND ex_date <> ''
          AND (COALESCE(CAST(stk_div AS DOUBLE), 0.0) > 0
               OR COALESCE(CAST(cash_div AS DOUBLE), 0.0) > 0
               OR COALESCE(CAST(cash_div_tax AS DOUBLE), 0.0) > 0)
    """


def build_sql(p: PipelinePaths, include_massive: bool, include_tushare: bool) -> str:
    """Full SELECT for the unified corporate-actions table.

    ``div_price_ratio`` is derived by ASOF-joining each event to the latest
    converted stock_daily close strictly before ``ex_date``. If no prior close is
    available (price out of converted range), it defaults to 1.0 (no dividend
    price effect) — the same conservative guard Assay uses for data gaps.
    """
    parts: list[str] = []
    if include_massive:
        parts.append(_massive_splits_sql(p))
        parts.append(_massive_dividends_sql(p))
    if include_tushare:
        parts.append(_tushare_dividends_sql(p))
    if not parts:
        raise ValueError("no corporate-action sources selected")

    events = "\n        UNION ALL BY NAME\n".join(f"({s})" for s in parts)
    price_glob = _lit(p.store("stock_daily") / "trade_date=*" / "*.parquet")

    return f"""
        WITH ev AS (
            {events}
        ),
        prices AS (
            SELECT ticker AS symbol, trade_date, close
            FROM read_parquet('{price_glob}', union_by_name=true)
        ),
        joined AS (
            SELECT ev.symbol, ev.ex_date, ev.split_ratio, ev.dividend_cash,
                   ev.currency, ev.source,
                   p.close AS close_prev, p.trade_date AS prev_date
            FROM ev
            ASOF LEFT JOIN prices p
              ON ev.symbol = p.symbol AND ev.ex_date > p.trade_date
        )
        SELECT
            CAST(symbol AS VARCHAR) AS symbol,
            CAST(ex_date AS DATE) AS ex_date,
            CAST(split_ratio AS DOUBLE) AS split_ratio,
            CAST(dividend_cash AS DOUBLE) AS dividend_cash,
            CAST(
                CASE
                    WHEN dividend_cash > 0 AND close_prev IS NOT NULL
                         AND close_prev > 0 AND dividend_cash < close_prev
                         AND datediff('day', prev_date, ex_date) <= {MAX_PRIOR_GAP_DAYS}
                    THEN 1.0 - dividend_cash / close_prev
                    ELSE 1.0
                END AS DOUBLE) AS div_price_ratio,
            CAST(currency AS VARCHAR) AS currency,
            CAST(source AS VARCHAR) AS source
        FROM joined
        WHERE NOT (split_ratio = 1.0 AND dividend_cash = 0.0)
        ORDER BY symbol, ex_date
    """


def dividends_backcompat_sql(p: PipelinePaths) -> str:
    """Derive the legacy dividends store (ticker, ex_dividend_date, amount)
    used by option Greeks and ``/dividends/query`` from the unified table."""
    ca_glob = _lit(p.store("corporate_actions") / "corporate_actions.parquet")
    return f"""
        SELECT
            CAST(symbol AS VARCHAR) AS ticker,
            CAST(ex_date AS DATE) AS ex_dividend_date,
            CAST(dividend_cash AS DOUBLE) AS amount
        FROM read_parquet('{ca_glob}')
        WHERE dividend_cash > 0
        ORDER BY ticker, ex_dividend_date
    """
