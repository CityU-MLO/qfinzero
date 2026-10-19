"""massive (Polygon-style) source reader.

Raw layout (read in place):
  us_stocks_sip/{day,minute}_aggs_v1/YYYY/MM/YYYY-MM-DD.parquet
  us_options_opra/{day,minute}_aggs_v1/YYYY/MM/YYYY-MM-DD.parquet
  global_crypto/{day,minute}_aggs_v1/YYYY/MM/YYYY-MM-DD.csv.gz   (X:BTC-USD)
  global_forex/{day,minute}_aggs_v1, quotes_v1/...csv.gz           (C:EUR-USD)
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

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\.(?:parquet|csv\.gz)$")

# OPRA contract: O:{ROOT}{YYMMDD}{C|P}{strike*1000, 8 digits}
# (same parse as upq-ingest; ROOT may carry up to 2 trailing digits we ignore).
# Single-brace quantifiers: this is interpolated via f-strings into DuckDB SQL.
_OPRA_RE = r"^O:([A-Z]+)[0-9]{0,2}([0-9]{6})([CP])([0-9]{8})$"


@dataclass(frozen=True)
class DatedFile:
    trade_date: str  # YYYY-MM-DD
    path: Path


def list_dated_files(root: Path, start: str | None, end: str | None) -> list[DatedFile]:
    """Enumerate ``YYYY-MM-DD.parquet`` (or ``.csv.gz``, as massive ships the
    global flat files) under ``root`` within [start, end]; parquet wins when a
    day has both."""
    out: dict[str, DatedFile] = {}
    for p in sorted(root.rglob("*"), key=lambda x: x.suffix == ".parquet"):
        m = _DATE_RE.search(p.name)
        if not m:
            continue
        d = m.group(1)
        if start and d < start:
            continue
        if end and d > end:
            continue
        out[d] = DatedFile(d, p)
    return [out[d] for d in sorted(out)]


def read_src(src: Path) -> str:
    """DuckDB relation for one raw day file, parquet or gzip CSV."""
    if src.name.endswith(".csv.gz"):
        return f"read_csv('{_lit(src)}', header=true, auto_detect=true)"
    return f"read_parquet('{_lit(src)}')"


def _pair(col: str = "ticker") -> str:
    """``X:BTC-USD`` / ``C:EUR-USD`` -> ticker, base, quote."""
    t = f"regexp_replace(CAST({col} AS VARCHAR), '^[A-Z]:', '')"
    return f"{t} AS ticker, split_part({t}, '-', 1) AS base, split_part({t}, '-', 2) AS quote"


def pair_daily_sql(src: Path, trade_date: str) -> str:
    return f"""
        SELECT {_pair()}, DATE '{trade_date}' AS trade_date,
            CAST(open AS DOUBLE) AS open, CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low, CAST(close AS DOUBLE) AS close,
            CAST(volume AS DOUBLE) AS volume, CAST(transactions AS BIGINT) AS transactions
        FROM {read_src(src)}
        ORDER BY ticker
    """


def pair_minute_sql(src: Path, trade_date: str) -> str:
    return f"""
        SELECT {_pair()}, CAST(window_start AS BIGINT) AS window_start,
            CAST(open AS DOUBLE) AS open, CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low, CAST(close AS DOUBLE) AS close,
            CAST(volume AS DOUBLE) AS volume, CAST(transactions AS BIGINT) AS transactions,
            DATE '{trade_date}' AS trade_date
        FROM {read_src(src)}
        ORDER BY ticker, window_start
    """


def fx_quote_sql(src: Path, trade_date: str, interval: int = 1) -> str:
    """Last FX quote of each minute (or ``interval``-minute bucket) per pair,
    within the UTC day of the file."""
    from .databento import NS_PER_MIN, check_interval, sample_sql
    return f"""
        WITH t AS (
            SELECT CAST(ticker AS VARCHAR) AS raw, CAST(participant_timestamp AS BIGINT) AS ts,
                   CAST(bid_price AS DOUBLE) AS bid, CAST(ask_price AS DOUBLE) AS ask
            FROM {read_src(src)} WHERE participant_timestamp IS NOT NULL
        ),
        m1 AS (
            SELECT raw, ts // {NS_PER_MIN} * {NS_PER_MIN} AS window_start,
                   arg_max(bid, ts) AS bid_price, arg_max(ask, ts) AS ask_price
            FROM t GROUP BY 1, 2
        ),
        m2 AS (
            SELECT {_pair("raw")}, window_start, bid_price, ask_price FROM m1
            WHERE CAST(to_timestamp(window_start // 1000000000) AT TIME ZONE 'UTC' AS DATE) = DATE '{trade_date}'
        ),
        q AS ({sample_sql("m2", check_interval(interval))})
        SELECT ticker, base, quote, window_start, bid_price, ask_price, DATE '{trade_date}' AS trade_date
        FROM q ORDER BY ticker, window_start
    """



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


# ── quotes (NBBO) ─────────────────────────────────────────────────────────
#
# Raw quotes live under {us_options_opra,us_stocks_sip}/quotes_v1/ as parquet
# with at least: ticker, sip_timestamp (ns), bid_price, ask_price, bid_size,
# ask_size. One file per day (the flat file) or several per day (one per
# contract, e.g. REST samples); the date is taken from the path. The data
# setup utility normalises csv.gz flat files, REST jsonl.gz samples and
# snapshot parquet (mark_ns) into this layout.

QUOTE_INDEX = {"option": "us_options_opra/quotes_v1", "stock": "us_stocks_sip/quotes_v1"}
_ANY_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def list_quote_files(root: Path, start: str | None, end: str | None) -> dict[str, list[Path]]:
    """Parquet quote files under ``root`` grouped by trade date (from the path)."""
    out: dict[str, list[Path]] = {}
    if not root.is_dir():
        return out
    for p in root.rglob("*.parquet"):
        m = _ANY_DATE_RE.findall(str(p.relative_to(root)))
        if not m:
            continue
        d = m[-1]
        if (start and d < start) or (end and d > end):
            continue
        out.setdefault(d, []).append(p)
    return {d: sorted(v) for d, v in sorted(out.items())}


def quote_sql(store: str, files: list[Path], trade_date: str, interval: int = 1) -> str:
    """Last NBBO of each minute (or of each ``interval``-minute bucket) per ticker.

    ``window_start`` is the minute the quote falls in, so a row is the book at
    the end of that minute, like the Databento quote stores.
    """
    from .databento import NS_PER_MIN, check_interval, sample_sql
    src = "read_parquet([" + ",".join(f"'{_lit(f)}'" for f in files) + "], union_by_name=true)"
    et = "timezone('America/New_York', to_timestamp(window_start // 1000000000))"
    base = f"""
        WITH t AS (
            SELECT CAST(ticker AS VARCHAR) AS ticker, CAST(sip_timestamp AS BIGINT) AS ts,
                   CAST(bid_price AS DOUBLE) AS bid, CAST(ask_price AS DOUBLE) AS ask,
                   CAST(bid_size AS BIGINT) AS bsz, CAST(ask_size AS BIGINT) AS asz
            FROM {src} WHERE sip_timestamp IS NOT NULL
        ),
        m1 AS (
            SELECT ticker, ts // {NS_PER_MIN} * {NS_PER_MIN} AS window_start,
                   arg_max(bid, ts) AS bid_price, arg_max(ask, ts) AS ask_price,
                   arg_max(bsz, ts) AS bid_size, arg_max(asz, ts) AS ask_size
            FROM t GROUP BY 1, 2
        ),
        m2 AS (SELECT * FROM m1 WHERE CAST({et} AS DATE) = DATE '{trade_date}'),
        q AS ({sample_sql("m2", check_interval(interval))})"""
    if store == "stock_quote_minute":
        return base + f"""
        SELECT ticker, window_start, bid_price, ask_price, bid_size, ask_size, DATE '{trade_date}' AS trade_date
        FROM q ORDER BY ticker, window_start"""
    return base + f"""
        SELECT ticker, ticker AS contract,
               regexp_extract(ticker, '{_OPRA_RE}', 1) AS underlying,
               strptime('20' || regexp_extract(ticker, '{_OPRA_RE}', 2), '%Y%m%d')::DATE AS expiry,
               CAST(regexp_extract(ticker, '{_OPRA_RE}', 4) AS DOUBLE) / 1000.0 AS strike,
               regexp_extract(ticker, '{_OPRA_RE}', 3) AS "right",
               window_start, bid_price, ask_price, bid_size, ask_size, DATE '{trade_date}' AS trade_date
        FROM q WHERE regexp_matches(ticker, '{_OPRA_RE}')
        ORDER BY contract, window_start"""
