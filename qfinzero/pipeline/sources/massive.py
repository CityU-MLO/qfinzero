"""massive (Polygon-style) source reader.

Raw layout (read in place):
  us_stocks_sip/{day,minute}_aggs_v1/YYYY/MM/YYYY-MM-DD.parquet
  us_options_opra/{day,minute}_aggs_v1/YYYY/MM/YYYY-MM-DD.parquet
  economy/treasury_yields.jsonl
  corporate_actions/{splits,dividends}/<TICKER>.jsonl

Raw OHLCV columns: ticker, volume, open, close, high, low, window_start(ns), transactions.
There is no trade_date column — it is derived from the filename.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .. import schema
from ..engine import _lit

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\.parquet$")

# OPRA contract: O:{ROOT}{YYMMDD}{C|P}{strike*1000, 8 digits}
# (same parse as upq-ingest; ROOT may carry up to 2 trailing digits we ignore).
# Single-brace quantifiers: this is interpolated via f-strings into DuckDB SQL.
_OPRA_RE = r"^O:([A-Z]+)[0-9]{0,2}([0-9]{6})([CP])([0-9]{8})$"


@dataclass(frozen=True)
class DatedFile:
    trade_date: str  # YYYY-MM-DD
    path: Path


def list_dated_files(root: Path, start: str | None, end: str | None) -> list[DatedFile]:
    """Enumerate ``YYYY-MM-DD.parquet`` files under ``root`` within [start, end]."""
    out: list[DatedFile] = []
    for p in root.rglob("*.parquet"):
        m = _DATE_RE.search(p.name)
        if not m:
            continue
        d = m.group(1)
        if start and d < start:
            continue
        if end and d > end:
            continue
        out.append(DatedFile(d, p))
    out.sort(key=lambda f: f.trade_date)
    return out


# ── per-store SELECT builders (one source file -> one partition) ─────────

def stock_daily_sql(src: Path, trade_date: str) -> str:
    return f"""
        SELECT
            CAST(ticker AS VARCHAR) AS ticker,
            DATE '{trade_date}' AS trade_date,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close,
            CAST(volume AS BIGINT) AS volume,
            CAST(transactions AS BIGINT) AS transactions
        FROM read_parquet('{_lit(src)}')
        ORDER BY ticker
    """


def stock_minute_sql(src: Path, trade_date: str) -> str:
    return f"""
        SELECT
            CAST(ticker AS VARCHAR) AS ticker,
            CAST(window_start AS BIGINT) AS window_start,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close,
            CAST(volume AS BIGINT) AS volume,
            CAST(transactions AS BIGINT) AS transactions,
            DATE '{trade_date}' AS trade_date
        FROM read_parquet('{_lit(src)}')
        ORDER BY ticker, window_start
    """


def _option_select(src: Path, trade_date: str) -> str:
    """Shared option projection: parse the OPRA ticker into contract fields."""
    return f"""
        SELECT
            CAST(ticker AS VARCHAR) AS ticker,
            CAST(ticker AS VARCHAR) AS contract,
            regexp_extract(ticker, '{_OPRA_RE}', 1) AS underlying,
            strptime('20' || regexp_extract(ticker, '{_OPRA_RE}', 2), '%Y%m%d')::DATE AS expiry,
            CAST(regexp_extract(ticker, '{_OPRA_RE}', 4) AS DOUBLE) / 1000.0 AS strike,
            regexp_extract(ticker, '{_OPRA_RE}', 3) AS right,
            CAST(window_start AS BIGINT) AS window_start,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close,
            CAST(volume AS BIGINT) AS volume,
            CAST(transactions AS BIGINT) AS transactions,
            DATE '{trade_date}' AS trade_date
        FROM read_parquet('{_lit(src)}')
        WHERE regexp_matches(ticker, '{_OPRA_RE}')
        ORDER BY contract, window_start
    """


def option_day_sql(src: Path, trade_date: str) -> str:
    return _option_select(src, trade_date)


def option_minute_sql(src: Path, trade_date: str) -> str:
    return _option_select(src, trade_date)


def rates_sql(treasury_jsonl: Path) -> str:
    """massive treasury_yields.jsonl -> UPQ 7-tenor rates schema.

    Source only carries 1Y/5Y/10Y; the other four tenors are written NULL.
    """
    return f"""
        SELECT
            CAST(date AS DATE) AS date,
            CAST(NULL AS DOUBLE) AS yield_1_month,
            CAST(NULL AS DOUBLE) AS yield_3_month,
            CAST(yield_1_year AS DOUBLE) AS yield_1_year,
            CAST(NULL AS DOUBLE) AS yield_2_year,
            CAST(yield_5_year AS DOUBLE) AS yield_5_year,
            CAST(yield_10_year AS DOUBLE) AS yield_10_year,
            CAST(NULL AS DOUBLE) AS yield_30_year
        FROM read_json_auto('{_lit(treasury_jsonl)}')
        ORDER BY date
    """
