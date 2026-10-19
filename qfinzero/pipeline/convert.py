"""Converter: raw vendor data -> UPQ storage (partitioned ZSTD parquet).

Writes exactly the layout the UPQ service reads (one file per ``trade_date=X/``
partition, ``trade_date`` carried in-file), so the output is byte-compatible with
the Rust ``upq-ingest``.

Order for a full build:  stocks -> options -> databento -> rates -> corporate_actions
(corporate_actions derives dividend price ratios from the converted stock_daily;
Databento fills only tickers the other vendors did not write for a date).
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import corporate_actions as ca
from .engine import connect, copy_to_parquet
from .manifest import Manifest
from .paths import PipelinePaths, resolve
from .sources import databento, massive, tushare


def default_quote_intervals() -> dict[str, int]:
    """Quote sampling per asset: ``QFZ_{STOCK,OPTION,FUTURE}_QUOTE_INTERVAL`` or
    the data setup setting (``quotes.<asset>_interval_min``), else 1 minute.
    Persisted so scheduled updates keep the interval a store was built with."""
    out = {"stock": 1, "option": 1, "future": 1, "fx": 1}
    try:
        from qfinzero.admin import config_store
        q = config_store.load().get("quotes", {}) or {}
        for a in out:
            if q.get(f"{a}_interval_min"):
                out[a] = int(q[f"{a}_interval_min"])
    except Exception:  # noqa: BLE001 — config optional
        pass
    import os
    for a in out:
        v = os.environ.get(f"QFZ_{a.upper()}_QUOTE_INTERVAL")
        if v:
            out[a] = int(v)
    return {a: databento.check_interval(v) for a, v in out.items()}


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

    def _convert_dated(self, store, root, sql_fn, start, end, force, refilter=True) -> ConvertResult:
        res = ConvertResult(store)
        refiltered = 0
        for f in massive.list_dated_files(root, start, end):
            if not force and self.manifest.is_current(store, f.trade_date, f.path):
                res.skipped += 1
                continue
            out = self.p.partition(store, f.trade_date) / "part-0000.parquet"
            rows = copy_to_parquet(self.con, sql_fn(f.path, f.trade_date), out)
            self.manifest.record(store, f.trade_date, f.path, rows)
            # keep Databento fill-only: drop tickers this vendor now covers
            if refilter and databento.refilter_part(self.con, out.parent) is not None:
                refiltered += 1
            res.partitions += 1
            res.rows += rows
        if refiltered:
            res.notes.append(f"{refiltered} databento part(s) re-filtered")
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

    # ── crypto and FX (massive global flat files, UTC days) ─────────────

    # First conversions of the large stores keep to recent history unless a
    # start is given (``qfz-data convert --asset fx --resolution minute --start 2014-01-01``).
    RECENT_DAYS = {"crypto_minute": 400, "fx_minute": 400, "fx_quote_minute": 60}

    def _recent(self, store: str, root, start):
        if start or store not in self.RECENT_DAYS:
            return start
        files = massive.list_dated_files(root, None, None)
        if not files:
            return start
        from datetime import date, timedelta
        return (date.fromisoformat(files[-1].trade_date) - timedelta(days=self.RECENT_DAYS[store])).isoformat()

    def convert_crypto_daily(self, start=None, end=None, force=False) -> ConvertResult:
        return self._convert_dated("crypto_daily", self.p.massive_crypto_day, massive.pair_daily_sql,
                                   start, end, force, refilter=False)

    def convert_crypto_minute(self, start=None, end=None, force=False) -> ConvertResult:
        root = self.p.massive_crypto_minute
        return self._convert_dated("crypto_minute", root, massive.pair_minute_sql,
                                   self._recent("crypto_minute", root, start), end, force, refilter=False)

    def convert_fx_daily(self, start=None, end=None, force=False) -> ConvertResult:
        return self._convert_dated("fx_daily", self.p.massive_fx_day, massive.pair_daily_sql,
                                   start, end, force, refilter=False)

    def convert_fx_minute(self, start=None, end=None, force=False) -> ConvertResult:
        root = self.p.massive_fx_minute
        return self._convert_dated("fx_minute", root, massive.pair_minute_sql,
                                   self._recent("fx_minute", root, start), end, force, refilter=False)

    def convert_fx_quotes(self, start=None, end=None, force=False, interval: int | None = None) -> ConvertResult:
        """massive FX quotes -> ``fx_quote_minute``, sampled every ``interval``
        minutes (the ``fx`` quote interval, default 1)."""
        store, root = "fx_quote_minute", self.p.massive_fx_quotes
        interval = databento.check_interval(interval or default_quote_intervals().get("fx", 1))
        res = ConvertResult(store)
        for f in massive.list_dated_files(root, self._recent(store, root, start), end):
            fp = databento.fingerprint([f.path]) + f"|q{interval}m"
            mkey = f"massive:{store}/{f.trade_date}"
            if not force and self.manifest.fp_current(mkey, fp):
                res.skipped += 1
                continue
            out = self.p.partition(store, f.trade_date) / "part-0000.parquet"
            rows = copy_to_parquet(self.con, massive.fx_quote_sql(f.path, f.trade_date, interval), out)
            self.manifest.put(mkey, {"fp": fp, "rows": rows, "inputs": 1, "trade_date": f.trade_date,
                                     "store": store, "interval_min": interval})
            res.partitions += 1
            res.rows += rows
        if interval != 1:
            res.notes.append(f"sampled every {interval} min")
        return res

    def convert_us_quotes(self, asset: str, start=None, end=None, force=False,
                          interval: int | None = None) -> ConvertResult:
        """massive NBBO (``quotes_v1``) -> the stock / option quote store, sampled
        every ``interval`` minutes (1 = every minute)."""
        store = "option_quote_minute" if asset == "option" else "stock_quote_minute"
        res = ConvertResult(store)
        interval = databento.check_interval(interval or default_quote_intervals()[asset])
        root = self.p.massive / massive.QUOTE_INDEX[asset]
        for d, files in massive.list_quote_files(root, start, end).items():
            fp = databento.fingerprint(files) + f"|q{interval}m"
            mkey = f"massive:{store}/{d}"
            if not force and self.manifest.fp_current(mkey, fp):
                res.skipped += 1
                continue
            out = self.p.partition(store, d) / "part-0000.parquet"
            rows = copy_to_parquet(self.con, massive.quote_sql(store, files, d, interval), out)
            self.manifest.put(mkey, {"fp": fp, "rows": rows, "inputs": len(files), "trade_date": d,
                                     "store": store, "interval_min": interval})
            if databento.refilter_part(self.con, out.parent) is not None:
                res.notes.append(f"{d}: databento quotes re-filtered")
            res.partitions += 1
            res.rows += rows
        if interval != 1:
            res.notes.append(f"sampled every {interval} min")
        return res

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

    # ── Databento (DBN / parquet, any layout) ───────────────────────────

    def convert_databento(self, start=None, end=None, force=False, jobs=None,
                          assets=("stock", "option", "future"), quote_interval=None) -> ConvertResult:
        """Databento files -> ``part-databento-0000.parquet`` in the four bar stores.

        Stage 1 extracts each new/changed raw file into cached staging bars
        (``jobs`` worker processes). Stage 2 rebuilds every (store, date) whose
        inputs changed, with fill precedence against other vendors' parts.
        """
        res = ConvertResult("databento")
        root = self.p.databento
        if not root.is_dir():
            res.notes.append(f"{root} missing")
            return res
        files = databento.index(root, self.p.state_dir, self.con)
        usable = [f for f in files if f.convertible and f.overlaps(start, end)]
        skipped_roles: dict[str, int] = {}
        for f in files:
            if f.convertible:
                continue
            if f.error:
                why = "unreadable"
            elif f.role in ("trades", "ohlcv"):
                why = "unsupported dataset"
            else:
                why = f.role   # quotes / other
            skipped_roles[why] = skipped_roles.get(why, 0) + 1
        if skipped_roles:
            res.notes.append("not converted: " + ", ".join(
                f"{k}={v}" for k, v in sorted(skipped_roles.items())))
        if not usable:
            res.notes.append("no convertible Databento files in range")
            return res

        # ── stage 1: extract (cached per raw file) ──
        stage = self.p.databento_staging
        stage.mkdir(parents=True, exist_ok=True)
        todo, staged = [], []
        for f in usable:
            key = f"databento-src:{f.path}"
            out = stage / f"{databento.file_key(Path(f.path))}.parquet"
            e = self.manifest.get(key)
            current = (e and e.get("src_size") == f.size and e.get("src_mtime") == f.mtime
                       and e.get("v") == databento.EXTRACT_VERSION
                       and (e.get("rows", 0) == 0 or out.exists())
                       and (e.get("q_rows", 0) == 0
                            or databento.quote_staging_path(out).exists())
                       and (e.get("s_rows", 0) == 0
                            or databento.settle_staging_path(out).exists()))
            if force or not current:
                todo.append((f, out))
            else:
                staged.append((f, out, e))
        n_cached = len(staged)
        done, extract_errors = self._extract_databento(todo, jobs, res)
        staged.extend(done)

        # A file that is unreadable now, or failed to extract this run, keeps
        # contributing its last good bars, so a corrupt re-download or a missing
        # package never silently drops tickers from a shared partition.
        ok_paths = {f.path for f, _, _ in staged}
        fallback = [f for f in files if f.error and f.role != "quotes"] + \
                   [f for f, _ in todo if f.path not in ok_paths]
        n_fallback = 0
        for f in fallback:
            e = self.manifest.get(f"databento-src:{f.path}")
            if e and e.get("staging") and (
                    (e.get("rows") and Path(e["staging"]).exists())
                    or (e.get("q_rows") and databento.quote_staging_path(Path(e["staging"])).exists())):
                staged.append((f, Path(e["staging"]), e))
                n_fallback += 1
        if n_fallback:
            res.notes.append(f"{n_fallback} file(s) unreadable now; kept their last good bars")

        # ── stage 2: assemble per (store, trade_date) ──
        # (stores, asset, date) -> staging files; bar and quote stores apart
        by_date: dict[tuple[str, str, str], list[Path]] = {}
        settles: dict[str, list[Path]] = {}
        for f, out, e in staged:
            for kind, rows_k, dates_k, assets_k, path in (
                    ("bars", "rows", "dates", "assets", out),
                    ("quotes", "q_rows", "q_dates", "q_assets", databento.quote_staging_path(out))):
                if not e.get(rows_k):
                    continue
                for d in e.get(dates_k, []):
                    if (start and d < start) or (end and d > end):
                        continue
                    for a in e.get(assets_k, []):
                        if a in assets:
                            by_date.setdefault((kind, a, d), []).append(path)
            # exchange settlements join the futures daily bars of their session
            if e.get("s_rows") and "future" in assets:
                for d in e.get("s_dates", []):
                    if (start and d < start) or (end and d > end):
                        continue
                    settles.setdefault(d, []).append(databento.settle_staging_path(out))
        for d, paths in settles.items():
            if ("bars", "future", d) in by_date:
                by_date[("bars", "future", d)] += paths
        written = 0
        assembled: set[str] = set()
        for (kind, asset, d), stg in sorted(by_date.items(), key=lambda kv: (kv[0][2], kv[0][0], kv[0][1])):
            stores = (databento.STORES_FOR_ASSET if kind == "bars"
                      else databento.QUOTE_STORES_FOR_ASSET)[asset]
            iv = databento.check_interval((quote_interval or default_quote_intervals()).get(asset, 1)) \
                if kind == "quotes" else 1
            sql_fn = (databento.assembly_sql if kind == "bars"
                      else (lambda st, sg, dd, sb, _iv=iv: databento.quote_sql(st, sg, dd, sb, interval=_iv)))
            for store in stores:
                inputs = stg if store == "future_daily" else [p for p in stg if not databento.is_settle_staging(p)]
                if not inputs:
                    continue
                part_dir = self.p.partition(store, d)
                sibs = databento.sibling_parts(part_dir)
                fp = databento.fingerprint([*inputs, *sibs]) + (f"|q{iv}m" if iv != 1 else "")
                mkey = f"databento:{store}/{d}"
                assembled.add(mkey)
                if not force and self.manifest.fp_current(mkey, fp):
                    res.skipped += 1
                    continue
                target = part_dir / databento.PART_NAME
                rows = copy_to_parquet(self.con, sql_fn(store, inputs, d, sibs), target)
                if rows == 0:
                    databento.remove_part(target)    # fully covered by another vendor
                else:
                    written += 1
                self.manifest.put(mkey, {"fp": fp, "rows": rows, "inputs": len(stg),
                                         "trade_date": d, "store": store,
                                         **({"interval_min": iv} if kind == "quotes" else {})})
                res.partitions += 1
                res.rows += rows
        res.notes.append(f"files: {len(staged) - n_cached} extracted, {n_cached} cached")
        res.notes.append(f"{written} partitions with Databento rows")

        # Raw files that disappeared leave parts with no inputs: remove them.
        # Only when every file was readable and extracted, so a missing
        # package or a transient read error never deletes good data.
        if any(f.error for f in files) or extract_errors:
            res.notes.append("stale-part cleanup skipped (unreadable or failed files)")
        else:
            removed = self._drop_stale_databento(assembled, start, end, assets, files)
            if removed:
                res.notes.append(f"{removed} stale Databento part(s) removed")
        return res

    def _drop_stale_databento(self, assembled: set[str], start, end, assets, files) -> int:
        stores = {s for a in assets for s in (*databento.STORES_FOR_ASSET[a],
                                              *databento.QUOTE_STORES_FOR_ASSET[a])}
        removed = 0
        for key, e in list(self.manifest.entries.items()):
            if not key.startswith("databento:") or key in assembled:
                continue
            d, store = e.get("trade_date"), e.get("store")
            if store not in stores or not d or (start and d < start) or (end and d > end):
                continue
            databento.remove_part(self.p.partition(store, d) / databento.PART_NAME)
            self.manifest.drop(key)
            removed += 1
        present = {f.path for f in files}
        for key, e in list(self.manifest.entries.items()):
            if key.startswith("databento-src:") and e.get("src") not in present:
                if e.get("staging"):
                    Path(e["staging"]).unlink(missing_ok=True)
                    databento.quote_staging_path(Path(e["staging"])).unlink(missing_ok=True)
                self.manifest.drop(key)
        return removed

    def _extract_databento(self, todo, jobs, res: ConvertResult) -> tuple[list, int]:
        """Run :func:`databento.extract_file` over ``todo``; record manifest rows.

        Returns ``(done, n_errors)``."""
        done = []
        if not todo:
            return done, 0
        jobs = max(1, int(jobs or os.environ.get("QFZ_DATABENTO_JOBS", 1)))
        errors = 0

        def record(f, out, r):
            rec = {"src": f.path, "src_size": f.size, "src_mtime": f.mtime,
                   "v": databento.EXTRACT_VERSION,
                   "rows": r.rows, "dates": r.dates, "assets": r.assets,
                   "q_rows": r.q_rows, "q_dates": r.q_dates, "q_assets": r.q_assets,
                   "s_rows": r.s_rows, "s_dates": r.s_dates,
                   "staging": str(out)}
            if r.dropped_symbols:
                rec["unmapped_instruments"] = r.dropped_symbols
            self.manifest.put(f"databento-src:{f.path}", rec)
            done.append((f, out, rec))

        if jobs == 1:
            for f, out in todo:
                try:
                    record(f, out, databento.extract_file(f, out))
                except Exception as e:  # noqa: BLE001 - one bad file must not stop the run
                    errors += 1
                    if errors <= 5:
                        res.notes.append(f"extract failed {Path(f.path).name}: {e}")
        else:
            with ProcessPoolExecutor(max_workers=jobs) as ex:
                futs = {ex.submit(databento.extract_file, f.to_dict(), str(out), 1): (f, out)
                        for f, out in todo}
                for fut in as_completed(futs):
                    f, out = futs[fut]
                    try:
                        record(f, out, fut.result())
                    except Exception as e:  # noqa: BLE001
                        errors += 1
                        if errors <= 5:
                            res.notes.append(f"extract failed {Path(f.path).name}: {e}")
        if errors:
            res.notes.append(f"{errors} file(s) failed to extract")
        self.manifest.save()   # checkpoint: extraction is the expensive part
        return done, errors

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
