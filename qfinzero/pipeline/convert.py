"""Converter: raw vendor data -> UPQ storage (partitioned ZSTD parquet).

Writes exactly the layout the UPQ service reads (one file per ``trade_date=X/``
partition, ``trade_date`` carried in-file), so the output is byte-compatible with
the Rust ``upq-ingest``.

Order for a full build:  stocks -> options -> rates -> corporate_actions
(corporate_actions derives dividend price ratios from the converted stock_daily).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from . import corporate_actions as ca
from .engine import connect, copy_to_parquet
from .manifest import Manifest
from .paths import PipelinePaths, resolve
from .sources import massive, tushare


@dataclass
class ConvertResult:
    store: str
    partitions: int = 0
    rows: int = 0
    skipped: int = 0
    notes: list[str] = field(default_factory=list)

    def log(self) -> str:
        n = f"  ({'; '.join(self.notes)})" if self.notes else ""
        return f"{self.store:18} partitions={self.partitions:5d} rows={self.rows:>12,} skipped={self.skipped}{n}"


class Converter:
    def __init__(self, paths: PipelinePaths | None = None, threads: int | None = None):
        self.p = paths or resolve()
        self.con = connect(threads)
        self.manifest = Manifest.load(self.p.storage)

    def close(self) -> None:
        self.manifest.save()
        self.con.close()

    def __enter__(self) -> "Converter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── per-date massive stores (stock/option day & minute) ─────────────

    def _convert_dated(self, store, root, sql_fn, start, end, force) -> ConvertResult:
        res = ConvertResult(store)
        for f in massive.list_dated_files(root, start, end):
            if not force and self.manifest.is_current(store, f.trade_date, f.path):
                res.skipped += 1
                continue
            out = self.p.partition(store, f.trade_date) / "part-0000.parquet"
            rows = copy_to_parquet(self.con, sql_fn(f.path, f.trade_date), out)
            self.manifest.record(store, f.trade_date, f.path, rows)
            res.partitions += 1
            res.rows += rows
        return res

    def convert_us_stock_daily(self, start=None, end=None, force=False) -> ConvertResult:
        return self._convert_dated("stock_daily", self.p.massive_stock_day,
                                   massive.stock_daily_sql, start, end, force)

    def convert_us_stock_minute(self, start=None, end=None, force=False) -> ConvertResult:
        return self._convert_dated("stock_minute", self.p.massive_stock_minute,
                                   massive.stock_minute_sql, start, end, force)

    def convert_us_option_day(self, start=None, end=None, force=False) -> ConvertResult:
        return self._convert_dated("option_day", self.p.massive_option_day,
                                   massive.option_day_sql, start, end, force)

    def convert_us_option_minute(self, start=None, end=None, force=False) -> ConvertResult:
        return self._convert_dated("option_minute", self.p.massive_option_minute,
                                   massive.option_minute_sql, start, end, force)

    # ── CN A-shares (regroup per-symbol files into per-date partitions) ──

    def convert_cn_stock_daily(self, start=None, end=None, force=False) -> ConvertResult:
        res = ConvertResult("stock_daily")
        glob = tushare.daily_glob(self.p.tushare_cn_daily)
        # Read the per-symbol files once into a temp table, then partition by date
        # in memory (avoids re-scanning thousands of files per trade date).
        try:
            self.con.execute("DROP TABLE IF EXISTS _cn_daily")
            self.con.execute(
                f"CREATE TEMP TABLE _cn_daily AS {tushare.all_daily_sql(glob, start, end)}")
        except Exception as e:  # noqa: BLE001 - surface as a note, keep going
            res.notes.append(f"cn daily unavailable: {e}")
            return res
        dates = [r[0] for r in self.con.execute(
            "SELECT DISTINCT strftime(trade_date, '%Y-%m-%d') FROM _cn_daily ORDER BY 1"
        ).fetchall()]
        for d in dates:
            out = self.p.partition("stock_daily", d) / "part-cn-0000.parquet"
            rows = copy_to_parquet(
                self.con,
                f"SELECT * FROM _cn_daily WHERE trade_date = DATE '{d}' ORDER BY ticker",
                out)
            self.manifest.record("stock_daily", f"cn:{d}", None, rows)
            res.partitions += 1
            res.rows += rows
        self.con.execute("DROP TABLE IF EXISTS _cn_daily")
        return res

    # ── rates (single file) ─────────────────────────────────────────────

    def convert_rates(self, force=False) -> ConvertResult:
        res = ConvertResult("rates")
        src = self.p.massive_treasury
        if not src.exists():
            res.notes.append("treasury_yields.jsonl missing")
            return res
        out = self.p.store("rates") / "rates.parquet"
        rows = copy_to_parquet(self.con, massive.rates_sql(src), out)
        res.partitions = 1
        res.rows = rows
        res.notes.append("only 1Y/5Y/10Y populated (massive source limitation)")
        return res

    # ── corporate actions (+ back-compat dividends store) ───────────────

    def convert_corporate_actions(self, include_massive=True, include_tushare=True) -> ConvertResult:
        res = ConvertResult("corporate_actions")
        out = self.p.store("corporate_actions") / "corporate_actions.parquet"
        rows = copy_to_parquet(
            self.con, ca.build_sql(self.p, include_massive, include_tushare), out)
        res.partitions = 1
        res.rows = rows
        # derive legacy dividends store for option Greeks / /dividends/query
        if rows:
            div_out = self.p.store("dividends") / "dividends.parquet"
            drows = copy_to_parquet(self.con, ca.dividends_backcompat_sql(self.p), div_out)
            res.notes.append(f"dividends.parquet rows={drows}")
        return res


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
