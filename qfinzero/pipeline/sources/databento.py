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

Quote schemas (``bbo-*``, ``cbbo-*``, ``cmbp-1``, and ``mbp-1`` / ``mbp-10`` of a
futures venue) fill the minute quote stores; reference schemas (definition,
statistics, status, imbalance) are indexed but not converted. In MBO data only ``T`` records are counted; ``F`` fills are the passive
side of the same execution and would double count.

Asset class: ``OPRA.*`` datasets (or OSI-style symbols in parquet) become
options; US equity datasets become stocks; futures venues (``GLBX.MDP3`` = CME
Globex, ICE, Nodal) become futures; anything else is skipped. Option symbols
are rewritten from OSI (``SPY   250117C00500000``) to the UPQ/massive form
(``O:SPY250117C00500000``). Futures keep the contract symbol (``ZNZ6``); a
front-month continuous symbol (``ZN.v.0``, ``ZN.c.0``, ``ZN.n.0``) becomes the
root (``ZN``). A futures trade date is the CME session: 18:00 ET the evening
before to 17:00 ET, so bars from 18:00 ET on belong to the next date.

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

from ..engine import _lit, parquet_options

# ── constants ────────────────────────────────────────────────────────────

SUFFIXES = (".dbn.zst", ".dbn", ".parquet")
PART_NAME = "part-databento-0000.parquet"
INDEX_FILE = "databento_index.json"   # under <storage>/_state/
INDEX_VERSION = 2   # 2: OCEA recognised as a US equity venue
# Bump when extraction output changes so cached staging bars are rebuilt.
EXTRACT_VERSION = 5   # 3: quote staging (<key>.q.parquet); 4: futures; 5: instrument ids, settlements

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
# Schemas whose records carry a top-of-book (bid/ask) -> quote stores, with a
# preference rank: full-resolution consolidated updates beat sampled quotes.
QUOTE_CAPABLE = {"cmbp-1": 4, "cbbo-1s": 3, "bbo-1s": 3, "cbbo-1m": 2, "bbo-1m": 2}
# A futures exchange is the only venue, so its own top of book is the BBO.
FUTURE_BOOK_SCHEMAS = {"mbp-1", "mbp-10"}
# Sampled schemas stamp ts_recv at the *end* of their interval.
SAMPLED_QUOTES = {"cbbo-1s", "bbo-1s", "cbbo-1m", "bbo-1m"}

# DBN rtype -> schema (for parquet files, which carry rtype but no header).
# tbbo shares rtype 1 with mbp-1; both are filtered on action == 'T'.
RTYPE_SCHEMA = {
    0x00: "trades", 0x01: "mbp-1", 0x0A: "mbp-10",
    0x20: "ohlcv-1s", 0x21: "ohlcv-1m", 0x22: "ohlcv-1h", 0x23: "ohlcv-1d",
    0x24: "ohlcv-eod", 0xA0: "mbo", 0xB1: "cmbp-1", 0xC0: "cbbo-1s",
    0xC1: "cbbo-1m", 0xC2: "tcbbo", 0xC3: "bbo-1s", 0xC4: "bbo-1m",
}

# US equity datasets (venue or consolidated). Datasets that are neither these,
# OPRA nor a futures venue (non-US equities, ...) are skipped.
EQUITY_DATASET_PREFIXES = (
    "XNAS", "XNYS", "XBOS", "XPSX", "XCHI", "XCIS", "XASE", "ARCX", "IEXG",
    "BATS", "BATY", "EDGA", "EDGX", "MEMX", "EPRL", "DBEQ", "EQUS", "XNDQ",
    "FINN", "FINY", "FINC", "LTSE",
    "OCEA",     # Blue Ocean ATS: the 20:00-04:00 ET overnight session
)
CONSOLIDATED_PREFIXES = ("EQUS", "DBEQ", "OPRA")
# Futures venues: CME Globex (CME, CBOT, NYMEX, COMEX), ICE US / Europe, Nodal.
FUTURES_DATASET_PREFIXES = ("GLBX", "IFUS", "IFEU", "IFLL", "NDEX")
# A futures session opens at 18:00 ET: shift by 6 h to get its trade date.
FUTURE_SESSION_SHIFT_NS = 6 * 3_600_000_000_000

# OSI option symbol: 6-char padded root, YYMMDD, C/P, strike * 1000 (8 digits).
OSI_RE = r"^[A-Z0-9 .]{6}[0-9]{6}[CP][0-9]{8}$"
_DATASET_DIR_RE = re.compile(r"^[A-Z]{4}\.[A-Z0-9_]+$")
_ET = "America/New_York"

# staging columns (one row per bar); written per source file
STAGING_COLUMNS = (
    "asset", "ticker", "kind", "trade_date", "window_start", "et_min",
    "open", "high", "low", "close", "volume", "transactions", "drank", "src", "iid",
)
# exchange settlement prices of futures (statistics schema) -> <key>.s.parquet
SETTLE_STAGING_COLUMNS = ("ticker", "trade_date", "settle", "final", "ts")


def dataset_rank(dataset: str | None) -> int:
    """2 for consolidated feeds (EQUS/DBEQ/OPRA), 1 for a single venue."""
    if dataset and dataset.upper().startswith(CONSOLIDATED_PREFIXES):
        return 2
    return 1


def asset_for_dataset(dataset: str | None) -> Optional[str]:
    """``option`` / ``stock`` / ``future`` / ``None`` (unsupported) for a dataset."""
    if not dataset:
        return None
    ds = dataset.upper()
    if ds.startswith("OPRA"):
        return "option"
    if ds.startswith(FUTURES_DATASET_PREFIXES):
        return "future"
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
    def has_bars(self) -> bool:
        return self.role in ("trades", "ohlcv")

    @property
    def has_quotes(self) -> bool:
        return self.schema in QUOTE_CAPABLE or (
            self.asset == "future" and self.schema in FUTURE_BOOK_SCHEMAS)

    @property
    def has_settlements(self) -> bool:
        return self.asset == "future" and self.schema == "statistics" and self.fmt == "dbn"

    @property
    def convertible(self) -> bool:
        return self.error is None and (self.has_bars or self.has_quotes or self.has_settlements) and (
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
        WHEN {asset_col} = 'future' THEN
            CASE WHEN regexp_matches(trim({sym_col}), '^[A-Z0-9]+\\.[cnv]\\.0$')
                     THEN split_part(trim({sym_col}), '.', 1)
                 -- outrights only: calendar spreads (ZNZ6-ZNH7) and UDS (UD:...) are dropped
                 WHEN regexp_matches(trim({sym_col}), '^[A-Z0-9]+(\\.[cnv]\\.[0-9]+)?$')
                     THEN trim({sym_col})
            END
        ELSE nullif(replace(trim({sym_col}), ' ', '.'), '')
    END"""


def _et_shifted(ns_col: str) -> str:
    """ET wall time of a futures timestamp shifted into its session's date."""
    return (f"timezone('{_ET}', to_timestamp(({ns_col} + {FUTURE_SESSION_SHIFT_NS}) "
            f"// 1000000000))")


def _bars_to_staging_sql(src: str, kind_col: str, drank: int, src_id: str) -> str:
    """``src`` has (asset, sym, kind, ws, open..transactions) -> staging columns."""
    et = f"timezone('{_ET}', to_timestamp(ws // 1000000000))"
    return f"""
        SELECT asset,
               {_ticker_sql('sym', 'asset')} AS ticker,
               {kind_col} AS kind,
               CASE WHEN {kind_col} IN ('d', 'e')
                    THEN DATE '1970-01-01' + CAST(ws // {NS_PER_DAY} AS INTEGER)
                    WHEN asset = 'future' THEN CAST({_et_shifted('ws')} AS DATE)
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
               '{src_id}' AS src,
               CAST(iid AS BIGINT) AS iid
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
    q_rows: int = 0                                      # quote staging
    q_dates: list[str] = field(default_factory=list)
    q_assets: list[str] = field(default_factory=list)
    s_rows: int = 0                                      # settlement staging
    s_dates: list[str] = field(default_factory=list)


def quote_staging_path(out: Path) -> Path:
    """Quote staging file next to a bar staging file (``<key>.q.parquet``)."""
    return out.with_name(out.stem + ".q.parquet")


def settle_staging_path(out: Path) -> Path:
    """Settlement staging file next to a bar staging file (``<key>.s.parquet``)."""
    return out.with_name(out.stem + ".s.parquet")


def is_settle_staging(p: Path) -> bool:
    return Path(p).name.endswith(".s.parquet")


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


def _register_symbols(con, table: str, md) -> int:
    """Register ``_sym(key, day, sym)`` mapping instrument ids in ``table``
    (columns ``key``, ``ws``) to raw symbols, resolved per UTC date because
    OPRA reuses ids. Returns how many (id, day) pairs could not be mapped."""
    import pyarrow as pa
    from databento.common.symbology import InstrumentMap

    pairs = con.execute(f"SELECT DISTINCT key, ws // {NS_PER_DAY} FROM {table}").fetchall()
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
    dropped = 0
    for key, day in pairs:
        try:
            sym = imap.resolve(int(key), epoch + timedelta(days=int(day)))
        except Exception:  # noqa: BLE001 - empty map
            sym = None
        sym = sym if sym is not None else single
        if sym is None:
            dropped += 1
            continue
        keys.append(int(key)); days.append(int(day)); syms.append(str(sym))
    con.register("_sym", pa.table({"key": pa.array(keys, pa.int64()),
                                   "day": pa.array(days, pa.int64()),
                                   "sym": pa.array(syms, pa.string())}))
    return dropped


def _extract_dbn(info: FileInfo, out: Path, con, chunk: int) -> ExtractResult:
    import databento as db
    import numpy as np
    import pyarrow as pa

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

    res.dropped_symbols += _register_symbols(con, "_bars", md)
    con.execute(f"""CREATE OR REPLACE TEMP VIEW _named AS
        SELECT '{asset}' AS asset, s.sym, b.ws, b.open, b.high, b.low, b.close,
               b.volume, b.transactions, b.key AS iid
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
    iid = "CAST(instrument_id AS BIGINT)" if "instrument_id" in cols else "NULL::BIGINT"

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
            SELECT {asset_expr} AS asset, CAST(symbol AS VARCHAR) AS sym, {iid} AS iid,
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
            SELECT {asset_expr} AS asset, CAST(symbol AS VARCHAR) AS sym, {iid} AS iid, {ws} AS ws,
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


# ── quotes: top of book sampled at the end of each minute ────────────────

QUOTE_STAGING_COLUMNS = (
    "asset", "ticker", "trade_date", "window_start", "bid_price", "ask_price",
    "bid_size", "ask_size", "last_ts", "drank", "srank", "src",
)

# Per chunk: the last book state in each (instrument, minute), by file order.
_QUOTE_PARTIAL_SQL = """
    SELECT key, ws, max(rn) AS last_rn, max(ts) AS last_ts,
           arg_max(bid, rn) AS bid, arg_max(ask, rn) AS ask,
           arg_max(bsz, rn) AS bsz, arg_max(asz, rn) AS asz
    FROM {src} GROUP BY key, ws
"""
_QUOTE_FINAL_SQL = """
    SELECT key, ws, max(last_ts) AS last_ts,
           arg_max(bid, last_rn) AS bid, arg_max(ask, last_rn) AS ask,
           arg_max(bsz, last_rn) AS bsz, arg_max(asz, last_rn) AS asz
    FROM {src} GROUP BY key, ws
"""


def _write_quote_staging(con, src: str, info: FileInfo, out: Path) -> tuple[int, list[str], list[str]]:
    """``src`` has (asset, sym, ws, last_ts, bid, ask, bsz, asz) -> quote staging."""
    srank = QUOTE_CAPABLE.get(info.schema or "", 1)
    drank = dataset_rank(info.dataset) if info.dataset else (2 if info.asset == "option" else 1)
    et = f"timezone('{_ET}', to_timestamp(ws // 1000000000))"
    out.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE _qstg AS
        SELECT asset, {_ticker_sql('sym', 'asset')} AS ticker,
               CASE WHEN asset = 'future' THEN CAST({_et_shifted('ws')} AS DATE)
                    ELSE CAST({et} AS DATE) END AS trade_date,
               CAST(ws AS BIGINT) AS window_start,
               CAST(bid AS DOUBLE) AS bid_price, CAST(ask AS DOUBLE) AS ask_price,
               CAST(bsz AS BIGINT) AS bid_size, CAST(asz AS BIGINT) AS ask_size,
               CAST(last_ts AS BIGINT) AS last_ts, {int(drank)} AS drank, {int(srank)} AS srank,
               '{source_id(info)}' AS src
        FROM {src}
        WHERE (bid IS NOT NULL OR ask IS NOT NULL)""")
    con.execute("DELETE FROM _qstg WHERE ticker IS NULL")
    n = con.execute("SELECT count(*) FROM _qstg").fetchone()[0]
    if n:
        tmp = out.with_suffix(".parquet.tmp")
        con.execute(f"COPY (SELECT {', '.join(QUOTE_STAGING_COLUMNS)} FROM _qstg "
                    f"ORDER BY asset, trade_date, ticker, window_start) "
                    f"TO '{_lit(tmp)}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        os.replace(tmp, out)
    dates = [r[0] for r in con.execute(
        "SELECT DISTINCT strftime(trade_date, '%Y-%m-%d') FROM _qstg ORDER BY 1").fetchall()]
    assets = [r[0] for r in con.execute("SELECT DISTINCT asset FROM _qstg ORDER BY 1").fetchall()]
    con.execute("DROP TABLE _qstg")
    return int(n), dates, assets


def _extract_dbn_quotes(info: FileInfo, out: Path, con, chunk: int) -> tuple[int, list[str], list[str]]:
    import databento as db
    import numpy as np
    import pyarrow as pa

    store = db.DBNStore.from_file(info.path)
    lag = 1 if info.schema in SAMPLED_QUOTES else 0   # interval-end stamps -> its minute
    partials, offset = [], 0
    for arr in store.to_ndarray(count=chunk):
        if len(arr) == 0:
            continue
        ok = arr["ts_recv"] < UNDEF_TS
        idx = np.nonzero(ok)[0]
        if len(idx):
            sel = arr[idx]
            ts = sel["ts_recv"].astype(np.int64)

            def px(field_name):
                raw = sel[field_name]
                return pa.array(raw.astype(np.float64) / PRICE_DIVISOR, mask=raw == UNDEF_PRICE)

            tbl = pa.table({
                "key": sel["instrument_id"].astype(np.int64),
                "ws": ((ts - lag) // NS_PER_MIN) * NS_PER_MIN,
                "ts": ts,
                "rn": (idx + offset).astype(np.int64),
                "bid": px("bid_px_00"), "ask": px("ask_px_00"),
                "bsz": sel["bid_sz_00"].astype(np.int64), "asz": sel["ask_sz_00"].astype(np.int64),
            })
            con.register("_qchunk", tbl)
            partials.append(_arrow_table(con.execute(_QUOTE_PARTIAL_SQL.format(src="_qchunk"))))
            con.unregister("_qchunk")
        offset += len(arr)
    if not partials:
        return 0, [], []
    con.register("_qpartials", pa.concat_tables(partials))
    con.execute(f"CREATE OR REPLACE TEMP TABLE _quotes AS {_QUOTE_FINAL_SQL.format(src='_qpartials')}")
    con.unregister("_qpartials")
    _register_symbols(con, "_quotes", store.metadata)
    con.execute(f"""CREATE OR REPLACE TEMP VIEW _qnamed AS
        SELECT '{info.asset}' AS asset, s.sym, q.ws, q.last_ts, q.bid, q.ask, q.bsz, q.asz
        FROM _quotes q JOIN _sym s ON s.key = q.key AND s.day = q.ws // {NS_PER_DAY}""")
    result = _write_quote_staging(con, "_qnamed", info, out)
    con.execute("DROP VIEW _qnamed")
    con.unregister("_sym")
    con.execute("DROP TABLE _quotes")
    return result


def _extract_parquet_quotes(info: FileInfo, out: Path, con) -> tuple[int, list[str], list[str]]:
    path = Path(info.path)
    cols = _parquet_columns(con, path)
    if not {"bid_px_00", "ask_px_00"} <= set(cols):
        return 0, [], []
    ts_col = "ts_recv" if "ts_recv" in cols else "ts_event"
    ts = _ts_ns_expr(ts_col, cols[ts_col])
    lag = 1 if info.schema in SAMPLED_QUOTES else 0

    def price(col: str) -> str:
        if "INT" in cols.get(col, ""):
            return f"CASE WHEN {col} = {UNDEF_PRICE} THEN NULL ELSE {col} / {PRICE_DIVISOR} END"
        return f"CASE WHEN isnan(CAST({col} AS DOUBLE)) THEN NULL ELSE CAST({col} AS DOUBLE) END"

    asset_expr = (f"'{info.asset}'" if info.dataset else
                  f"CASE WHEN regexp_matches(symbol, '{OSI_RE}') THEN 'option' ELSE 'stock' END")
    rp = f"read_parquet('{_lit(path)}', file_row_number=true)"
    con.execute(f"""CREATE OR REPLACE TEMP TABLE _qsrc AS
        SELECT {asset_expr} AS asset, CAST(symbol AS VARCHAR) AS sym,
               (({ts}) - {lag}) // {NS_PER_MIN} * {NS_PER_MIN} AS ws,
               max({ts}) AS last_ts,
               arg_max({price('bid_px_00')}, file_row_number) AS bid,
               arg_max({price('ask_px_00')}, file_row_number) AS ask,
               arg_max(CAST(bid_sz_00 AS BIGINT), file_row_number) AS bsz,
               arg_max(CAST(ask_sz_00 AS BIGINT), file_row_number) AS asz
        FROM {rp} WHERE {ts} IS NOT NULL GROUP BY ALL""")
    result = _write_quote_staging(con, "_qsrc", info, out)
    con.execute("DROP TABLE _qsrc")
    return result


QUOTE_INTERVALS = (1, 5, 15, 30, 60)


def check_interval(minutes: int) -> int:
    m = int(minutes)
    if m not in QUOTE_INTERVALS:
        raise ValueError(f"quote interval must be one of {QUOTE_INTERVALS} minutes")
    return m


def sample_sql(src: str, minutes: int) -> str:
    """Keep the last minute row of each ``minutes`` bucket (ET-aligned: the UTC
    offset is a whole number of hours). ``minutes == 1`` keeps every row."""
    if minutes == 1:
        return f"SELECT * FROM {src}"
    bucket = minutes * NS_PER_MIN
    return (f"SELECT * FROM {src} QUALIFY row_number() OVER ("
            f"PARTITION BY ticker, window_start // {bucket} ORDER BY window_start DESC) = 1")


def quote_sql(store: str, staging: list[Path], trade_date: str, siblings: list[Path],
              interval: int = 1) -> str:
    """Quote store: one source per ticker (consolidated, then finer sampling,
    then more samples), one row per (ticker, minute) keeping the latest book;
    ``interval`` > 1 keeps only the last book of each N-minute bucket."""
    asset = STORE_ASSET[store]
    base = f"""
        WITH src AS (
            SELECT * FROM read_parquet({_staging_list(staging)})
            WHERE asset = '{asset}' AND trade_date = DATE '{trade_date}'
              {_excluded(siblings)}
        ),
        rank AS (
            SELECT ticker, src, row_number() OVER (
                PARTITION BY ticker ORDER BY max(drank) DESC, max(srank) DESC, count(*) DESC, src) AS rn
            FROM src GROUP BY ticker, src
        ),
        q1 AS (
            SELECT s.* FROM src s JOIN rank r USING (ticker, src) WHERE r.rn = 1
            QUALIFY row_number() OVER (PARTITION BY ticker, window_start ORDER BY last_ts DESC) = 1
        ),
        q AS ({sample_sql("q1", check_interval(interval))})"""
    if asset == "stock":
        return base + f"""
        SELECT ticker, window_start, bid_price, ask_price, bid_size, ask_size,
               DATE '{trade_date}' AS trade_date
        FROM q ORDER BY ticker, window_start"""
    if asset == "future":
        return base + f"""
        SELECT ticker, {FUTURE_ROOT_SQL} AS root, window_start, bid_price, ask_price,
               bid_size, ask_size, DATE '{trade_date}' AS trade_date
        FROM q ORDER BY ticker, window_start"""
    return base + f"""
        SELECT ticker, ticker AS contract,
               regexp_extract(ticker, '{_OPRA_RE}', 1) AS underlying,
               strptime('20' || regexp_extract(ticker, '{_OPRA_RE}', 2), '%Y%m%d')::DATE AS expiry,
               CAST(regexp_extract(ticker, '{_OPRA_RE}', 4) AS DOUBLE) / 1000.0 AS strike,
               regexp_extract(ticker, '{_OPRA_RE}', 3) AS "right",
               window_start, bid_price, ask_price, bid_size, ask_size,
               DATE '{trade_date}' AS trade_date
        FROM q WHERE regexp_matches(ticker, '{_OPRA_RE}')
        ORDER BY contract, window_start"""


QUOTE_STORES_FOR_ASSET = {
    "stock": ("stock_quote_minute",),
    "option": ("option_quote_minute",),
    "future": ("future_quote_minute",),
}


def _extract_dbn_settlements(info: FileInfo, out: Path, con, chunk: int) -> tuple[int, list[str]]:
    """Exchange settlement prices (``statistics`` records with stat_type
    SETTLEMENT_PRICE) per contract and session -> ``<key>.s.parquet``. The
    session is the one ``ts_ref`` (else ``ts_recv``) falls in; a final
    settlement beats a preliminary one, a later record an earlier one."""
    import databento as db
    import numpy as np
    import pyarrow as pa

    store = db.DBNStore.from_file(info.path)
    parts = []
    for arr in store.to_ndarray(count=chunk):
        if len(arr) == 0:
            continue
        ok = (arr["stat_type"] == 3) & (arr["price"] != UNDEF_PRICE)
        if "update_action" in arr.dtype.names:
            ok &= arr["update_action"] != 2          # 2 = delete
        sel = arr[ok]
        if not len(sel):
            continue
        ref = sel["ts_ref"].astype(np.uint64)
        ts = np.where(ref < UNDEF_TS, ref, sel["ts_recv"].astype(np.uint64)).astype(np.int64)
        parts.append(pa.table({
            "key": sel["instrument_id"].astype(np.int64),
            "ws": ts,
            "recv": sel["ts_recv"].astype(np.int64),
            "px": sel["price"].astype(np.float64) / PRICE_DIVISOR,
            "final": (sel["stat_flags"].astype(np.int64) & 1) == 1,
        }))
    if not parts:
        return 0, []
    con.register("_st", pa.concat_tables(parts))
    con.execute("CREATE OR REPLACE TEMP TABLE _stat AS SELECT * FROM _st")
    con.unregister("_st")
    _register_symbols(con, "_stat", store.metadata)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE _stg AS
        SELECT {_ticker_sql('s.sym', "'future'")} AS ticker,
               CAST({_et_shifted('t.ws')} AS DATE) AS trade_date,
               t.px AS settle, t.final, t.recv AS ts
        FROM _stat t JOIN _sym s ON s.key = t.key AND s.day = t.ws // {NS_PER_DAY}
        QUALIFY row_number() OVER (PARTITION BY ticker, trade_date ORDER BY final DESC, recv DESC) = 1""")
    con.execute("DELETE FROM _stg WHERE ticker IS NULL")
    n = con.execute("SELECT count(*) FROM _stg").fetchone()[0]
    if n:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".parquet.tmp")
        con.execute(f"COPY (SELECT {', '.join(SETTLE_STAGING_COLUMNS)} FROM _stg ORDER BY ticker, trade_date) "
                    f"TO '{_lit(tmp)}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        os.replace(tmp, out)
    dates = [r[0] for r in con.execute(
        "SELECT DISTINCT strftime(trade_date, '%Y-%m-%d') FROM _stg ORDER BY 1").fetchall()]
    con.execute("DROP TABLE _stg")
    con.execute("DROP TABLE _stat")
    con.unregister("_sym")
    return int(n), dates


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
        if not info.has_bars:
            res = ExtractResult(info.path)
        elif info.fmt == "parquet":
            res = _extract_parquet(info, out, con)
        else:
            res = _extract_dbn(info, out, con, chunk)
        if res.rows == 0:
            out.unlink(missing_ok=True)
        qout = quote_staging_path(out)
        if info.has_quotes:
            q = (_extract_parquet_quotes(info, qout, con) if info.fmt == "parquet"
                 else _extract_dbn_quotes(info, qout, con, chunk))
            res.q_rows, res.q_dates, res.q_assets = q
        if res.q_rows == 0:
            qout.unlink(missing_ok=True)
        sout = settle_staging_path(out)
        if info.has_settlements:
            res.s_rows, res.s_dates = _extract_dbn_settlements(info, sout, con, chunk)
        if res.s_rows == 0:
            sout.unlink(missing_ok=True)
        return res
    finally:
        con.close()


# ── assembly SQL: staging -> one UPQ partition ───────────────────────────

_OPRA_RE = r"^O:([A-Z]+)[0-9]{0,2}([0-9]{6})([CP])([0-9]{8})$"   # == massive._OPRA_RE
# Futures root: ``ZNZ6`` / ``ESZ26`` -> ``ZN`` / ``ES``; ``ZN`` and ``ZN.v.1`` -> ``ZN``.
FUTURE_ROOT_SQL = ("regexp_extract(split_part(ticker, '.', 1), "
                   "'^([A-Z0-9]+?)([FGHJKMNQUVXZ][0-9]{1,2})?$', 1)")


# Overnight segment (20:00-04:00 ET). No other vendor covers it (massive stops
# at 20:00), so overnight bars are only dropped where another vendor has the
# very same (ticker, minute); daytime bars are dropped per ticker.
NIGHT_SQL = "coalesce(et_min >= 1200 OR et_min < 240, false)"


def _sib_list(siblings: list[Path]) -> str:
    return ", ".join(f"'{_lit(p)}'" for p in siblings)


def _excluded(siblings: list[Path], col: str = "ticker") -> str:
    """Fill precedence: drop tickers another vendor wrote into this partition."""
    if not siblings:
        return ""
    return f" AND ticker NOT IN (SELECT DISTINCT {col} FROM read_parquet([{_sib_list(siblings)}]))"


def _excluded_by_segment(siblings: list[Path], night_expr: str = NIGHT_SQL,
                         alias: str = "z") -> str:
    """Minute stores: daytime rows by ticker, overnight rows by (ticker, minute)."""
    if not siblings:
        return ""
    sibs = f"read_parquet([{_sib_list(siblings)}])"
    return f""" AND CASE WHEN {night_expr}
            THEN NOT EXISTS (SELECT 1 FROM {sibs} s
                             WHERE s.ticker = {alias}.ticker AND s.window_start = {alias}.window_start)
            ELSE {alias}.ticker NOT IN (SELECT DISTINCT ticker FROM {sibs}) END"""


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


def future_minute_sql(staging: list[Path], trade_date: str, siblings: list[Path]) -> str:
    """``future_minute``: the whole session (no overnight split), best source per ticker."""
    staging = [p for p in staging if not is_settle_staging(p)]
    return f"""
        WITH src AS (
            SELECT * FROM read_parquet({_staging_list(staging)})
            WHERE asset = 'future' AND kind = 'm' AND trade_date = DATE '{trade_date}'
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
        )
        SELECT ticker, {FUTURE_ROOT_SQL} AS root, CAST(iid AS BIGINT) AS instrument_id,
               window_start, open, high, low, close,
               volume, transactions, DATE '{trade_date}' AS trade_date
        FROM bars ORDER BY ticker, window_start"""


def future_daily_sql(staging: list[Path], trade_date: str, siblings: list[Path]) -> str:
    settles = [p for p in staging if is_settle_staging(p)]
    staging = [p for p in staging if not is_settle_staging(p)]
    exch = (f"""SELECT ticker, settle FROM read_parquet({_staging_list(settles)})
                WHERE trade_date = DATE '{trade_date}'
                QUALIFY row_number() OVER (PARTITION BY ticker ORDER BY final DESC, ts DESC) = 1"""
            if settles else "SELECT NULL::VARCHAR AS ticker, NULL::DOUBLE AS settle WHERE FALSE")
    """``future_daily``: one bar per session (18:00 ET the day before to 17:00 ET).

    ``settle`` is the exchange settlement price when a ``statistics`` file gave
    one for that contract and session (``settle_source = 'exchange'``), else the
    last trade of the session (``'last'``). ``instrument_id`` is the contract a
    continuous series pointed to at the session's end. Databento cuts files
    on UTC days, so a lone file also holds the first hours of the next session;
    a session built from minutes gets a daily bar only when its US day part
    (12:00-17:00 ET) is present for that product (root) in that source.
    """
    return f"""
        WITH raw AS (
            SELECT * FROM read_parquet({_staging_list(staging)})
            WHERE asset = 'future' AND trade_date = DATE '{trade_date}'
              {_excluded(siblings)}
        ),
        src AS (SELECT * FROM raw {_DEDUPE_DAILY}),
        cand0 AS (
            SELECT ticker, src, kind, max(drank) AS drank,
                   CASE kind WHEN 'e' THEN 4 WHEN 'm' THEN 3 WHEN 'd' THEN 2 ELSE 1 END AS krank,
                   arg_min(open, window_start) AS open, max(high) AS high, min(low) AS low,
                   arg_max(close, window_start) AS close,
                   CAST(sum(volume) AS BIGINT) AS volume,
                   CAST(sum(transactions) AS BIGINT) AS transactions,
                   arg_max(iid, window_start) AS iid,
                   count(*) FILTER (WHERE et_min BETWEEN 720 AND 1019) AS day_rows
            FROM src GROUP BY ticker, src, kind
        ),
        cand AS (
            SELECT *, sum(day_rows) OVER (PARTITION BY src, kind, {FUTURE_ROOT_SQL}) AS day_part
            FROM cand0
        ),
        bars AS (
            SELECT * FROM (
                SELECT *, row_number() OVER (
                    PARTITION BY ticker ORDER BY drank DESC, krank DESC, volume DESC, src) AS rn
                FROM cand WHERE krank <> 3 OR day_part > 0) WHERE rn = 1
        )
        SELECT b.ticker, regexp_extract(split_part(b.ticker, '.', 1),
                   '^([A-Z0-9]+?)([FGHJKMNQUVXZ][0-9]{{1,2}})?$', 1) AS root,
               CAST(b.iid AS BIGINT) AS instrument_id, DATE '{trade_date}' AS trade_date,
               b.open, b.high, b.low, b.close, coalesce(x.settle, b.close) AS settle,
               CASE WHEN x.settle IS NULL THEN 'last' ELSE 'exchange' END AS settle_source,
               b.volume, b.transactions
        FROM bars b LEFT JOIN ({exch}) x USING (ticker) ORDER BY b.ticker"""


def minute_sql(store: str, staging: list[Path], trade_date: str, siblings: list[Path]) -> str:
    """Minute store (stock_minute / option_minute): best source per ticker."""
    asset = "stock" if store == "stock_minute" else "option"
    # Sources are ranked per (ticker, segment): an overnight venue (OCEA) adds
    # the night bars without displacing the daytime source.
    base = f"""
        WITH src AS (
            SELECT z.*, CASE WHEN {NIGHT_SQL} THEN 'night' ELSE 'day' END AS seg
            FROM read_parquet({_staging_list(staging)}) z
            WHERE asset = '{asset}' AND kind = 'm' AND trade_date = DATE '{trade_date}'
              {_excluded_by_segment(siblings)}
        ),
        rank AS (
            SELECT ticker, seg, src, row_number() OVER (
                PARTITION BY ticker, seg ORDER BY max(drank) DESC, sum(volume) DESC, src) AS rn
            FROM src GROUP BY ticker, seg, src
        ),
        bars AS (
            SELECT s.* FROM src s JOIN rank r USING (ticker, seg, src) WHERE r.rn = 1
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
    Overnight (20:00-04:00 ET) bars never enter a daily bar.
    """
    asset = "stock" if store == "stock_daily" else "option"
    rth = "et_min BETWEEN 570 AND 959" if asset == "stock" else "et_min IS NOT NULL"
    return f"""
        WITH raw AS (
            SELECT * FROM read_parquet({_staging_list(staging)})
            WHERE asset = '{asset}' AND trade_date = DATE '{trade_date}'
              AND NOT {NIGHT_SQL}
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
    if store == "future_minute":
        return future_minute_sql(staging, trade_date, siblings)
    if store == "future_daily":
        return future_daily_sql(staging, trade_date, siblings)
    if store in ("stock_minute", "option_minute"):
        return minute_sql(store, staging, trade_date, siblings)
    return daily_sql(store, staging, trade_date, siblings)


STORES_FOR_ASSET = {
    "stock": ("stock_daily", "stock_minute"),
    "option": ("option_day", "option_minute"),
    "future": ("future_daily", "future_minute"),
}
STORE_ASSET = {s: a for m in (STORES_FOR_ASSET, QUOTE_STORES_FOR_ASSET)
               for a, stores in m.items() for s in stores}


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
    if partition_dir.parent.name in ("stock_minute", "option_minute"):
        et = f"timezone('{_ET}', to_timestamp(z.window_start // 1000000000))"
        night = (f"(date_part('hour', {et}) >= 20 OR date_part('hour', {et}) < 4)")
        cond = _excluded_by_segment(sibs, night)
    else:
        cond = _excluded(sibs)
    con.execute(
        f"COPY (SELECT z.* FROM read_parquet('{_lit(ours)}') z WHERE TRUE{cond}) "
        f"TO '{_lit(tmp)}' ({parquet_options()})")
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
