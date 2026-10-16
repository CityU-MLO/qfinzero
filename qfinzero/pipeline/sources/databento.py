"""Databento source reader (DBN files or Databento-format parquet), read in place.

Layout-agnostic: every ``*.dbn``, ``*.dbn.zst`` and ``*.parquet`` file under
``RAW_DATABENTO_DIR`` is identified from its own contents (DBN header: dataset,
schema, time range and symbology; parquet: ``rtype`` + ``symbol`` columns), so
the files written by ``qfz-data acquire databento``, Databento batch downloads
and hand-arranged folders all work.

What converts into the UPQ bar stores:

=====================================  =======================================
schema                                 becomes
=====================================  =======================================
``ohlcv-1m`` / ``ohlcv-1s``            minute bars (1s re-aggregated) + daily
``ohlcv-1h``                           daily only
``ohlcv-1d`` / ``ohlcv-eod``           daily only
``trades`` ``tbbo`` ``tcbbo``          trade records -> minute bars + daily
``mbp-1`` ``mbp-10`` ``mbo``           trade records (``action == 'T'``) ->
``cmbp-1``                             minute bars + daily
=====================================  =======================================

Quote-only schemas (``bbo-*``, ``cbbo-*``) and reference schemas (definition,
statistics, status, imbalance) are indexed but not converted: UPQ has no quote
store. In MBO data only ``T`` records are counted; ``F`` fills are the passive
side of the same execution and would double count.

Asset class: ``OPRA.*`` datasets (or OSI-style symbols in parquet) become
options; US equity datasets become stocks; anything else (futures, ...) is
skipped. Option symbols are rewritten from OSI (``SPY   250117C00500000``) to the
UPQ/massive form (``O:SPY250117C00500000``).

Conversion is two-stage so re-runs are incremental:

1. :func:`extract_file` turns one raw file into a small *staging* parquet of
   minute/daily bars (cached per source file, keyed on size + mtime).
2. ``Converter.convert_databento`` assembles, per store and trade date, the
   staging bars into ``part-databento-0000.parquet`` beside any other vendor's
   part file, picking one source per ticker and never duplicating a ticker
   another vendor already wrote for that date (*fill* precedence).

A *source* is a (dataset, schema) pair, not a file: Databento cuts files on UTC
days, so one ET session's after-hours (19:00-20:00 ET) arrive in the next
day's file. All files of the chosen source are unioned and a bar repeated by
overlapping downloads is kept once.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from ..engine import _lit

# ── constants ────────────────────────────────────────────────────────────

SUFFIXES = (".dbn.zst", ".dbn", ".parquet")
PART_NAME = "part-databento-0000.parquet"
INDEX_FILE = "databento_index.json"   # under <storage>/_state/
INDEX_VERSION = 1
# Bump when extraction output changes so cached staging bars are rebuilt.
EXTRACT_VERSION = 2

UNDEF_PRICE = 9223372036854775807     # i64::MAX, Databento's "no price"
UNDEF_TS = 18446744073709551615       # u64::MAX, Databento's "no timestamp"
# Fixed-point prices are divided (not multiplied by 1e-9) so 56650000000 -> 56.65
# exactly, matching the decimal prices other vendors store.
PRICE_DIVISOR = 1e9
NS_PER_MIN = 60_000_000_000
NS_PER_DAY = 86_400_000_000_000

# schema -> how it converts
TRADE_SCHEMAS = {"trades", "tbbo", "tcbbo", "mbp-1", "mbp-10", "mbo", "cmbp-1"}
OHLCV_KIND = {          # staging "kind" per OHLCV schema
    "ohlcv-1s": "s",    # re-aggregated to minutes
    "ohlcv-1m": "m",
    "ohlcv-1h": "h",    # daily only
    "ohlcv-1d": "d",
    "ohlcv-eod": "e",
}
QUOTE_SCHEMAS = {"bbo-1s", "bbo-1m", "cbbo-1s", "cbbo-1m"}

# DBN rtype -> schema (for parquet files, which carry rtype but no header).
# tbbo shares rtype 1 with mbp-1; both are filtered on action == 'T'.
RTYPE_SCHEMA = {
    0x00: "trades", 0x01: "mbp-1", 0x0A: "mbp-10",
    0x20: "ohlcv-1s", 0x21: "ohlcv-1m", 0x22: "ohlcv-1h", 0x23: "ohlcv-1d",
    0x24: "ohlcv-eod", 0xA0: "mbo", 0xB1: "cmbp-1", 0xC0: "cbbo-1s",
    0xC1: "cbbo-1m", 0xC2: "tcbbo", 0xC3: "bbo-1s", 0xC4: "bbo-1m",
}

# US equity datasets (venue or consolidated). Everything else that is not
# OPRA is skipped (futures / non-US venues have no UPQ store).
EQUITY_DATASET_PREFIXES = (
    "XNAS", "XNYS", "XBOS", "XPSX", "XCHI", "XCIS", "XASE", "ARCX", "IEXG",
    "BATS", "BATY", "EDGA", "EDGX", "MEMX", "EPRL", "DBEQ", "EQUS", "XNDQ",
    "FINN", "FINY", "FINC", "LTSE",
)
CONSOLIDATED_PREFIXES = ("EQUS", "DBEQ", "OPRA")

# OSI option symbol: 6-char padded root, YYMMDD, C/P, strike * 1000 (8 digits).
OSI_RE = r"^[A-Z0-9 .]{6}[0-9]{6}[CP][0-9]{8}$"
_DATASET_DIR_RE = re.compile(r"^[A-Z]{4}\.[A-Z0-9_]+$")
_ET = "America/New_York"

# staging columns (one row per bar); written per source file
STAGING_COLUMNS = (
    "asset", "ticker", "kind", "trade_date", "window_start", "et_min",
    "open", "high", "low", "close", "volume", "transactions", "drank", "src",
)


def dataset_rank(dataset: str | None) -> int:
    """2 for consolidated feeds (EQUS/DBEQ/OPRA), 1 for a single venue."""
    if dataset and dataset.upper().startswith(CONSOLIDATED_PREFIXES):
        return 2
    return 1


def asset_for_dataset(dataset: str | None) -> Optional[str]:
    """``option`` / ``stock`` / ``None`` (unsupported) for a Databento dataset."""
    if not dataset:
        return None
    ds = dataset.upper()
    if ds.startswith("OPRA"):
        return "option"
    if ds.startswith(EQUITY_DATASET_PREFIXES):
        return "stock"
    return None


def schema_role(schema: str | None) -> str:
    """``trades`` | ``ohlcv`` | ``quotes`` | ``other`` for a schema name."""
    if schema in TRADE_SCHEMAS:
        return "trades"
    if schema in OHLCV_KIND:
        return "ohlcv"
    if schema in QUOTE_SCHEMAS:
        return "quotes"
    return "other"


def is_raw_file(p: Path) -> bool:
    name = p.name
    return p.is_file() and not name.startswith((".", "_")) and name.endswith(SUFFIXES)


def source_id(info: "FileInfo") -> str:
    """Bars from files sharing a source id are unioned (see module doc)."""
    return f"{info.dataset or 'parquet'}:{info.schema}"


def file_key(path: Path) -> str:
    """Stable id for a raw file (names its staging parquet)."""
    return hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:20]


def _et_date(ns: int) -> str:
    """ET calendar date of a UTC-ns timestamp."""
    from zoneinfo import ZoneInfo
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).astimezone(ZoneInfo(_ET)).date().isoformat()


# ── file index (header-only, cached) ─────────────────────────────────────

@dataclass
class FileInfo:
    path: str
    size: int
    mtime: int
    fmt: str                      # dbn | parquet
    dataset: Optional[str] = None
    schema: Optional[str] = None
    asset: Optional[str] = None   # stock | option | None
    role: str = "other"           # trades | ohlcv | quotes | other
    start: Optional[str] = None   # first ET date covered (YYYY-MM-DD)
    end: Optional[str] = None     # last ET date covered
    symbols: list[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def convertible(self) -> bool:
        return self.error is None and self.role in ("trades", "ohlcv") and (
            self.asset is not None or self.fmt == "parquet")

    def overlaps(self, start: str | None, end: str | None) -> bool:
        if start and self.end and self.end < start:
            return False
        if end and self.start and self.start > end:
            return False
        return True

    def to_dict(self) -> dict:
        return asdict(self)


def _dataset_from_path(path: Path) -> Optional[str]:
    for part in path.parts:
        if _DATASET_DIR_RE.match(part):
            return part
    return None


def _describe_dbn(path: Path) -> FileInfo:
    st = path.stat()
    info = FileInfo(str(path), st.st_size, int(st.st_mtime), "dbn")
    try:
        import databento as db
    except ImportError:
        info.error = "databento package not installed (pip install 'qfinzero[databento]')"
        return info
    try:
        md = db.DBNStore.from_file(path).metadata
        info.dataset = str(md.dataset)
        info.schema = str(md.schema) if md.schema is not None else None
        info.asset = asset_for_dataset(info.dataset)
        info.role = schema_role(info.schema)
        if md.start is not None:
            info.start = _et_date(int(md.start))
            end = md.end
            if end is not None and int(end) not in (0, UNDEF_TS) and int(end) > int(md.start):
                info.end = _et_date(int(end) - 1)
            else:
                info.end = info.start
        info.symbols = [str(s) for s in (md.symbols or [])][:20]
    except Exception as e:  # noqa: BLE001 - a corrupt file must not break the scan
        info.error = f"{type(e).__name__}: {e}"
    return info


def _parquet_columns(con, path: Path) -> dict[str, str]:
    rows = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{_lit(path)}')").fetchall()
    return {r[0]: str(r[1]).upper() for r in rows}


def _ts_ns_expr(col: str, ctype: str) -> str:
    if "TIMESTAMP" in ctype:
        return f"epoch_ns({col})"
    return f"CAST({col} AS BIGINT)"


def _describe_parquet(path: Path, con) -> FileInfo:
    st = path.stat()
    info = FileInfo(str(path), st.st_size, int(st.st_mtime), "parquet")
    try:
        cols = _parquet_columns(con, path)
        if not {"rtype", "ts_event", "symbol"} <= set(cols):
            info.error = "not a Databento parquet export (needs rtype, ts_event, symbol)"
            return info
        ts = _ts_ns_expr("ts_event", cols["ts_event"])
        lo, hi, rtype, sym = con.execute(
            f"SELECT min({ts}), max({ts}), first(rtype), first(symbol) "
            f"FROM read_parquet('{_lit(path)}')"
        ).fetchone()
        info.schema = RTYPE_SCHEMA.get(int(rtype)) if rtype is not None else None
        info.role = schema_role(info.schema)
        info.dataset = _dataset_from_path(path)
        if info.dataset:
            info.asset = asset_for_dataset(info.dataset)
        elif sym is not None:
            info.asset = "option" if re.match(OSI_RE, str(sym)) else "stock"
        if lo is not None:
            info.start, info.end = _et_date(int(lo)), _et_date(int(hi))
        if sym is not None:
            info.symbols = [str(sym)]
    except Exception as e:  # noqa: BLE001
        info.error = f"{type(e).__name__}: {e}"
    return info


def describe(path: Path, con=None) -> FileInfo:
    """Identify one raw file from its contents (header / columns)."""
    if path.name.endswith(".parquet"):
        own = con is None
        if own:
            from ..engine import connect
            con = connect()
        try:
            return _describe_parquet(path, con)
        finally:
            if own:
                con.close()
    return _describe_dbn(path)


def list_raw_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    out = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        # skip private/temp dirs (e.g. Databento ``_tmp`` batch scratch)
        dirnames[:] = sorted(d for d in dirnames if not d.startswith((".", "_")))
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            if is_raw_file(p):
                out.append(p)
    return out


def index(root: Path, state_dir: Path | None = None, con=None) -> list[FileInfo]:
    """Describe every raw file under ``root``; cache keyed on (size, mtime).

    The cache lives at ``<state_dir>/databento_index.json`` so a repeat scan only
    ``stat``s files. Cache I/O is best-effort (a read-only store still works).
    """
    cache: dict[str, dict] = {}
    cache_path = (state_dir / INDEX_FILE) if state_dir else None
    if cache_path and cache_path.exists():
        try:
            blob = json.loads(cache_path.read_text())
            if blob.get("version") == INDEX_VERSION:
                cache = blob.get("files", {})
        except (OSError, json.JSONDecodeError):
            cache = {}

    out: list[FileInfo] = []
    fresh: dict[str, dict] = {}
    changed = False
    for p in list_raw_files(root):
        try:
            st = p.stat()
        except OSError:
            continue
        hit = cache.get(str(p))
        if hit and hit.get("size") == st.st_size and hit.get("mtime") == int(st.st_mtime) \
                and not (hit.get("error") or "").startswith("databento package not installed"):
            info = FileInfo(**hit)
        else:
            info = describe(p, con)
            changed = True
        out.append(info)
        fresh[str(p)] = info.to_dict()
    if cache_path and (changed or set(fresh) != set(cache)):
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"version": INDEX_VERSION, "files": fresh}))
            os.replace(tmp, cache_path)
        except OSError:
            pass
    return out


def summarize(files: Iterable[FileInfo], root: Path) -> dict:
    """Registry view: totals + per (dataset, schema) date ranges."""
    files = list(files)
    groups: dict[tuple, dict] = {}
    conv = [f for f in files if f.convertible]
    for f in files:
        k = (f.dataset or ("parquet" if f.fmt == "parquet" else "?"), f.schema or "?")
        g = groups.setdefault(k, {
            "dataset": k[0], "schema": k[1], "asset": f.asset, "role": f.role,
            "files": 0, "convertible": f.convertible, "start": None, "end": None,
            "errors": 0,
        })
        g["files"] += 1
        if f.error:
            g["errors"] += 1
            g["convertible"] = False
        if f.start and (g["start"] is None or f.start < g["start"]):
            g["start"] = f.start
        if f.end and (g["end"] is None or f.end > g["end"]):
            g["end"] = f.end
    out = {
        "root": str(root),
        "present": bool(files),
        "files": len(files),
        "convertible_files": len(conv),
        "groups": sorted(groups.values(), key=lambda g: (g["dataset"], g["schema"])),
    }
    starts = [f.start for f in conv if f.start]
    ends = [f.end for f in conv if f.end]
    if starts:
        out["start"], out["end"] = min(starts), max(ends)
    errs = [f.error for f in files if f.error]
    if errs:
        out["first_error"] = errs[0]
    return out


# ── extraction: one raw file -> staging bars ─────────────────────────────

# Final bar aggregation over partial bars (see _partial_sql). ``first_rn`` /
# ``last_rn`` are the file-order positions of a bar's first/last trade, so a bar
# split across ndarray chunks still gets the right open/close.
_FINAL_MINUTE_SQL = """
    SELECT key, ws,
           arg_min(o, first_rn) AS open, max(h) AS high, min(l) AS low,
           arg_max(c, last_rn) AS close,
           CAST(sum(v) AS BIGINT) AS volume, CAST(sum(n) AS BIGINT) AS transactions
    FROM {src} GROUP BY key, ws
"""

_PARTIAL_SQL = """
    SELECT key, ts - ts % {bucket} AS ws,
           min(rn) AS first_rn, max(rn) AS last_rn,
           arg_min(px, rn) AS o, max(px) AS h, min(px) AS l, arg_max(px, rn) AS c,
           sum(sz) AS v, count(*) AS n
    FROM {src} GROUP BY key, ws
"""


def _ticker_sql(sym_col: str, asset_col: str) -> str:
    """Normalize a raw Databento symbol into the UPQ ticker for its asset."""
    return f"""CASE
        WHEN {asset_col} = 'option' THEN
            CASE WHEN regexp_matches({sym_col}, '{OSI_RE}')
                 THEN 'O:' || replace(trim(substr({sym_col}, 1, 6)), ' ', '') || substr({sym_col}, 7)
            END
        ELSE nullif(replace(trim({sym_col}), ' ', '.'), '')
    END"""


def _bars_to_staging_sql(src: str, kind_col: str, drank: int, src_id: str) -> str:
    """``src`` has (asset, sym, kind, ws, open..transactions) -> staging columns."""
    et = f"timezone('{_ET}', to_timestamp(ws // 1000000000))"
    return f"""
        SELECT asset,
               {_ticker_sql('sym', 'asset')} AS ticker,
               {kind_col} AS kind,
               CASE WHEN {kind_col} IN ('d', 'e')
                    THEN DATE '1970-01-01' + CAST(ws // {NS_PER_DAY} AS INTEGER)
                    ELSE CAST({et} AS DATE) END AS trade_date,
               CAST(ws AS BIGINT) AS window_start,
               CASE WHEN {kind_col} = 'm'
                    THEN CAST(date_part('hour', {et}) * 60 + date_part('minute', {et}) AS INTEGER)
                    END AS et_min,
               CAST(open AS DOUBLE) AS open, CAST(high AS DOUBLE) AS high,
               CAST(low AS DOUBLE) AS low, CAST(close AS DOUBLE) AS close,
               CAST(volume AS BIGINT) AS volume,
               CAST(transactions AS BIGINT) AS transactions,
               {int(drank)} AS drank,
               '{src_id}' AS src
        FROM {src}
    """


@dataclass
class ExtractResult:
    path: str
    rows: int = 0
    dates: list[str] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)
    dropped_symbols: int = 0
    note: str = ""


def _write_staging(con, select_sql: str, out: Path) -> tuple[int, list[str], list[str]]:
    out.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"CREATE OR REPLACE TEMP TABLE _stg AS SELECT * FROM ({select_sql}) "
                f"WHERE ticker IS NOT NULL AND close IS NOT NULL")
    n = con.execute("SELECT count(*) FROM _stg").fetchone()[0]
    tmp = out.with_suffix(".parquet.tmp")
    con.execute(f"COPY (SELECT {', '.join(STAGING_COLUMNS)} FROM _stg "
                f"ORDER BY asset, trade_date, ticker, window_start) "
                f"TO '{_lit(tmp)}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    os.replace(tmp, out)
    dates = [r[0] for r in con.execute(
        "SELECT DISTINCT strftime(trade_date, '%Y-%m-%d') FROM _stg ORDER BY 1").fetchall()]
    assets = [r[0] for r in con.execute("SELECT DISTINCT asset FROM _stg ORDER BY 1").fetchall()]
    con.execute("DROP TABLE _stg")
    return int(n), dates, assets


def _arrow_table(cur):
    """Result as a ``pyarrow.Table`` (DuckDB >= 1.4 returns a reader from ``arrow()``)."""
    out = cur.arrow()
    return out.read_all() if hasattr(out, "read_all") else out


def _extract_dbn(info: FileInfo, out: Path, con, chunk: int) -> ExtractResult:
    import databento as db
    import numpy as np
    import pyarrow as pa
    from databento.common.symbology import InstrumentMap

    res = ExtractResult(info.path)
    store = db.DBNStore.from_file(info.path)
    md = store.metadata
    asset = info.asset
    schema = info.schema
    src_id = source_id(info)
    drank = dataset_rank(info.dataset)

    partials: list[pa.Table] = []
    offset = 0
    if schema_role(schema) == "trades":
        bucket = NS_PER_MIN
        for arr in store.to_ndarray(count=chunk):
            if len(arr) == 0:
                continue
            names = arr.dtype.names
            mask = (arr["price"] != UNDEF_PRICE) & (arr["size"] > 0) & (arr["ts_event"] < UNDEF_TS)
            if "action" in names:
                mask &= arr["action"] == b"T"
            idx = np.nonzero(mask)[0]
            if len(idx):
                sel = arr[idx]
                tbl = pa.table({
                    "key": sel["instrument_id"].astype(np.int64),
                    "ts": sel["ts_event"].astype(np.int64),
                    "px": sel["price"].astype(np.float64) / PRICE_DIVISOR,
                    "sz": sel["size"].astype(np.int64),
                    "rn": (idx + offset).astype(np.int64),
                })
                con.register("_chunk", tbl)
                partials.append(_arrow_table(con.execute(
                    _PARTIAL_SQL.format(src="_chunk", bucket=bucket))))
                con.unregister("_chunk")
            offset += len(arr)
        kind = "m"
    else:
        kind = OHLCV_KIND[schema]
        for arr in store.to_ndarray(count=chunk):
            if len(arr) == 0:
                continue
            ok = (arr["close"] != UNDEF_PRICE) & (arr["ts_event"] < UNDEF_TS)
            sel = arr[ok]
            n = len(sel)
            pos = np.arange(offset, offset + len(arr), dtype=np.int64)[ok]
            px = lambda f: sel[f].astype(np.float64) / PRICE_DIVISOR  # noqa: E731
            partials.append(pa.table({
                "key": sel["instrument_id"].astype(np.int64),
                "ws": sel["ts_event"].astype(np.int64),
                "first_rn": pos, "last_rn": pos,
                "o": px("open"), "h": px("high"), "l": px("low"), "c": px("close"),
                "v": sel["volume"].astype(np.int64),
                "n": np.full(n, -1, dtype=np.int64),   # sentinel -> NULL transactions
            }))
            offset += len(arr)
        # 1s bars are re-bucketed to minutes below; other OHLCV kinds pass through
        bucket = NS_PER_MIN if kind == "s" else None
        if kind == "s":
            kind = "m"

    if not partials:
        res.note = "no trade/bar records"
        out.unlink(missing_ok=True)
        return res

    allp = pa.concat_tables(partials)
    con.register("_partials", allp)
    if bucket is not None and (schema_role(schema) == "trades" or schema == "ohlcv-1s"):
        if schema == "ohlcv-1s":
            con.execute("CREATE OR REPLACE TEMP VIEW _p AS SELECT key, ws - ws % "
                        f"{NS_PER_MIN} AS ws, first_rn, last_rn, o, h, l, c, v, n FROM _partials")
            src = "_p"
        else:
            src = "_partials"
        con.execute(f"CREATE OR REPLACE TEMP TABLE _bars AS {_FINAL_MINUTE_SQL.format(src=src)}")
        if schema == "ohlcv-1s":
            con.execute("UPDATE _bars SET transactions = NULL")
    else:
        con.execute("CREATE OR REPLACE TEMP TABLE _bars AS SELECT key, ws, o AS open, h AS high, "
                    "l AS low, c AS close, v AS volume, NULL::BIGINT AS transactions FROM _partials")
    con.unregister("_partials")

    # instrument_id -> raw symbol, resolved per UTC date (OPRA ids are reused)
    pairs = con.execute(
        f"SELECT DISTINCT key, ws // {NS_PER_DAY} FROM _bars").fetchall()
    imap = InstrumentMap()
    try:
        imap.insert_metadata(md)
    except Exception:  # noqa: BLE001 - files without mappings fall through below
        pass
    single = None
    if md.symbols and len(md.symbols) == 1 and len({k for k, _ in pairs}) == 1:
        single = str(md.symbols[0])
    epoch = date(1970, 1, 1)
    keys, days, syms = [], [], []
    for key, day in pairs:
        sym = None
        try:
            sym = imap.resolve(int(key), epoch + timedelta(days=int(day)))
        except Exception:  # noqa: BLE001 - empty map
            sym = None
        if sym is None:
            sym = single
        if sym is None:
            res.dropped_symbols += 1
            continue
        keys.append(int(key)); days.append(int(day)); syms.append(str(sym))
    con.register("_sym", pa.table({"key": pa.array(keys, pa.int64()),
                                   "day": pa.array(days, pa.int64()),
                                   "sym": pa.array(syms, pa.string())}))
    con.execute(f"""CREATE OR REPLACE TEMP VIEW _named AS
        SELECT '{asset}' AS asset, s.sym, b.ws, b.open, b.high, b.low, b.close,
               b.volume, b.transactions
        FROM _bars b JOIN _sym s ON s.key = b.key AND s.day = b.ws // {NS_PER_DAY}""")
    n, dates, assets = _write_staging(
        con, _bars_to_staging_sql("_named", f"'{kind}'", drank, src_id), out)
    con.execute("DROP VIEW _named")
    con.unregister("_sym")
    con.execute("DROP TABLE _bars")
    res.rows, res.dates, res.assets = n, dates, assets
    return res


def _extract_parquet(info: FileInfo, out: Path, con) -> ExtractResult:
    res = ExtractResult(info.path)
    path = Path(info.path)
    cols = _parquet_columns(con, path)
    src_id = source_id(info)
    schema = info.schema
    drank = dataset_rank(info.dataset) if info.dataset else (2 if info.asset == "option" else 1)
    ts = _ts_ns_expr("ts_event", cols["ts_event"])
    if info.dataset:
        asset_expr = f"'{info.asset}'"
    else:   # infer per row from the symbol shape
        asset_expr = f"CASE WHEN regexp_matches(symbol, '{OSI_RE}') THEN 'option' ELSE 'stock' END"

    def price(col: str) -> str:
        ctype = cols.get(col, "")
        if "INT" in ctype:
            return f"CASE WHEN {col} = {UNDEF_PRICE} THEN NULL ELSE {col} / {PRICE_DIVISOR} END"
        return f"CAST({col} AS DOUBLE)"

    rp = f"read_parquet('{_lit(path)}', file_row_number=true)"
    if schema_role(schema) == "trades":
        where = [f"{ts} IS NOT NULL", "size > 0", f"({price('price')}) IS NOT NULL",
                 "NOT isnan(" + price('price') + ")"]
        if "action" in cols and schema != "tcbbo":
            where.append("action = 'T'")
        con.execute(f"""CREATE OR REPLACE TEMP TABLE _bars AS
            SELECT {asset_expr} AS asset, CAST(symbol AS VARCHAR) AS sym,
                   ts - ts % {NS_PER_MIN} AS ws,
                   arg_min(px, file_row_number) AS open, max(px) AS high, min(px) AS low,
                   arg_max(px, file_row_number) AS close,
                   CAST(sum(size) AS BIGINT) AS volume, CAST(count(*) AS BIGINT) AS transactions
            FROM (SELECT *, {ts} AS ts, {price('price')} AS px FROM {rp}
                  WHERE {' AND '.join(where)})
            GROUP BY ALL""")
        kind = "m"
    else:
        kind = OHLCV_KIND[schema]
        bucket = NS_PER_MIN if kind == "s" else None
        ws = f"{ts} - {ts} % {bucket}" if bucket else ts
        con.execute(f"""CREATE OR REPLACE TEMP TABLE _bars AS
            SELECT {asset_expr} AS asset, CAST(symbol AS VARCHAR) AS sym, {ws} AS ws,
                   arg_min({price('open')}, file_row_number) AS open,
                   max({price('high')}) AS high, min({price('low')}) AS low,
                   arg_max({price('close')}, file_row_number) AS close,
                   CAST(sum(volume) AS BIGINT) AS volume, NULL::BIGINT AS transactions
            FROM {rp} WHERE {ts} IS NOT NULL
            GROUP BY ALL""")
        if kind == "s":
            kind = "m"
    n, dates, assets = _write_staging(
        con, _bars_to_staging_sql("_bars", f"'{kind}'", drank, src_id), out)
    con.execute("DROP TABLE _bars")
    res.rows, res.dates, res.assets = n, dates, assets
    return res


def extract_file(info: FileInfo | dict, out: Path | str, threads: int | None = None,
                 chunk: int = 2_000_000) -> ExtractResult:
    """Convert one raw file into staging bars at ``out``. Picklable entry point
    (dict in / dataclass out) so it can run in a worker process."""
    from ..engine import connect
    if isinstance(info, dict):
        info = FileInfo(**info)
    out = Path(out)
    con = connect(threads)
    try:
        if info.fmt == "parquet":
            res = _extract_parquet(info, out, con)
        else:
            res = _extract_dbn(info, out, con, chunk)
        if res.rows == 0:
            out.unlink(missing_ok=True)
        return res
    finally:
        con.close()


# ── assembly SQL: staging -> one UPQ partition ───────────────────────────

_OPRA_RE = r"^O:([A-Z]+)[0-9]{0,2}([0-9]{6})([CP])([0-9]{8})$"   # == massive._OPRA_RE


def _excluded(siblings: list[Path], col: str = "ticker") -> str:
    """Fill precedence: drop tickers another vendor wrote into this partition."""
    if not siblings:
        return ""
    lst = ", ".join(f"'{_lit(p)}'" for p in siblings)
    return f" AND ticker NOT IN (SELECT DISTINCT {col} FROM read_parquet([{lst}]))"


# One bar per (ticker, source, kind, window_start): files of one source that
# overlap in time (re-downloads, per-symbol + multi-symbol requests) repeat
# identical bars; keep the fullest copy.
_DEDUPE = """QUALIFY row_number() OVER (
                PARTITION BY ticker, window_start
                ORDER BY volume DESC, transactions DESC NULLS LAST) = 1"""
_DEDUPE_DAILY = """QUALIFY row_number() OVER (
                PARTITION BY ticker, src, kind, window_start
                ORDER BY volume DESC, transactions DESC NULLS LAST) = 1"""


def _staging_list(files: list[Path]) -> str:
    return "[" + ", ".join(f"'{_lit(p)}'" for p in files) + "]"


def minute_sql(store: str, staging: list[Path], trade_date: str, siblings: list[Path]) -> str:
    """Minute store (stock_minute / option_minute): best source per ticker."""
    asset = "stock" if store == "stock_minute" else "option"
    base = f"""
        WITH src AS (
            SELECT * FROM read_parquet({_staging_list(staging)})
            WHERE asset = '{asset}' AND kind = 'm' AND trade_date = DATE '{trade_date}'
              {_excluded(siblings)}
        ),
        rank AS (
            SELECT ticker, src, row_number() OVER (
                PARTITION BY ticker ORDER BY max(drank) DESC, sum(volume) DESC, src) AS rn
            FROM src GROUP BY ticker, src
        ),
        bars AS (
            SELECT s.* FROM src s JOIN rank r USING (ticker, src) WHERE r.rn = 1
            {_DEDUPE}
        )"""
    if asset == "stock":
        return base + f"""
        SELECT ticker, window_start, open, high, low, close, volume, transactions,
               DATE '{trade_date}' AS trade_date
        FROM bars ORDER BY ticker, window_start"""
    return base + _option_projection("bars", trade_date, "window_start")


def _option_projection(src: str, trade_date: str, ws_expr: str) -> str:
    return f"""
        SELECT ticker, ticker AS contract,
               regexp_extract(ticker, '{_OPRA_RE}', 1) AS underlying,
               strptime('20' || regexp_extract(ticker, '{_OPRA_RE}', 2), '%Y%m%d')::DATE AS expiry,
               CAST(regexp_extract(ticker, '{_OPRA_RE}', 4) AS DOUBLE) / 1000.0 AS strike,
               regexp_extract(ticker, '{_OPRA_RE}', 3) AS "right",
               CAST({ws_expr} AS BIGINT) AS window_start,
               open, high, low, close, volume, transactions,
               DATE '{trade_date}' AS trade_date
        FROM {src}
        WHERE regexp_matches(ticker, '{_OPRA_RE}')
        ORDER BY contract, window_start"""


def daily_sql(store: str, staging: list[Path], trade_date: str, siblings: list[Path]) -> str:
    """Daily store (stock_daily / option_day).

    Candidates per (ticker, source): session ``eod`` bars, bars aggregated from
    minutes, UTC ``1d`` bars, bars aggregated from hours — in that preference
    (after consolidated-over-venue). Stock bars aggregated from minutes take
    O/H/L/C from the regular session (09:30-16:00 ET) when it traded, and
    volume/transactions from the whole day, matching the massive day aggs.
    """
    asset = "stock" if store == "stock_daily" else "option"
    rth = "et_min BETWEEN 570 AND 959" if asset == "stock" else "et_min IS NOT NULL"
    return f"""
        WITH raw AS (
            SELECT * FROM read_parquet({_staging_list(staging)})
            WHERE asset = '{asset}' AND trade_date = DATE '{trade_date}'
              {_excluded(siblings)}
        ),
        src AS (SELECT * FROM raw {_DEDUPE_DAILY}),
        cand AS (
            SELECT ticker, src, max(drank) AS drank,
                   CASE kind WHEN 'e' THEN 4 WHEN 'm' THEN 3 WHEN 'd' THEN 2 ELSE 1 END AS krank,
                   coalesce(arg_min(open, window_start) FILTER (WHERE {rth}),
                            arg_min(open, window_start)) AS open,
                   coalesce(max(high) FILTER (WHERE {rth}), max(high)) AS high,
                   coalesce(min(low) FILTER (WHERE {rth}), min(low)) AS low,
                   coalesce(arg_max(close, window_start) FILTER (WHERE {rth}),
                            arg_max(close, window_start)) AS close,
                   CAST(sum(volume) AS BIGINT) AS volume,
                   CAST(sum(transactions) AS BIGINT) AS transactions
            FROM src GROUP BY ticker, src, kind
        ),
        bars AS (
            SELECT * FROM (
                SELECT *, row_number() OVER (
                    PARTITION BY ticker ORDER BY drank DESC, krank DESC, volume DESC, src) AS rn
                FROM cand) WHERE rn = 1
        )""" + (f"""
        SELECT ticker, DATE '{trade_date}' AS trade_date, open, high, low, close,
               volume, transactions
        FROM bars ORDER BY ticker""" if asset == "stock" else _option_projection(
            "bars", trade_date,
            f"epoch_ns(timezone('{_ET}', TIMESTAMP '{trade_date} 00:00:00'))"))


def assembly_sql(store: str, staging: list[Path], trade_date: str, siblings: list[Path]) -> str:
    if store in ("stock_minute", "option_minute"):
        return minute_sql(store, staging, trade_date, siblings)
    return daily_sql(store, staging, trade_date, siblings)


STORES_FOR_ASSET = {
    "stock": ("stock_daily", "stock_minute"),
    "option": ("option_day", "option_minute"),
}


def sibling_parts(partition_dir: Path) -> list[Path]:
    """Other vendors' part files in a partition (everything but ours)."""
    if not partition_dir.is_dir():
        return []
    return sorted(p for p in partition_dir.glob("*.parquet") if p.name != PART_NAME)


def fingerprint(files: Iterable[Path]) -> str:
    h = hashlib.sha1()
    for p in sorted(Path(f) for f in files):
        try:
            st = p.stat()
            h.update(f"{p}|{st.st_size}|{int(st.st_mtime_ns)}\n".encode())
        except OSError:
            h.update(f"{p}|missing\n".encode())
    return h.hexdigest()


def remove_part(part: Path) -> None:
    """Delete a Databento part, and its partition dir if nothing else is left
    (an empty ``trade_date=`` dir would still count as a partition)."""
    part.unlink(missing_ok=True)
    try:
        part.parent.rmdir()          # only succeeds when empty
    except OSError:
        pass


def refilter_part(con, partition_dir: Path) -> Optional[int]:
    """Re-apply fill precedence to an existing Databento part after another
    vendor (re)wrote its own part in the same partition. Returns rows kept, or
    ``None`` when there is no Databento part."""
    ours = partition_dir / PART_NAME
    if not ours.exists():
        return None
    sibs = sibling_parts(partition_dir)
    if not sibs:
        return None
    tmp = ours.with_suffix(".parquet.refilter")
    con.execute(
        f"COPY (SELECT * FROM read_parquet('{_lit(ours)}') WHERE TRUE{_excluded(sibs)}) "
        f"TO '{_lit(tmp)}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    n = con.execute(f"SELECT count(*) FROM read_parquet('{_lit(tmp)}')").fetchone()[0]
    if n == 0:
        tmp.unlink(missing_ok=True)
        remove_part(ours)
    else:
        os.replace(tmp, ours)
    return int(n)


# ── convenience for tests / callers ──────────────────────────────────────

def as_dict(files: Iterable[FileInfo]) -> list[dict[str, Any]]:
    return [f.to_dict() for f in files]
