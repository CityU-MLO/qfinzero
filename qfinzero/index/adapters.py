"""Adapters: recognise one raw file from its contents and describe it.

Each adapter's ``describe(path)`` returns a :class:`Described` (one catalogue
row, the parquet row-group statistics, the symbols with row counts) or
``None`` when the file is not its kind. Paths only break ties (massive's
asset class); a file is never accepted on its name alone.
"""

from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Optional

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
MONTH_RE = re.compile(r"(?<!\d)(\d{4}-\d{2})(?!-\d)")
MANIFEST = "qfz.dataset.yaml"
# row groups this size or smaller (or a page index) make a sorted file fast to look up (L2)
FAST_ROW_GROUP = 131_072
# Per-file symbol lists pay off for files cut per symbol (Databento, most
# custom data). A whole-market day file (massive: up to a million OPRA contracts)
# is not listed; its row groups' symbol ranges already prune lookups.
MAX_LISTED_SYMBOLS = 10_000
MASSIVE_AGG_COLUMNS = {"ticker", "volume", "open", "close", "high", "low", "window_start", "transactions"}
MASSIVE_ASSET = {"us_options_opra": "option", "us_stocks_sip": "stock", "us_indices": "index",
                 "global_crypto": "crypto", "global_forex": "fx"}


@dataclass
class Described:
    adapter: str
    vendor: str
    kind: str                         # bar | quote | trade | book | reference
    asset_class: Optional[str] = None
    market: Optional[str] = None
    dataset: Optional[str] = None
    schema: Optional[str] = None
    resolution: Optional[str] = None
    trade_date_min: Optional[str] = None
    trade_date_max: Optional[str] = None
    ts_min: Optional[int] = None
    ts_max: Optional[int] = None
    rows: Optional[int] = None
    access: str = "scan"              # seek | scan | whole
    level: str = "L1"                 # L0 | L1 | L2
    scope: str = "in"                 # in | out | error
    note: str = ""
    row_groups: list[dict[str, Any]] = field(default_factory=list)
    symbols: dict[str, int] = field(default_factory=dict)
    symbols_listed: bool = True       # False: the file's symbols are not enumerated (see MAX_LISTED_SYMBOLS)


def _pq_meta(path: Path):
    import pyarrow.parquet as pq
    pf = pq.ParquetFile(path)
    return pf, pf.metadata, pf.schema_arrow


def _row_groups(md, col: Optional[int]) -> tuple[list[dict[str, Any]], bool, bool]:
    """Row-group stats of the symbol column; (rows, in order across groups, page index present)."""
    out, ordered, page_index, prev = [], True, False, None
    for i in range(md.num_row_groups):
        rg = md.row_group(i)
        lo = hi = None
        if col is not None:
            c = rg.column(col)
            page_index = page_index or bool(getattr(c, "has_offset_index", False))
            st = c.statistics
            if st is not None and st.has_min_max:
                lo, hi = str(st.min), str(st.max)
                if prev is not None and lo < prev:
                    ordered = False
                prev = hi
        out.append({"rg": i, "rows": rg.num_rows, "symbol_min": lo, "symbol_max": hi})
    return out, ordered, page_index


def _level(row_groups: list[dict[str, Any]], ordered: bool, page_index: bool) -> tuple[str, str]:
    if not row_groups or row_groups[0]["symbol_min"] is None:
        return "L0", "no symbol statistics"
    if not ordered:
        return "L1", "row groups not in symbol order"
    if page_index or max(r["rows"] for r in row_groups) <= FAST_ROW_GROUP:
        return "L2", ""
    return "L1", f"row groups up to {max(r['rows'] for r in row_groups):,} rows (fast lookups need <= {FAST_ROW_GROUP:,} or a page index)"


def _symbol_counts(path: Path, column: str) -> Optional[dict[str, int]]:
    """Rows per symbol, or ``None`` when the file holds more than MAX_LISTED_SYMBOLS."""
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    t = pq.read_table(path, columns=[column])
    vc = pc.value_counts(t.column(0))
    if len(vc) > MAX_LISTED_SYMBOLS:
        return None
    return {str(v["values"]): int(v["counts"]) for v in vc.to_pylist() if v["values"] is not None}


def _ns_range(md, schema, col_name: str) -> tuple[Optional[int], Optional[int]]:
    try:
        idx = schema.get_field_index(col_name)
    except KeyError:
        return None, None
    if idx < 0:
        return None, None
    lo = hi = None
    for i in range(md.num_row_groups):
        st = md.row_group(i).column(idx).statistics
        if st is None or not st.has_min_max:
            return None, None
        lo = st.min if lo is None else min(lo, st.min)
        hi = st.max if hi is None else max(hi, st.max)
    return (int(lo), int(hi)) if lo is not None else (None, None)


# ── massive ───────────────────────────────────────────────────────────────

def _massive_asset(path: Path) -> Optional[str]:
    return next((a for part, a in MASSIVE_ASSET.items() if part in path.parts), None)


def massive_aggs(path: Path, symbols: bool = True) -> Optional[Described]:
    if not path.name.endswith(".parquet") or not ({"minute_aggs_v1", "day_aggs_v1"} & set(path.parts)):
        return None
    pf, md, schema = _pq_meta(path)
    if not MASSIVE_AGG_COLUMNS <= set(schema.names):
        return None
    m = DATE_RE.search(path.name)
    d = m.group(1) if m else None
    rgs, ordered, pidx = _row_groups(md, schema.get_field_index("ticker"))
    level, note = _level(rgs, ordered, pidx)
    lo, hi = _ns_range(md, schema, "window_start")
    asset = _massive_asset(path)
    notes = [note] if note else []
    if str(schema.field("volume").type) != "int64":
        notes.append("fractional volume (rounded to integer)")
    return Described(
        adapter="massive.aggs", vendor="massive", kind="bar", asset_class=asset,
        market="global" if asset in ("crypto", "fx") else "us",
        dataset=next((p for p in MASSIVE_ASSET if p in path.parts), None),
        schema="minute_aggs_v1" if "minute_aggs_v1" in path.parts else "day_aggs_v1",
        resolution="1m" if "minute_aggs_v1" in path.parts else "1d",
        trade_date_min=d, trade_date_max=d, ts_min=lo, ts_max=hi, rows=md.num_rows,
        access="seek", level=level, note="; ".join(notes), row_groups=rgs, symbols_listed=False)


def massive_quotes(path: Path, symbols: bool = True) -> Optional[Described]:
    if not path.name.endswith(".parquet") or "quotes_v1" not in path.parts:
        return None
    pf, md, schema = _pq_meta(path)
    if not {"ticker", "bid_price", "ask_price"} <= set(schema.names):
        return None
    m = DATE_RE.search(str(path))
    d = m.group(1) if m else None
    rgs, ordered, pidx = _row_groups(md, schema.get_field_index("ticker"))
    level, note = _level(rgs, ordered, pidx)
    ts_col = "sip_timestamp" if "sip_timestamp" in schema.names else "window_start"
    lo, hi = _ns_range(md, schema, ts_col)
    return Described(adapter="massive.quotes", vendor="massive", kind="quote", asset_class=_massive_asset(path),
                     market="us", schema="quotes_v1", resolution="tick", trade_date_min=d, trade_date_max=d,
                     ts_min=lo, ts_max=hi, rows=md.num_rows, access="seek", level=level, note=note,
                     row_groups=rgs, symbols_listed=False)


def massive_trades(path: Path, symbols: bool = True) -> Optional[Described]:
    if not path.name.endswith(".parquet") or "trades_v1" not in path.parts:
        return None
    _, md, schema = _pq_meta(path)
    if not {"ticker", "price", "size", "sip_timestamp"} <= set(schema.names):
        return None
    m = DATE_RE.search(path.name)
    d = m.group(1) if m else None
    rgs, ordered, pidx = _row_groups(md, schema.get_field_index("ticker"))
    level, note = _level(rgs, ordered, pidx)
    lo, hi = _ns_range(md, schema, "sip_timestamp")
    return Described(adapter="massive.trades", vendor="massive", kind="trade", asset_class=_massive_asset(path),
                     market="us", dataset=next((p for p in MASSIVE_ASSET if p in path.parts), None),
                     schema="trades_v1", resolution="tick", trade_date_min=d, trade_date_max=d, ts_min=lo, ts_max=hi,
                     rows=md.num_rows, access="seek", level=level, note=note, row_groups=rgs, symbols_listed=False)


# massive / Benzinga files that are not prices: news, ratings, corporate actions,
# economy (used by ESP and the corporate-actions build, not by the market-data index)
REFERENCE_DIRS = {"benzinga": "benzinga", "corporate_actions": "corporate_actions", "economy": "economy"}


def massive_reference(path: Path, symbols: bool = True) -> Optional[Described]:
    if not path.name.endswith((".jsonl", ".jsonl.gz", ".json")):
        return None
    top = next((p for p in path.parts if p in REFERENCE_DIRS), None)
    if top is None:
        return None
    sub = path.parts[path.parts.index(top) + 1] if path.parts.index(top) + 1 < len(path.parts) - 1 else None
    m = DATE_RE.search(path.name)
    return Described(adapter="massive.reference", vendor="massive", kind="event", dataset=top, schema=sub,
                     trade_date_min=m.group(1) if m else None, trade_date_max=m.group(1) if m else None,
                     access="whole", level="L0", note="not prices (news, ratings, corporate actions, economy)",
                     symbols_listed=False)


def massive_global(path: Path, symbols: bool = True) -> Optional[Described]:
    if not path.name.endswith(".csv.gz") or _massive_asset(path) not in ("crypto", "fx"):
        return None
    with gzip.open(path, "rt") as fh:
        header = fh.readline().strip().split(",")
    if "ticker" not in header:
        return None
    m = DATE_RE.search(path.name)
    d = m.group(1) if m else None
    quotes = "quotes_v1" in path.parts
    trades = "trades_v1" in path.parts
    return Described(adapter="massive.global", vendor="massive",
                     kind="quote" if quotes else ("trade" if trades else "bar"),
                     asset_class=_massive_asset(path), market="global",
                     dataset=next((p for p in ("global_crypto", "global_forex") if p in path.parts), None),
                     schema=next((p for p in ("minute_aggs_v1", "day_aggs_v1", "quotes_v1", "trades_v1")
                                  if p in path.parts), None),
                     resolution="tick" if (quotes or trades) else ("1m" if "minute_aggs_v1" in path.parts else "1d"),
                     trade_date_min=d, trade_date_max=d, access="whole", level="L0",
                     note="gzip CSV: read whole (materialised)", symbols_listed=False)


# ── Databento ─────────────────────────────────────────────────────────────

_DB_KIND = {"trades": "trade", "ohlcv": "bar", "quotes": "quote"}


def databento(path: Path, symbols: bool = True) -> Optional[Described]:
    from qfinzero.pipeline.sources import databento as db
    if not db.is_raw_file(path):
        return None
    if path.name.endswith(".parquet"):
        # a Databento export carries rtype/ts_event/symbol; anything else is not ours
        _, _, schema = _pq_meta(path)
        if not {"rtype", "ts_event", "symbol"} <= set(schema.names):
            return None
    info = db.describe(path)
    if info.error and not info.schema:
        return Described(adapter="databento", vendor="databento", kind="reference", scope="error", level="L0",
                         note=info.error)
    kind = "book" if info.schema == "mbo" else _DB_KIND.get(info.role, "reference")
    res = None
    if info.schema:
        m = re.search(r"(\d+[smhd])$", info.schema)
        res = m.group(1) if m else ("1d" if info.schema == "ohlcv-eod" else "tick")
    whole = path.name.endswith(".zst")
    return Described(
        adapter="databento", vendor="databento", kind=kind, asset_class=info.asset,
        market="us" if info.asset in ("stock", "option") else ("global" if info.asset == "future" else None),
        dataset=info.dataset, schema=info.schema, resolution=res,
        trade_date_min=info.start, trade_date_max=info.end,
        access="whole" if whole else "scan", level="L1",
        scope="out" if info.out_of_scope else ("error" if info.error else "in"),
        note="; ".join(x for x in (
            "out of scope (QFinZero stops at consolidated BBO)" if info.out_of_scope else "",
            "single zstd frame: decoded whole (materialised)" if whole else "", info.error or "") if x),
        symbols={s: 0 for s in info.symbols})


# ── QFZ standard (custom data with a manifest) ────────────────────────────

REQUIRED = {"bar": ("ticker", "open", "high", "low", "close"), "quote": ("ticker", "bid_price", "ask_price"),
            "trade": ("ticker", "price", "size")}
KINDS = set(REQUIRED)
TIME_UNITS = {"s", "ms", "us", "ns", "iso"}


def find_manifest(path: Path, stop: Optional[Path] = None) -> Optional[Path]:
    for d in path.parents:
        m = d / MANIFEST
        if m.exists():
            return m
        if stop is not None and d == stop:
            break
    return None


def load_manifest(path: Path) -> dict[str, Any]:
    import yaml
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(doc, dict) or doc.get("qfz_dataset") != 1:
        raise ValueError(f"{path}: qfz_dataset: 1 expected")
    kind = doc.get("kind")
    if kind not in KINDS:
        raise ValueError(f"{path}: kind must be one of {sorted(KINDS)}")
    t = doc.get("time") or {}
    if t.get("unit", "ns") not in TIME_UNITS:
        raise ValueError(f"{path}: time.unit must be one of {sorted(TIME_UNITS)}")
    if t.get("unit") == "iso" and not t.get("timezone") and not t.get("has_offset"):
        raise ValueError(f"{path}: ISO times without an offset need time.timezone")
    return doc


def standard(path: Path, symbols: bool = True, manifest: Optional[Path] = None) -> Optional[Described]:
    if not path.name.endswith(".parquet"):
        return None
    manifest = manifest or find_manifest(path)
    if manifest is None:
        return None
    try:
        doc = load_manifest(manifest)
    except Exception as e:  # noqa: BLE001 - report the manifest problem on each file
        return Described(adapter="qfz.standard", vendor="custom", kind="reference", scope="error", level="L0",
                         note=str(e))
    import fnmatch
    pattern = doc.get("files") or "**/*.parquet"
    rel = path.relative_to(manifest.parent).as_posix()
    if not (fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(rel, pattern.replace("**/", ""))):
        return None
    _, md, schema = _pq_meta(path)
    rename = {k: v for k, v in (doc.get("columns") or {}).items()}
    std = {rename.get(c, c): c for c in schema.names}           # standard name -> file column
    tcol = (doc.get("time") or {}).get("column") or ("window_start" if doc.get("resolution") != "1d" else "trade_date")
    missing = [f for f in REQUIRED[doc["kind"]] if f not in std] + ([] if tcol in schema.names else [f"time column {tcol!r}"])
    sym_col = std.get("ticker")
    rgs, ordered, pidx = _row_groups(md, schema.get_field_index(sym_col) if sym_col else None)
    level, note = _level(rgs, ordered, pidx) if not missing else ("L0", "")
    m = DATE_RE.search(rel)
    counts = _symbol_counts(path, sym_col) if (symbols and sym_col and not missing) else None
    if counts is None and sym_col and not missing:
        note = "; ".join(x for x in (note, f"symbols not listed (more than {MAX_LISTED_SYMBOLS:,})") if x)
    return Described(
        adapter="qfz.standard", vendor=str(doc.get("vendor") or "custom"), kind=doc["kind"],
        asset_class=doc.get("asset_class"), market=doc.get("market"), dataset=str(doc.get("name") or manifest.parent.name),
        resolution=doc.get("resolution"), trade_date_min=m.group(1) if m else None,
        trade_date_max=m.group(1) if m else None, rows=md.num_rows, access="seek", level=level,
        scope="error" if missing else "in",
        note=("missing " + ", ".join(missing)) if missing else note, row_groups=rgs,
        symbols=counts or {}, symbols_listed=counts is not None)


ADAPTERS: list[tuple[str, Callable[..., Optional[Described]]]] = [
    ("qfz.standard", standard),        # a manifest wins over any vendor guess
    ("massive.aggs", massive_aggs),
    ("massive.quotes", massive_quotes),
    ("massive.trades", massive_trades),
    ("massive.global", massive_global),
    ("massive.reference", massive_reference),
    ("databento", databento),
]


def manifest_file(path: Path) -> Described:
    try:
        doc = load_manifest(path)
        return Described(adapter="qfz.standard", vendor=str(doc.get("vendor") or "custom"), kind="manifest",
                         dataset=str(doc.get("name") or path.parent.name), asset_class=doc.get("asset_class"),
                         market=doc.get("market"), resolution=doc.get("resolution"), level="L0")
    except Exception as e:  # noqa: BLE001
        return Described(adapter="qfz.standard", vendor="custom", kind="manifest", scope="error", level="L0",
                         note=str(e))


def describe(path: Path, symbols: bool = True) -> Optional[Described]:
    """The first adapter that recognises ``path`` (``None``: not market data we know)."""
    if path.name == MANIFEST:
        return manifest_file(path)
    errors = []
    for name, fn in ADAPTERS:
        try:
            d = fn(path, symbols=symbols)
        except Exception as e:  # noqa: BLE001 - a broken file is reported, never fatal
            errors.append(f"{name}: {type(e).__name__}: {e}")
            continue
        if d is not None:
            return d
    if errors and path.suffix in (".parquet", ".zst", ".dbn", ".gz"):
        return Described(adapter="unknown", vendor="unknown", kind="reference", scope="error", level="L0",
                         note=errors[0][:300])
    return None
