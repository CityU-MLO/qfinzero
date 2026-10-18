"""Columnar access to UPQ storage for research (DuckDB over the parquet stores).

Research reads the same partitions the UPQ service serves, but in bulk: one
SQL over many tickers and days instead of paged REST calls.

The panel is a *dense* minute grid per (ticker, trade date): minutes with no
trade carry the previous close forward (volume 0, ``has_bar = false``), so
``lag``/``lead`` by ``n`` rows is exactly ``n`` minutes. Universes are point
in time: the top N by the *previous* trading day's dollar volume.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Optional, Sequence

from ..pipeline.engine import _lit, connect
from ..pipeline.paths import resolve

_ET = "America/New_York"
SESSIONS = {"regular": (570, 960), "extended": (240, 1200)}   # [start, end) ET minutes
BAR_MINUTES = (1, 2, 3, 5, 10, 15, 30, 60)
_TICKER_RE = r"^[A-Z]{1,5}$"     # common-stock-looking symbols for default universes


@dataclass
class PanelSpec:
    start: str
    end: str
    universe: object = 500            # int top-N | list of tickers
    session: str = "regular"
    bar_minutes: int = 1
    quotes: bool = False
    min_price: float = 5.0
    as_of_ns: Optional[int] = None    # time lock: drop bars not final at as_of


def _dates(root: Path, store: str, start: str, end: str) -> list[str]:
    d = root / store
    if not d.is_dir():
        return []
    out = []
    for p in d.iterdir():
        if p.is_dir() and p.name.startswith("trade_date="):
            day = p.name[len("trade_date="):]
            if start <= day <= end and any(p.glob("*.parquet")):
                out.append(day)
    return sorted(out)


def _file_list(root: Path, store: str, days: Iterable[str]) -> str:
    files = [str(root / store / f"trade_date={d}" / "*.parquet") for d in days]
    return "[" + ", ".join(f"'{_lit(f)}'" for f in files) + "]"


class Research:
    """Research session over a UPQ storage root."""

    def __init__(self, storage: str | Path | None = None, threads: int | None = None):
        self.root = Path(storage) if storage else resolve().storage
        self.con = connect(threads)

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "Research":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── universes ────────────────────────────────────────────────────

    def trading_days(self, start: str, end: str) -> list[str]:
        return _dates(self.root, "stock_minute", start, end)

    def universe_table(self, spec: PanelSpec, days: Sequence[str]) -> str:
        """Create temp table ``_universe(trade_date, ticker)``; return its name."""
        self.con.execute("DROP TABLE IF EXISTS _universe")
        if not isinstance(spec.universe, int):
            tickers = [str(t).strip().upper() for t in spec.universe if str(t).strip()]
            if not tickers:
                raise ValueError("universe list is empty")
            vals = ", ".join(f"(DATE '{d}', '{_lit(t)}')" for d in days for t in tickers)
            self.con.execute(f"CREATE TEMP TABLE _universe AS SELECT * FROM (VALUES {vals}) "
                             f"t(trade_date, ticker)")
            return "_universe"
        top_n = int(spec.universe)
        lookback = (date.fromisoformat(days[0]) - timedelta(days=14)).isoformat()
        ddays = _dates(self.root, "stock_daily", lookback, days[-1])
        if not ddays:
            raise ValueError("no stock_daily data to rank the universe")
        self.con.execute(f"""
            CREATE TEMP TABLE _universe AS
            WITH d AS (
                SELECT ticker, trade_date, close, close * volume AS dv
                FROM read_parquet({_file_list(self.root, 'stock_daily', ddays)}, union_by_name=true)
                WHERE regexp_matches(ticker, '{_TICKER_RE}')
            ),
            p AS (
                SELECT ticker, trade_date,
                       lag(dv) OVER (PARTITION BY ticker ORDER BY trade_date) AS prev_dv,
                       lag(close) OVER (PARTITION BY ticker ORDER BY trade_date) AS prev_close
                FROM d
            )
            SELECT trade_date, ticker FROM p
            WHERE trade_date >= DATE '{days[0]}' AND trade_date <= DATE '{days[-1]}'
              AND prev_close >= {float(spec.min_price)} AND prev_dv IS NOT NULL
            QUALIFY row_number() OVER (PARTITION BY trade_date ORDER BY prev_dv DESC) <= {top_n}
        """)
        return "_universe"

    # ── the panel ───────────────────────────────────────────────────

    def build_panel(self, spec: PanelSpec) -> dict:
        """Create temp table ``_panel``; returns metadata (days, tickers, rows)."""
        if spec.session not in SESSIONS:
            raise ValueError(f"session must be one of {sorted(SESSIONS)}")
        if spec.bar_minutes not in BAR_MINUTES:
            raise ValueError(f"bar_minutes must be one of {BAR_MINUTES}")
        days = self.trading_days(spec.start, spec.end)
        if not days:
            raise ValueError(f"no stock_minute data between {spec.start} and {spec.end}")
        uni = self.universe_table(spec, days)
        lo, hi = SESSIONS[spec.session]
        n = int(spec.bar_minutes)
        cap = f"AND b.window_start <= {int(spec.as_of_ns) - 60_000_000_000}" if spec.as_of_ns else ""
        quotes_join, quote_cols = "", ""
        qdays = _dates(self.root, "stock_quote_minute", spec.start, spec.end) if spec.quotes else []
        if spec.quotes and qdays:
            quotes_join = f"""
                ASOF LEFT JOIN (
                    SELECT ticker, window_start AS q_ws, bid_price, ask_price, bid_size, ask_size
                    FROM read_parquet({_file_list(self.root, 'stock_quote_minute', qdays)})
                ) q ON q.ticker = g.ticker AND q.q_ws <= g.window_start"""
            quote_cols = """,
                q.bid_price AS bid, q.ask_price AS ask,
                CASE WHEN q.bid_price > 0 AND q.ask_price >= q.bid_price
                     THEN (q.bid_price + q.ask_price) / 2 END AS mid,
                CASE WHEN q.bid_price > 0 AND q.ask_price >= q.bid_price
                     THEN (q.ask_price - q.bid_price) / ((q.bid_price + q.ask_price) / 2) END AS spread,
                (q.bid_size - q.ask_size) / nullif(q.bid_size + q.ask_size, 0) AS imbalance"""
        elif spec.quotes:
            quote_cols = """, NULL::DOUBLE AS bid, NULL::DOUBLE AS ask, NULL::DOUBLE AS mid,
                NULL::DOUBLE AS spread, NULL::DOUBLE AS imbalance"""
        self.con.execute("DROP TABLE IF EXISTS _panel")
        self.con.execute(f"""
            CREATE TEMP TABLE _panel AS
            WITH bars AS (
                SELECT b.ticker, b.trade_date, b.window_start, b.open, b.high, b.low, b.close,
                       b.volume, b.transactions
                FROM read_parquet({_file_list(self.root, 'stock_minute', days)}, union_by_name=true) b
                JOIN {uni} u ON u.ticker = b.ticker AND u.trade_date = b.trade_date
                WHERE TRUE {cap}
            ),
            grid AS (
                SELECT u.ticker, u.trade_date, m.minute,
                       epoch_ns(timezone('{_ET}', u.trade_date + to_minutes(m.minute))) AS window_start
                FROM {uni} u, (SELECT range AS minute FROM range({lo}, {hi})) m
            ),
            dense AS (
                SELECT g.ticker, g.trade_date, g.window_start, g.minute - {lo} AS minute,
                       b.open, b.high, b.low, b.close AS bar_close, coalesce(b.volume, 0) AS volume,
                       coalesce(b.transactions, 0) AS transactions, b.close IS NOT NULL AS has_bar
                FROM grid g LEFT JOIN bars b USING (ticker, trade_date, window_start)
            ),
            filled AS (
                SELECT *, last_value(bar_close IGNORE NULLS) OVER (
                    PARTITION BY ticker, trade_date ORDER BY window_start
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS close
                FROM dense
            ),
            rs AS (
                SELECT ticker, trade_date, min(window_start) AS window_start, min(minute) AS minute,
                       arg_min(coalesce(open, close), window_start) FILTER (WHERE close IS NOT NULL) AS open,
                       max(coalesce(high, close)) AS high, min(coalesce(low, close)) AS low,
                       arg_max(close, window_start) AS close,
                       sum(volume) AS volume, sum(transactions) AS transactions,
                       bool_or(has_bar) AS has_bar
                FROM filled
                GROUP BY ticker, trade_date, minute // {n}
            )
            SELECT g.ticker, g.trade_date, g.window_start, g.minute, g.open, g.high, g.low, g.close,
                   g.volume, g.transactions, g.has_bar,
                   (g.high + g.low + g.close) / 3 AS vwap,
                   g.close / nullif(lag(g.close) OVER (
                       PARTITION BY g.ticker, g.trade_date ORDER BY g.window_start), 0) - 1 AS ret
                   {quote_cols}
            FROM rs g {quotes_join}
        """)
        meta = self.con.execute(
            "SELECT count(*), count(DISTINCT ticker), count(DISTINCT trade_date) FROM _panel").fetchone()
        return {"days": days, "rows": int(meta[0]), "tickers": int(meta[1]),
                "n_days": int(meta[2]), "bar_minutes": n, "session": spec.session}


def valid_symbol(s: str) -> bool:
    return bool(re.match(r"^[A-Z][A-Z0-9.]{0,9}$", s or ""))
