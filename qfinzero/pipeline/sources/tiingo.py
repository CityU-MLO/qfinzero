"""Tiingo BOATS (Blue Ocean ATS, 20:00-04:00 ET) raw files -> the stock stores.

Reads the library :mod:`qfinzero.admin.tiingo_dl` writes under
``$RAW_TIINGO_DIR/boats/`` in place and fills three stores with
``part-tiingo-0000.parquet``:

* ``stock_minute`` - overnight minutes that traded (Tiingo also returns
  zero-volume minutes carrying the last price; those are dropped);
* ``stock_overnight_daily`` - one bar per ticker and session, dated by the
  trading day it precedes (see :func:`databento.overnight_sessions`);
* ``stock_quote_minute`` - the BOATS top of book from the recorded snapshots,
  one row per (ticker, minute in which it changed).

Tiingo is the broad, lower-priority overnight source: a ticker another vendor
already has for that night (Databento's Blue Ocean order book) is left out
whole, so a series never mixes the two. Databento ignores these parts.

Conversion is two-stage like Databento: each month of bars and each day of
quote snapshots is read once into a staging parquet (cached on the files'
sizes and mtimes), then partitions are assembled from staging.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from ..engine import _lit
from . import databento

PART_NAME = "part-tiingo-0000.parquet"
EXTRACT_VERSION = 1
_ET = "America/New_York"
NIGHT = "(et_min >= 1200 OR et_min < 240)"


def price_months(root: Path) -> dict[str, list[Path]]:
    base = root / "boats" / "prices"
    return {d.name: sorted(d.glob("*.json.gz")) for d in sorted(base.glob("????-??")) if d.is_dir()} \
        if base.is_dir() else {}


def quote_days(root: Path) -> dict[str, list[Path]]:
    base = root / "boats" / "quotes"
    return {d.name: sorted(d.glob("*.json.gz")) for d in sorted(base.glob("????-??-??")) if d.is_dir()} \
        if base.is_dir() else {}


def files_fingerprint(files: Iterable[Path]) -> str:
    h = hashlib.sha1(f"v{EXTRACT_VERSION}".encode())
    for p in files:
        st = p.stat()
        h.update(f"{p.name}:{st.st_size}:{st.st_mtime_ns};".encode())
    return h.hexdigest()


def _list(files: list[Path]) -> str:
    return "[" + ", ".join(f"'{_lit(p)}'" for p in files) + "]"


def price_staging_sql(files: list[Path]) -> str:
    """Bars of one month of ticker files -> (ticker, window_start, trade_date, et_min, OHLCV)."""
    loc = f"timezone('{_ET}', ts)"
    return f"""
        WITH raw AS (
            SELECT upper(regexp_extract(filename, '([^/]+)\\.json\\.gz$', 1)) AS ticker,
                   CAST("date" AS TIMESTAMPTZ) AS ts,
                   CAST(open AS DOUBLE) AS open, CAST(high AS DOUBLE) AS high,
                   CAST(low AS DOUBLE) AS low, CAST(close AS DOUBLE) AS close,
                   CAST(volume AS DOUBLE) AS volume
            FROM read_json({_list(files)}, format = 'array', filename = true,
                           columns = {{'date': 'VARCHAR', 'open': 'DOUBLE', 'high': 'DOUBLE', 'low': 'DOUBLE',
                                       'close': 'DOUBLE', 'volume': 'DOUBLE'}})
        )
        SELECT ticker, epoch_ns(ts) AS window_start, CAST({loc} AS DATE) AS trade_date,
               hour({loc}) * 60 + minute({loc}) AS et_min,
               open, high, low, close, CAST(round(volume) AS BIGINT) AS volume
        FROM raw WHERE volume > 0 AND close IS NOT NULL
        QUALIFY row_number() OVER (PARTITION BY ticker, ts ORDER BY volume DESC) = 1"""


def quote_staging_sql(files: list[Path]) -> str:
    """One day of all-ticker snapshots -> the book per (ticker, minute it changed)."""
    loc = f"timezone('{_ET}', qts)"
    return f"""
        WITH raw AS (
            SELECT upper(ticker) AS ticker, CAST(quoteTimestamp AS TIMESTAMPTZ) AS qts,
                   CAST(bidPrice AS DOUBLE) AS bid, CAST(askPrice AS DOUBLE) AS ask,
                   CAST(bidSize AS DOUBLE) AS bsz, CAST(askSize AS DOUBLE) AS asz
            FROM read_json({_list(files)}, format = 'array',
                           columns = {{'ticker': 'VARCHAR', 'quoteTimestamp': 'VARCHAR', 'bidPrice': 'DOUBLE',
                                       'askPrice': 'DOUBLE', 'bidSize': 'DOUBLE', 'askSize': 'DOUBLE'}})
            WHERE quoteTimestamp IS NOT NULL AND bidPrice > 0 AND askPrice > 0
        ),
        t AS (
            SELECT *, epoch_ns(qts) AS last_ts, CAST({loc} AS DATE) AS trade_date,
                   hour({loc}) * 60 + minute({loc}) AS et_min FROM raw
        )
        SELECT ticker, last_ts // {databento.NS_PER_MIN} * {databento.NS_PER_MIN} AS window_start,
               trade_date, et_min, bid AS bid_price, ask AS ask_price,
               CAST(round(bsz) AS BIGINT) AS bid_size, CAST(round(asz) AS BIGINT) AS ask_size, last_ts
        FROM t WHERE {NIGHT}
        QUALIFY row_number() OVER (PARTITION BY ticker, window_start ORDER BY last_ts DESC) = 1"""


def _taken(siblings: list[Path], night_only: bool = True) -> str:
    """Tickers another vendor already has in this partition (overnight rows only)."""
    if not siblings:
        return ""
    sib = ", ".join(f"'{_lit(p)}'" for p in siblings)
    cond = ""
    if night_only:
        et = f"timezone('{_ET}', to_timestamp(window_start // 1000000000))"
        cond = f" WHERE hour({et}) >= 20 OR hour({et}) < 4"
    return f" AND ticker NOT IN (SELECT DISTINCT ticker FROM read_parquet([{sib}], union_by_name = true){cond})"


def minute_sql(staging: list[Path], trade_date: str, siblings: list[Path]) -> str:
    return f"""
        SELECT ticker, window_start, open, high, low, close, volume,
               CAST(NULL AS BIGINT) AS transactions, DATE '{trade_date}' AS trade_date
        FROM read_parquet({_list(staging)})
        WHERE trade_date = DATE '{trade_date}' AND {NIGHT}{_taken(siblings)}
        QUALIFY row_number() OVER (PARTITION BY ticker, window_start ORDER BY volume DESC) = 1
        ORDER BY ticker, window_start"""


def quote_sql(staging: list[Path], trade_date: str, siblings: list[Path]) -> str:
    return f"""
        SELECT ticker, window_start, bid_price, ask_price, bid_size, ask_size, DATE '{trade_date}' AS trade_date
        FROM read_parquet({_list(staging)})
        WHERE trade_date = DATE '{trade_date}'{_taken(siblings)}
        QUALIFY row_number() OVER (PARTITION BY ticker, window_start ORDER BY last_ts DESC) = 1
        ORDER BY ticker, window_start"""


def overnight_daily_sql(staging: list[Path], session: str, prev: str, siblings: list[Path]) -> str:
    return f"""
        WITH raw AS (
            SELECT * FROM read_parquet({_list(staging)})
            WHERE ((et_min >= 1200 AND trade_date >= DATE '{prev}' AND trade_date < DATE '{session}')
                OR (et_min < 240 AND trade_date > DATE '{prev}' AND trade_date <= DATE '{session}'))
              {_taken(siblings, night_only=False)}
            QUALIFY row_number() OVER (PARTITION BY ticker, window_start ORDER BY volume DESC) = 1
        )
        SELECT ticker, DATE '{session}' AS trade_date, arg_min(open, window_start) AS open, max(high) AS high,
               min(low) AS low, arg_max(close, window_start) AS close, CAST(sum(volume) AS BIGINT) AS volume,
               CAST(NULL AS BIGINT) AS transactions,
               min(window_start) AS first_window_start, max(window_start) AS last_window_start
        FROM raw GROUP BY ticker ORDER BY ticker"""


def sibling_parts(partition_dir: Path) -> list[Path]:
    """Every other vendor's part in a partition (Tiingo fills behind all of them)."""
    if not partition_dir.is_dir():
        return []
    return sorted(p for p in partition_dir.glob("*.parquet") if p.name != PART_NAME)
