"""Scan data directories in place and keep the catalogue under ``_state/index/``.

Output (rewritten atomically on every scan):

* ``catalog.parquet``    one row per file: fingerprint, adapter, kind, asset,
  resolution, trade-date and time range, rows, access, level, scope, note;
* ``row_groups.parquet`` parquet row groups: rows, symbol min/max;
* ``symbols.parquet``    (symbol, path, rows) - rows is 0 when only the header
  names the symbol (Databento, Tiingo);
* ``scan.json``          the last scan's report.

A file whose size and mtime are unchanged is not read again. Files are only
ever read; nothing is written into a data directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import adapters

VERSION = 2   # bump when an adapter changes: cached rows are then read again
SKIP_DIRS = {"_state", "_staging", ".git", "__pycache__", "node_modules"}
CATALOG_COLUMNS = ["path", "root", "size", "mtime_ns", "head_hash", "adapter", "vendor", "kind", "asset_class",
                   "market", "dataset", "schema", "resolution", "trade_date_min", "trade_date_max", "ts_min",
                   "ts_max", "rows", "access", "level", "scope", "note", "symbols"]


def index_dir(storage: Path) -> Path:
    return Path(storage) / "_state" / "index"


def head_hash(path: Path, n: int = 65536) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha1(fh.read(n)).hexdigest()[:16]


def walk(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for f in sorted(filenames):
            if not f.startswith(".") and not f.endswith((".tmp", ".part")):
                yield Path(dirpath) / f


def _read_previous(idx: Path) -> dict[str, dict[str, Any]]:
    """Last catalogue rows by path, with their row groups and symbols."""
    cat = idx / "catalog.parquet"
    if not cat.exists():
        return {}
    import pyarrow.parquet as pq
    meta = json.loads((idx / "scan.json").read_text()).get("version") if (idx / "scan.json").exists() else None
    if meta != VERSION:
        return {}
    rows = {r["path"]: {"row": r, "row_groups": [], "symbols": {}} for r in pq.read_table(cat).to_pylist()}
    if (idx / "row_groups.parquet").exists():
        for r in pq.read_table(idx / "row_groups.parquet").to_pylist():
            if r["path"] in rows:
                rows[r["path"]]["row_groups"].append({k: r[k] for k in ("rg", "rows", "symbol_min", "symbol_max")})
    if (idx / "symbols.parquet").exists():
        for r in pq.read_table(idx / "symbols.parquet").to_pylist():
            if r["path"] in rows:
                rows[r["path"]]["symbols"][r["symbol"]] = r["rows"]
    return rows


def _describe_one(path: Path, root: Path, symbols: bool) -> dict[str, Any]:
    st = path.stat()
    d = adapters.describe(path, symbols=symbols)
    if d is None:
        return {"row": {"path": str(path), "root": str(root), "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                        "adapter": None, "scope": "unknown"}, "row_groups": [], "symbols": {}}
    rec = asdict(d)
    rg, syms, listed = rec.pop("row_groups"), rec.pop("symbols"), rec.pop("symbols_listed")
    rec.update(path=str(path), root=str(root), size=st.st_size, mtime_ns=st.st_mtime_ns,
               head_hash=head_hash(path), symbols=len(syms) if listed else None)
    return {"row": rec, "row_groups": rg, "symbols": syms}


def _write(idx: Path, entries: list[dict[str, Any]]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq
    idx.mkdir(parents=True, exist_ok=True)
    cat = [{c: e["row"].get(c) for c in CATALOG_COLUMNS} for e in entries]
    types = {"size": pa.int64(), "mtime_ns": pa.int64(), "ts_min": pa.int64(), "ts_max": pa.int64(),
             "rows": pa.int64(), "symbols": pa.int64()}
    schema = pa.schema([(c, types.get(c, pa.string())) for c in CATALOG_COLUMNS])
    rgs = [{"path": e["row"]["path"], **r} for e in entries for r in e["row_groups"]]
    syms = [{"symbol": s, "path": e["row"]["path"], "rows": n} for e in entries for s, n in e["symbols"].items()]
    tables = {
        "catalog.parquet": pa.Table.from_pylist(cat, schema=schema),
        "row_groups.parquet": pa.Table.from_pylist(rgs, schema=pa.schema(
            [("path", pa.string()), ("rg", pa.int32()), ("rows", pa.int64()),
             ("symbol_min", pa.string()), ("symbol_max", pa.string())])),
        "symbols.parquet": pa.Table.from_pylist(sorted(syms, key=lambda r: (r["symbol"], r["path"])), schema=pa.schema(
            [("symbol", pa.string()), ("path", pa.string()), ("rows", pa.int64())])),
    }
    for name, t in tables.items():
        tmp = idx / f".{name}.tmp"
        pq.write_table(t, tmp, compression="zstd")
        os.replace(tmp, idx / name)


def summarize(rows: list[dict[str, Any]], elapsed: float, read: int, reused: int) -> dict[str, Any]:
    groups: dict[tuple, dict[str, Any]] = {}
    unknown = [r for r in rows if r.get("scope") == "unknown"]
    for r in rows:
        if r.get("scope") == "unknown":
            continue
        k = (r.get("adapter"), r.get("vendor"), r.get("dataset"), r.get("schema"), r.get("kind"),
             r.get("asset_class"), r.get("resolution"), r.get("scope"))
        g = groups.setdefault(k, {"files": 0, "bytes": 0, "rows": 0, "first": None, "last": None,
                                  "levels": {}, "notes": {}})
        g["files"] += 1
        g["bytes"] += r.get("size") or 0
        g["rows"] += r.get("rows") or 0
        for side, fn in (("first", min), ("last", max)):
            v = r.get("trade_date_min" if side == "first" else "trade_date_max")
            if v:
                g[side] = v if g[side] is None else fn(g[side], v)
        g["levels"][r.get("level")] = g["levels"].get(r.get("level"), 0) + 1
        for n in (r.get("note") or "").split("; "):
            if n:
                # "row groups up to 478,601 rows" and "... 176,852 rows" are one kind of note
                k = re.sub(r"\bup to [\d,]+ rows", "too large", n)
                g["notes"][k] = g["notes"].get(k, 0) + 1
                if k != n:
                    m = int(re.search(r"up to ([\d,]+)", n).group(1).replace(",", ""))
                    g["max_row_group"] = max(g.get("max_row_group", 0), m)
    keys = ("adapter", "vendor", "dataset", "schema", "kind", "asset_class", "resolution", "scope")
    out = [{**dict(zip(keys, k)), **v} for k, v in groups.items()]
    out.sort(key=lambda g: (g["vendor"] or "", g["dataset"] or "", g["schema"] or "", g["asset_class"] or ""))
    return {"version": VERSION, "elapsed_s": round(elapsed, 1), "files": len(rows), "read": read, "reused": reused,
            "groups": out, "unknown": {"files": len(unknown), "bytes": sum(r.get("size") or 0 for r in unknown),
                                       "examples": [r["path"] for r in unknown[:20]]}}


def scan(roots: Iterable[str | Path], storage: str | Path, *, symbols: bool = True, threads: int = 8,
         on_line: Optional[Callable[[str], None]] = None, on_progress: Optional[Callable[..., None]] = None,
         should_stop: Optional[Callable[[], bool]] = None) -> dict[str, Any]:
    """Catalogue every file under ``roots``; return the scan report."""
    say = on_line or (lambda _l: None)
    prog = on_progress or (lambda **_k: None)
    stop = should_stop or (lambda: False)
    t0 = time.time()
    idx = index_dir(Path(storage))
    prev = _read_previous(idx)
    roots = [Path(r).expanduser().resolve() for r in roots]
    files = [(p, r) for r in roots if r.is_dir() for p in walk(r)]
    missing = [str(r) for r in roots if not r.is_dir()]
    say(f"[scan] {len(files):,} files under {len(roots)} director{'y' if len(roots) == 1 else 'ies'}")
    prog(stage="scanning", files_total=len(files), files_done=0)
    entries: list[Optional[dict[str, Any]]] = [None] * len(files)
    todo = []
    for i, (p, r) in enumerate(files):
        e = prev.get(str(p))
        try:
            st = p.stat()
        except OSError:
            continue
        if e and e["row"].get("size") == st.st_size and e["row"].get("mtime_ns") == st.st_mtime_ns:
            e["row"]["root"] = str(r)
            entries[i] = e
        else:
            todo.append(i)
    reused = len(files) - len(todo)
    say(f"[scan] {reused:,} unchanged, {len(todo):,} to read")
    done = 0

    def work(i):
        if stop():
            return i, None
        p, r = files[i]
        try:
            return i, _describe_one(p, r, symbols)
        except OSError as e:
            return i, {"row": {"path": str(p), "root": str(r), "adapter": None, "scope": "error",
                               "note": f"{type(e).__name__}: {e}"}, "row_groups": [], "symbols": {}}

    with ThreadPoolExecutor(max(1, threads)) as ex:
        for i, e in ex.map(work, todo):
            entries[i] = e
            done += 1
            if done % 500 == 0 or done == len(todo):
                say(f"[scan] {done:,}/{len(todo):,} read")
                prog(files_done=reused + done)
    if stop():
        say("[scan] stopped by the user; the previous index is kept")
        return {"ok": False, "stopped": True}
    kept = [e for e in entries if e is not None]
    # directories not scanned this time keep their entries
    inside = tuple(str(r).rstrip("/") + "/" for r in roots)
    others = [e for p, e in prev.items() if not p.startswith(inside)]
    kept += others
    _write(idx, kept)
    report = summarize([e["row"] for e in kept], time.time() - t0, len(todo), reused)
    all_roots = sorted({str(r) for r in roots} | {e["row"].get("root") for e in others if e["row"].get("root")})
    report.update(ok=True, roots=all_roots, scanned=[str(r) for r in roots], missing_roots=missing, index=str(idx))
    (idx / "scan.json").write_text(json.dumps(report, indent=1, default=str))
    say(f"[scan] {len(kept):,} files catalogued in {report['elapsed_s']} s -> {idx}")
    return report


def last_report(storage: str | Path) -> Optional[dict[str, Any]]:
    p = index_dir(Path(storage)) / "scan.json"
    return json.loads(p.read_text()) if p.exists() else None
